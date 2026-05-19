#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/diagnostics_failure_explanation_convergence.py
=====================================================
PR-10V2: Diagnostics / Failure / Explanation Semantic Boundary Convergence.

Purpose
-------
This module is the **single authoritative boundary declaration** for the
diagnostics, failure, artifact, summary, and explanation semantic domains
in the Galaxy/OpenClawd system.

It builds directly on:

* PR-9 ``core.runtime_truth_output_chain`` — Stage 1 → Stage 2 → Stage 3
  truth output chain.
* PR-9V2 ``core.distributed_truth_ownership_convergence`` — four-domain
  ownership taxonomy (authority_truth / acceptance_closure_readiness_truth /
  outward_projection_operator_truth / diagnostics_audit_artifact).
* PR-4V2-GOV ``core.android_evaluator_artifact_ingress`` — canonical ingress
  for Android evaluator artifacts.
* PR-13 ``core.failure_degraded_recovery_policy`` — failure/degraded/recovery
  runtime truth propagation.

Problem addressed
-----------------
After PRs #7–#9V2, the system clearly declares four truth-domain kinds and an
explicit Stage 1 → Stage 2 → Stage 3 output chain.  However the system still
lacks a **single declaration** that answers the following diagnostics/failure-
specific questions:

1. Which surfaces produce *authority runtime truth* for execution failures?
   (Failure states reported by DesktopPresenceRuntime, TaskGraphRuntime,
   CommandRouter — these are runtime authority decisions.)
2. Which surfaces produce *failure/diagnostics truth*?
   (Structured failure classifications, degraded-state records, trace artefacts
   that describe *what happened* without deciding *what is authoritative now*.)
3. Which surfaces produce *artifact truth*?
   (Evaluated artefacts from Android evaluators, execution artefacts from
   task chains — evidence records, not closure/acceptance decisions.)
4. Which surfaces produce *operator-facing summary/explanation*?
   (Human-readable descriptions of failure outcomes, routing decisions, or
   operator projections — assembled from truth, never authoritative sources.)
5. Which surfaces produce *audit/post-run interpretation*?
   (Post-hoc forensic records, audit stores, repo goal audit projections —
   produced after the fact, never as real-time authority inputs.)

Without this explicit five-domain classification the following risks persist:

* Summary / explanation text is implicitly treated as authority truth by
  consumers who conflate a failure description with the failure itself.
* Artifact truth (Android evaluator artefacts, execution chain artefacts)
  is mixed with closure/acceptance truth in gate evaluations.
* Diagnostics snapshots are read back as inputs to acceptance or closure
  gates, creating circular authority.
* Operator-facing explanations (routing explanation, projection explanation)
  claim authority beyond their read-only role.
* Post-run audit interpretation (repo_goal_audit, projection audit) are
  confused with live runtime truth.

This module resolves that ambiguity by:

1. Declaring five *diagnostic/failure/explanation semantic kinds* with
   explicit role and read-only/write constraints.
2. Classifying every surface that touches failure, diagnostics, artifact,
   summary, explanation, or audit into exactly one of those five kinds.
3. Providing policy sentinels that prevent summary/explanation from
   redefining authority truth and diagnostics from being read back as
   acceptance inputs.
4. Declaring how Android-side diagnostics/failure/artifact uplink integrates
   into the V2 canonical truth chain.
5. Providing a snapshot builder for operator / CI visibility.

This module does NOT introduce new runtime logic, new storage, or a new
diagnostics platform.  It consolidates existing boundary declarations so
that the diagnostics/failure/explanation narrative is unambiguous.

Five diagnostic semantic kinds
-------------------------------
AUTHORITY_EXECUTION_TRUTH
    Runtime authority decisions about execution state: running, failed,
    completed, aborted.  These are produced by DesktopPresenceRuntime,
    TaskGraphRuntime, CommandRouter, and the canonical execution chain.
    They are the sources of canonical failure and success truth.
    *Constraint*: produced by authority modules; downstream surfaces read them.

FAILURE_DIAGNOSTICS_TRUTH
    Structured failure and degraded-state records that describe *what happened*
    in a failure episode.  These are produced by failure_degraded_recovery_policy,
    failure_domains, FailureClassification, and error_framework.
    They record failure state for operator and CI visibility; they do NOT
    substitute for authority execution truth.
    *Constraint*: MUST NOT be read back as inputs to acceptance/closure gates.

ARTIFACT_EVIDENCE_TRUTH
    Evaluated artefacts produced by Android evaluators (readiness, acceptance,
    governance, strategy) and V2 execution chain artefacts.  These are evidence
    records: structured outputs of evaluation processes.
    *Constraint*: artifact evidence informs gate evaluation but MUST NOT be
    confused with closure/acceptance decisions; artifact truth ≠ closure truth.

OPERATOR_SUMMARY_EXPLANATION
    Human-readable summaries, explanations, and projections assembled for
    operator dashboards, routing explanation endpoints, and operator console
    surfaces.  These are compiled from truth (Stage 2 outward truth) and MUST
    NOT redefine or reverse-inject into authority truth.
    *Constraint*: read-only consumers of Stage 2 outward truth; may not claim
    authority over what is canonical runtime state.

AUDIT_POSTRUN_INTERPRETATION
    Post-hoc forensic records, audit stores, repo goal audit projections, and
    post-run interpretation surfaces.  These are produced after execution
    completes and are for post-hoc analysis only.
    *Constraint*: MUST NOT be used as real-time authority or acceptance inputs;
    audit interpretation is retrospective, not prescriptive.

Android ↔ V2 diagnostics/failure/artifact uplink
-------------------------------------------------
Android-originated diagnostics and failure signals enter the V2 canonical
chain via the following declared path::

    Android diagnostics / failure / evaluator artifact
        └─ galaxy_gateway.android.handlers.*          (ingress gateway)
              └─ core.android_evaluator_artifact_ingress  (artifact ingress)
              │      → AndroidEvaluatorArtifactRegistry   (evidence store)
              └─ core.android_participant_truth_ingress    (failure signal)
                    └─ core.v2_android_truth_ssot          (SSOT build)
                          └─ core.canonical_session_truth  (merge + record)
                                └─ Stage 1: compile_runtime_truth()
                                      └─ Stage 2: compile_outward_truth()
                                            └─ Stage 3: projection surfaces

Android evaluator artefacts (readiness/acceptance/governance/strategy) are
evidence records (ARTIFACT_EVIDENCE_TRUTH) and MUST NOT be confused with
closure or acceptance truth from the acceptance chain.

Android failure signals that reach ``build_v2_android_truth_block()`` become
AUTHORITY_EXECUTION_TRUTH.  Failure signals that stop before reaching the
SSOT are FAILURE_DIAGNOSTICS_TRUTH (advisory/local-only).

Policy invariants
-----------------
1. Summary / explanation text (OPERATOR_SUMMARY_EXPLANATION) MUST NOT
   redefine, override, or reverse-inject into authority execution truth.
   Summary text describes; it does not decide.

2. Diagnostics / failure records (FAILURE_DIAGNOSTICS_TRUTH) MUST NOT be
   read back as inputs to acceptance or closure gate evaluation.

3. Artifact evidence (ARTIFACT_EVIDENCE_TRUTH) informs gate evaluation as
   input evidence but MUST NOT be confused with the acceptance/closure decision
   itself.  The artifact is a gate input; the gate output is acceptance truth.

4. Post-run audit interpretation (AUDIT_POSTRUN_INTERPRETATION) MUST NOT
   be used as real-time authority inputs or live acceptance decisions.

5. No new parallel diagnostics platform, failure explanation service, or
   explanation authority layer is introduced by this PR.

Public API
----------
Authority sentinels::

    DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY
    DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL

Policy sentinels::

    SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY
    DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY
    ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY
    AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY
    NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY

Enums::

    DiagnosticsSemanticKind

Data classes::

    DiagnosticsSemanticSurface
    DiagnosticsFailureConvergenceSnapshot

Functions::

    get_diagnostics_surface_registry()
    classify_diagnostics_semantic_kind(surface_id)
    get_surfaces_by_semantic_kind(kind)
    build_diagnostics_failure_convergence_snapshot()
    get_android_diagnostics_uplink_path()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple

__all__ = [
    # Authority sentinels
    "DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY",
    "DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL",
    # Policy sentinels
    "SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY",
    "DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY",
    "ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY",
    "AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY",
    "NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY",
    # Enums
    "DiagnosticsSemanticKind",
    # Data classes
    "DiagnosticsSemanticSurface",
    "DiagnosticsFailureConvergenceSnapshot",
    # Functions
    "get_diagnostics_surface_registry",
    "classify_diagnostics_semantic_kind",
    "get_surfaces_by_semantic_kind",
    "build_diagnostics_failure_convergence_snapshot",
    "get_android_diagnostics_uplink_path",
    # Registry (for direct inspection)
    "DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY",
]


# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY: str = (
    "DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY_V1: "
    "core.diagnostics_failure_explanation_convergence is the single authoritative "
    "boundary declaration for the diagnostics/failure/artifact/summary/explanation/"
    "audit semantic domains.  It classifies every diagnostics, failure, artifact, "
    "summary, explanation, and audit surface into one of five semantic kinds and "
    "locks the PR-10V2 boundary so that summary/explanation text cannot redefine "
    "authority execution truth and diagnostics records cannot be read back as "
    "acceptance or closure gate inputs."
)
"""Module-level authority sentinel for the diagnostics/failure/explanation
convergence boundary (PR-10V2)."""

DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL: str = (
    "diagnostics_failure_explanation_convergence_pr10v2_boundary_locked"
)
"""PR-10V2 sentinel value.  Tests and CI gates locking the PR-10V2 boundary
declaration must assert the presence of this sentinel."""


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY: str = (
    "SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY_V1: "
    "operator_summary_explanation surfaces (routing explanation, failure summary, "
    "operator projection description) MUST NOT redefine, override, or "
    "reverse-inject into authority execution truth; summary text is assembled from "
    "Stage 2 outward truth (compile_outward_truth) for operator visibility only; "
    "a human-readable failure description is NOT the canonical failure record — "
    "the canonical failure record is produced by authority modules such as "
    "DesktopPresenceRuntime, TaskGraphRuntime, and failure_degraded_recovery_policy"
)
"""Policy: summary/explanation text is read-only; it does not define truth."""

DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY: str = (
    "DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY_V1: "
    "failure_diagnostics_truth surfaces (failure_domains, FailureClassification, "
    "error_framework, diagnostics route) record failure episodes for operator and "
    "CI inspection; they MUST NOT be read back as inputs to acceptance gate "
    "evaluation, closure determination, or authority truth compilation; the "
    "acceptance/closure chain reads authority execution truth directly — it does "
    "not re-ingest diagnostics snapshots as truth signals"
)
"""Policy: diagnostics/failure records are write-once forensic surfaces."""

ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY: str = (
    "ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY_V1: "
    "artifact_evidence_truth surfaces (AndroidEvaluatorArtifactRegistry, "
    "android_evaluator_artifact_ingress, execution chain artefacts) produce "
    "structured evaluation records that are gate inputs — they are NOT the "
    "acceptance/closure decision itself; the gate that consumes an artifact "
    "and emits accept/reject is an acceptance_closure_readiness_truth surface; "
    "artifact truth ≠ closure truth; mixing them obscures whether a device has "
    "been accepted or merely evaluated"
)
"""Policy: artifact evidence is a gate input, not a closure/acceptance decision."""

AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY: str = (
    "AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY_V1: "
    "audit_postrun_interpretation surfaces (repo_goal_audit route, "
    "runtime_closure_audit, android_delegated_runtime_audit, "
    "post_closure_dual_repo_reassessment, projection audit) are post-hoc forensic "
    "records produced after execution events have been recorded by authority "
    "modules; they MUST NOT be used as real-time authority inputs, live acceptance "
    "decisions, or live gate-blocking signals; audit interpretation is retrospective "
    "— it describes what was decided, it does not make decisions"
)
"""Policy: audit/post-run records are retrospective; they do not make decisions."""

NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY: str = (
    "NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY_V1: "
    "this PR consolidates and declares existing diagnostics/failure/explanation "
    "boundaries; it does NOT introduce a new diagnostics platform, a new "
    "failure explanation service, a new incident response system, or a new "
    "observability stack alongside the existing one; extensions to diagnostics "
    "or failure handling must integrate into the existing "
    "failure_degraded_recovery_policy → runtime_truth_output_chain path, "
    "not alongside it"
)
"""Policy: no new parallel diagnostics platform or explanation authority layer."""


# ---------------------------------------------------------------------------
# Diagnostic semantic kind taxonomy
# ---------------------------------------------------------------------------


class DiagnosticsSemanticKind(str, Enum):
    """Five-kind taxonomy for diagnostics/failure/explanation semantic domains.

    Every surface that touches failure state, diagnostics records, evaluation
    artefacts, operator summaries/explanations, or audit/post-run interpretation
    is classified into exactly one of these five kinds.
    """

    authority_execution_truth = "authority_execution_truth"
    """Runtime authority decisions about execution state: running, failed,
    completed, aborted.  These are produced by DesktopPresenceRuntime,
    TaskGraphRuntime, CommandRouter, and the canonical execution chain.
    They are the canonical sources of failure and success truth.
    Examples: DesktopPresenceRuntime, TaskGraphRuntime, CommandRouter,
    failure_degraded_recovery_policy (as producer to runtime layers)."""

    failure_diagnostics_truth = "failure_diagnostics_truth"
    """Structured failure and degraded-state records describing what happened
    in a failure episode.  These are produced by failure_domains,
    FailureClassification, error_framework, and diagnostics route.
    They record failure state for operator / CI visibility; they MUST NOT be
    read back as acceptance/closure gate inputs.
    Examples: failure_domains, FailureClassification, error_framework,
    core.routes.diagnostics, failure_degraded_recovery_policy (as recorder)."""

    artifact_evidence_truth = "artifact_evidence_truth"
    """Evaluated artefacts from Android evaluators and V2 execution chain.
    These are evidence records that are gate inputs — NOT closure decisions.
    Examples: AndroidEvaluatorArtifactRegistry, android_evaluator_artifact_ingress,
    v2_readiness_governance_evidence_surface, execution chain artefacts."""

    operator_summary_explanation = "operator_summary_explanation"
    """Human-readable summaries, explanations, and projections assembled for
    operator dashboards and routing explanation endpoints.  These consume
    Stage 2 outward truth and MUST NOT redefine authority execution truth.
    Examples: core.routes.projection (explanation fields), routing_explanation,
    operator_surface, mesh_participation_summary, operator console."""

    audit_postrun_interpretation = "audit_postrun_interpretation"
    """Post-hoc forensic records, audit stores, and post-run interpretation
    surfaces produced after execution events have been recorded.  These MUST
    NOT be used as real-time authority inputs or live acceptance gate signals.
    Examples: runtime_closure_audit, android_delegated_runtime_audit,
    post_closure_dual_repo_reassessment, repo_goal_audit, audit_event_semantics."""


# ---------------------------------------------------------------------------
# Surface data class
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticsSemanticSurface:
    """Single surface entry in the diagnostics/failure/explanation registry.

    Parameters
    ----------
    surface_id:
        Short stable identifier (e.g. ``"failure_domains_classifier"``).
    module_path:
        Fully-qualified Python module path.
    surface_name:
        Human-readable surface name with brief role summary.
    semantic_kind:
        :class:`DiagnosticsSemanticKind` classification.
    may_not_redefine_authority_truth:
        ``True`` for all non-authority surfaces — they MUST NOT claim or
        redefine canonical runtime execution authority.
    android_diagnostics_uplink:
        ``True`` if this surface is part of the declared Android
        diagnostics/failure/artifact uplink path into the V2 chain.
    notes:
        Human-readable explanation of the surface's role, governance
        constraints, and any semantic boundary risks.
    """

    surface_id: str
    module_path: str
    surface_name: str
    semantic_kind: DiagnosticsSemanticKind
    may_not_redefine_authority_truth: bool = True
    android_diagnostics_uplink: bool = False
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "semantic_kind": self.semantic_kind.value,
            "may_not_redefine_authority_truth": self.may_not_redefine_authority_truth,
            "android_diagnostics_uplink": self.android_diagnostics_uplink,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Convergence snapshot data class
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticsFailureConvergenceSnapshot:
    """Aggregate convergence snapshot produced by
    :func:`build_diagnostics_failure_convergence_snapshot`.
    """

    authority: str = ""
    sentinel: str = ""
    policies: Tuple[str, ...] = field(default_factory=tuple)
    total_surfaces: int = 0
    authority_execution_truth_count: int = 0
    failure_diagnostics_count: int = 0
    artifact_evidence_count: int = 0
    operator_summary_count: int = 0
    audit_postrun_count: int = 0
    android_diagnostics_uplink_surfaces: List[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "authority": self.authority,
            "sentinel": self.sentinel,
            "policies": list(self.policies),
            "total_surfaces": self.total_surfaces,
            "authority_execution_truth_count": self.authority_execution_truth_count,
            "failure_diagnostics_count": self.failure_diagnostics_count,
            "artifact_evidence_count": self.artifact_evidence_count,
            "operator_summary_count": self.operator_summary_count,
            "audit_postrun_count": self.audit_postrun_count,
            "android_diagnostics_uplink_surfaces": (
                self.android_diagnostics_uplink_surfaces
            ),
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Diagnostics semantic surface registry
# ---------------------------------------------------------------------------

#: All surfaces classified within the diagnostics/failure/explanation boundary.
DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY: List[DiagnosticsSemanticSurface] = [

    # =========================================================================
    # AUTHORITY_EXECUTION_TRUTH — runtime authority sources for failure/success
    # =========================================================================

    DiagnosticsSemanticSurface(
        surface_id="desktop_presence_runtime_authority",
        module_path="core.desktop_presence_runtime.DesktopPresenceRuntime",
        surface_name=(
            "DesktopPresenceRuntime (canonical runtime shell authority — PR-4)"
        ),
        semantic_kind=DiagnosticsSemanticKind.authority_execution_truth,
        may_not_redefine_authority_truth=False,
        android_diagnostics_uplink=False,
        notes=(
            "Produces canonical execution state for the desktop runtime shell. "
            "Its failure/success state is authority execution truth. "
            "Downstream diagnostics, summaries, and audits consume this; "
            "they do not redefine it."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="task_graph_runtime_authority",
        module_path="core.task_graph_runtime.TaskGraphRuntime",
        surface_name=(
            "TaskGraphRuntime (task execution authority — core)"
        ),
        semantic_kind=DiagnosticsSemanticKind.authority_execution_truth,
        may_not_redefine_authority_truth=False,
        android_diagnostics_uplink=False,
        notes=(
            "Produces canonical task execution state including task failure "
            "and completion records.  The source of authority for 'did the "
            "task succeed or fail'.  Failure diagnostics records are derived "
            "from this, not vice versa."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="canonical_execution_chain_authority",
        module_path="core.canonical_execution_chain",
        surface_name=(
            "canonical_execution_chain (execution pipeline authority — core)"
        ),
        semantic_kind=DiagnosticsSemanticKind.authority_execution_truth,
        may_not_redefine_authority_truth=False,
        android_diagnostics_uplink=False,
        notes=(
            "Declares the canonical set of execution pipeline modules and their "
            "authority roles.  Failure states propagated through this chain are "
            "authority execution truth; downstream summaries read from here via "
            "the runtime truth output chain."
        ),
    ),

    # =========================================================================
    # FAILURE_DIAGNOSTICS_TRUTH — failure records, degraded-state, error logs
    # =========================================================================

    DiagnosticsSemanticSurface(
        surface_id="failure_degraded_recovery_policy",
        module_path="core.failure_degraded_recovery_policy",
        surface_name=(
            "failure_degraded_recovery_policy (failure/degraded/recovery "
            "policy layer — PR-13/Layer-13)"
        ),
        semantic_kind=DiagnosticsSemanticKind.failure_diagnostics_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Records failure, degraded, partial, fallback, retry, abort, and "
            "recovery states by propagating them into canonical runtime layers. "
            "Failure events recorded here are failure_diagnostics_truth. "
            "MUST NOT be read back as acceptance/closure gate inputs."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="failure_domains_classifier",
        module_path="core.failure_domains.FailureDomain",
        surface_name=(
            "FailureDomain / FailureClassification (structured failure "
            "classification — core.failure_domains)"
        ),
        semantic_kind=DiagnosticsSemanticKind.failure_diagnostics_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Classifies failures into structural domains (connectivity, timeout, "
            "auth, etc.).  Produces structured failure records for operator and "
            "CI visibility.  MUST NOT be reverse-read as acceptance gate inputs."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="error_framework_tracker",
        module_path="core.error_framework",
        surface_name=(
            "error_framework (global error tracking and categorisation — core)"
        ),
        semantic_kind=DiagnosticsSemanticKind.failure_diagnostics_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Global error tracker producing error summaries for the diagnostics "
            "route (/api/v1/errors/summary).  Error records are diagnostics truth; "
            "they describe what occurred but do not constitute authority runtime "
            "state or closure evidence."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="diagnostics_route_surface",
        module_path="core.routes.diagnostics",
        surface_name=(
            "core.routes.diagnostics (system diagnostics route surface — "
            "operational endpoints)"
        ),
        semantic_kind=DiagnosticsSemanticKind.failure_diagnostics_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Exposes operational diagnostics endpoints (/api/v1/errors/summary, "
            "/api/v1/concurrency/status, etc.).  These endpoints surface "
            "failure_diagnostics_truth for operator and monitoring use. "
            "They MUST NOT be consumed as acceptance/closure gate inputs."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="android_failure_signal_ingress",
        module_path="core.android_participant_truth_ingress",
        surface_name=(
            "android_participant_truth_ingress (Android failure signal ingress — "
            "canonical uplink path)"
        ),
        semantic_kind=DiagnosticsSemanticKind.failure_diagnostics_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=True,
        notes=(
            "Android-originated failure signals enter the V2 canonical chain via "
            "this ingress module.  Signals that do NOT reach "
            "build_v2_android_truth_block() remain failure_diagnostics_truth "
            "(advisory/local-only).  Only signals that reach the SSOT block "
            "become authority_execution_truth.  The two must not be conflated."
        ),
    ),

    # =========================================================================
    # ARTIFACT_EVIDENCE_TRUTH — evaluator artefacts, execution chain artefacts
    # =========================================================================

    DiagnosticsSemanticSurface(
        surface_id="android_evaluator_artifact_ingress",
        module_path="core.android_evaluator_artifact_ingress",
        surface_name=(
            "android_evaluator_artifact_ingress (Android evaluator artefact "
            "ingress and registry — PR-4V2-GOV)"
        ),
        semantic_kind=DiagnosticsSemanticKind.artifact_evidence_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=True,
        notes=(
            "Canonical ingress for Android readiness/acceptance/governance/"
            "strategy evaluator artefacts.  Artefacts stored in "
            "AndroidEvaluatorArtifactRegistry are ARTIFACT_EVIDENCE_TRUTH — "
            "they are gate inputs, not gate decisions.  The acceptance/closure "
            "gate that consumes them produces acceptance_closure_readiness_truth "
            "(PR-9V2 domain), not more artifact_evidence_truth."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="android_evaluator_artifact_registry",
        module_path=(
            "core.android_evaluator_artifact_ingress.AndroidEvaluatorArtifactRegistry"
        ),
        surface_name=(
            "AndroidEvaluatorArtifactRegistry (in-process artefact store — "
            "PR-4V2-GOV)"
        ),
        semantic_kind=DiagnosticsSemanticKind.artifact_evidence_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=True,
        notes=(
            "Ring-buffer singleton storing the most recent Android evaluator "
            "artefacts per device/kind.  Read-only for operator surfaces and "
            "readiness gates.  Storing an artefact here does not constitute "
            "closure or acceptance — it is evidence for gate evaluation."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="v2_readiness_governance_evidence_surface",
        module_path="core.v2_readiness_governance_evidence_surface",
        surface_name=(
            "v2_readiness_governance_evidence_surface (V2-side artefact evidence "
            "surface — readiness/governance gate input)"
        ),
        semantic_kind=DiagnosticsSemanticKind.artifact_evidence_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=True,
        notes=(
            "Assembles artefact evidence dimensions (including Android evaluator "
            "artefacts) for readiness and governance gate visibility.  This is an "
            "artifact evidence surface; it does not produce closure or acceptance "
            "truth."
        ),
    ),

    # =========================================================================
    # OPERATOR_SUMMARY_EXPLANATION — human-readable summaries, explanations
    # =========================================================================

    DiagnosticsSemanticSurface(
        surface_id="projection_route_explanation_fields",
        module_path="core.routes.projection",
        surface_name=(
            "core.routes.projection (projection route — operator-facing "
            "runtime-truth view and explanation fields)"
        ),
        semantic_kind=DiagnosticsSemanticKind.operator_summary_explanation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "The projection route assembles outward-facing runtime truth snapshots "
            "and operator explanations from Stage 2 (compile_outward_truth). "
            "Explanation / description fields in projection payloads are "
            "OPERATOR_SUMMARY_EXPLANATION — they describe state, they do not "
            "define it.  Projection routes MUST NOT reverse-inject explanation "
            "text into authority execution truth."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="routing_explanation_surface",
        module_path="core.routing_explanation",
        surface_name=(
            "routing_explanation (operator-facing routing decision explanation — "
            "read-only)"
        ),
        semantic_kind=DiagnosticsSemanticKind.operator_summary_explanation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Produces human-readable explanations of routing decisions for "
            "operator visibility.  Routing explanation is OPERATOR_SUMMARY_EXPLANATION "
            "— it narrates the routing decision, it does not constitute the "
            "routing authority decision itself."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="operator_surface",
        module_path="core.operator_surface",
        surface_name=(
            "operator_surface (operator-facing runtime surface — summary views)"
        ),
        semantic_kind=DiagnosticsSemanticKind.operator_summary_explanation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Assembles operator-facing views of runtime state including failure "
            "summaries and diagnostics snapshots.  Operator surface views are "
            "OPERATOR_SUMMARY_EXPLANATION; they consume authority execution truth "
            "and failure diagnostics truth but do not produce or redefine them."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="mesh_participation_summary",
        module_path="core.mesh_participation_summary",
        surface_name=(
            "mesh_participation_summary (mesh-level participation summary — "
            "operator read-only)"
        ),
        semantic_kind=DiagnosticsSemanticKind.operator_summary_explanation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Assembles mesh participation summaries for operator dashboards. "
            "This is a summary surface; failure or degraded participation is "
            "described here for human consumption, not defined here."
        ),
    ),

    # =========================================================================
    # AUDIT_POSTRUN_INTERPRETATION — post-hoc audit, forensic, post-run records
    # =========================================================================

    DiagnosticsSemanticSurface(
        surface_id="runtime_closure_audit",
        module_path="core.runtime_closure_audit",
        surface_name=(
            "runtime_closure_audit (post-hoc runtime closure audit record — "
            "forensic)"
        ),
        semantic_kind=DiagnosticsSemanticKind.audit_postrun_interpretation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Records runtime closure events and audit facts for post-hoc "
            "forensic analysis.  These records are AUDIT_POSTRUN_INTERPRETATION "
            "and MUST NOT be used as real-time authority or live closure inputs."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="android_delegated_runtime_audit",
        module_path="core.android_delegated_runtime_audit",
        surface_name=(
            "android_delegated_runtime_audit (Android-side delegated runtime "
            "audit — post-hoc forensic)"
        ),
        semantic_kind=DiagnosticsSemanticKind.audit_postrun_interpretation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=True,
        notes=(
            "Records Android delegated runtime audit events for post-hoc "
            "forensic analysis on the V2 side.  These are "
            "AUDIT_POSTRUN_INTERPRETATION records; they describe what the "
            "Android runtime decided, they do not constitute a V2-side "
            "authority decision."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="post_closure_dual_repo_reassessment",
        module_path="core.post_closure_dual_repo_reassessment",
        surface_name=(
            "post_closure_dual_repo_reassessment (post-closure dual-repo "
            "reassessment — retrospective)"
        ),
        semantic_kind=DiagnosticsSemanticKind.audit_postrun_interpretation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Produces post-closure reassessment of the dual-repo state for "
            "operator and audit visibility.  This is a retrospective "
            "AUDIT_POSTRUN_INTERPRETATION surface; it does not create new "
            "closure decisions."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="audit_event_semantics",
        module_path="core.audit_event_semantics",
        surface_name=(
            "audit_event_semantics (audit event classification and semantics — "
            "post-hoc)"
        ),
        semantic_kind=DiagnosticsSemanticKind.audit_postrun_interpretation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Classifies and records audit events for post-hoc analysis. "
            "Audit event classification is AUDIT_POSTRUN_INTERPRETATION; "
            "classifying an event does not constitute making a runtime decision."
        ),
    ),

    DiagnosticsSemanticSurface(
        surface_id="repo_goal_audit_route",
        module_path="core.routes.audit",
        surface_name=(
            "core.routes.audit (repo/goal audit route surface — "
            "post-run interpretation)"
        ),
        semantic_kind=DiagnosticsSemanticKind.audit_postrun_interpretation,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes=(
            "Exposes audit endpoints for repo-level and goal-level post-run "
            "interpretation.  Audit route payloads are "
            "AUDIT_POSTRUN_INTERPRETATION — they summarise what has been "
            "decided and recorded; they do not make live authority or "
            "acceptance decisions."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Registry accessor
# ---------------------------------------------------------------------------


def get_diagnostics_surface_registry() -> List[DiagnosticsSemanticSurface]:
    """Return the full diagnostics/failure/explanation surface registry.

    Returns
    -------
    List[DiagnosticsSemanticSurface]
        All surfaces classified within the PR-10V2 boundary.
    """
    return list(DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY)


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


def classify_diagnostics_semantic_kind(surface_id: str) -> str:
    """Return the :class:`DiagnosticsSemanticKind` value for *surface_id*.

    Parameters
    ----------
    surface_id:
        The ``surface_id`` of a registered surface.

    Returns
    -------
    str
        The ``DiagnosticsSemanticKind.value`` for the surface, or
        ``"unknown"`` if *surface_id* is not in the registry.
    """
    for surface in DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY:
        if surface.surface_id == surface_id:
            return surface.semantic_kind.value
    return "unknown"


# ---------------------------------------------------------------------------
# Domain filter helper
# ---------------------------------------------------------------------------


def get_surfaces_by_semantic_kind(
    kind: DiagnosticsSemanticKind,
) -> List[DiagnosticsSemanticSurface]:
    """Return all registry surfaces with the given *kind*.

    Parameters
    ----------
    kind:
        :class:`DiagnosticsSemanticKind` to filter by.

    Returns
    -------
    List[DiagnosticsSemanticSurface]
        Surfaces whose ``semantic_kind`` equals *kind*.
    """
    return [s for s in DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY if s.semantic_kind == kind]


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_diagnostics_failure_convergence_snapshot() -> (
    DiagnosticsFailureConvergenceSnapshot
):
    """Build an aggregate convergence snapshot for operator / CI visibility.

    Returns
    -------
    DiagnosticsFailureConvergenceSnapshot
        Counts and metadata for all classified surfaces.
    """
    registry = DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY
    android_uplink = [
        s.surface_id for s in registry if s.android_diagnostics_uplink
    ]
    return DiagnosticsFailureConvergenceSnapshot(
        authority=DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY,
        sentinel=DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL,
        policies=(
            SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY,
            DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY,
            ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY,
            AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY,
            NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY,
        ),
        total_surfaces=len(registry),
        authority_execution_truth_count=sum(
            1 for s in registry
            if s.semantic_kind == DiagnosticsSemanticKind.authority_execution_truth
        ),
        failure_diagnostics_count=sum(
            1 for s in registry
            if s.semantic_kind == DiagnosticsSemanticKind.failure_diagnostics_truth
        ),
        artifact_evidence_count=sum(
            1 for s in registry
            if s.semantic_kind == DiagnosticsSemanticKind.artifact_evidence_truth
        ),
        operator_summary_count=sum(
            1 for s in registry
            if s.semantic_kind == DiagnosticsSemanticKind.operator_summary_explanation
        ),
        audit_postrun_count=sum(
            1 for s in registry
            if s.semantic_kind == DiagnosticsSemanticKind.audit_postrun_interpretation
        ),
        android_diagnostics_uplink_surfaces=android_uplink,
        generated_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Android diagnostics uplink path declaration
# ---------------------------------------------------------------------------


def get_android_diagnostics_uplink_path() -> Tuple[str, ...]:
    """Return the declared canonical Android diagnostics/failure/artifact
    uplink path into the V2 truth chain.

    Returns
    -------
    Tuple[str, ...]
        Ordered sequence of module/class steps from Android ingress to
        V2 canonical truth.
    """
    return (
        "galaxy_gateway.android.handlers (ingress gateway)",
        "core.android_evaluator_artifact_ingress (artifact ingress → "
        "AndroidEvaluatorArtifactRegistry)",
        "core.android_participant_truth_ingress (failure signal ingress)",
        "core.v2_android_truth_ssot.build_v2_android_truth_block (SSOT build)",
        "core.canonical_session_truth (merge + record)",
        "Stage 1: core.projection.runtime_truth_compiler.compile_runtime_truth()",
        "Stage 2: core.outward_runtime_truth.compile_outward_truth()",
        "Stage 3: core.routes.projection (projection surfaces)",
    )
