"""core/android_evidence_integration_pipeline.py
=================================================
PR-8 V2-side — Final Android Evidence Integration Pipeline
===========================================================

Background
----------
The V2 center-governance layer has been progressively hardened across
prior PRs:

- PR-5   Android execution lifecycle truth quality classification
         (core.unified_execution_governance: get_execution_lifecycle_truth_binding,
          AndroidExecutionLifecycleTruthQuality)

- PR-6A  Real Android execution governance regression path
         (tests/integration/test_pr6a_real_android_execution_governance_regression.py)

- PR-7A  Capability truth absent degrades readiness to deny
         (core.android_mode_gate_policy: ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY,
          resolve_android_execution_gate_decision)

- PR-13  Closed-loop governance consolidation
         (core.closed_loop_governance_consolidation: query_closed_loop_governance_state,
          assert_closed_loop_invariants)

- PR-14  Execution governance audit authority
         (core.execution_governance_audit_authority: build_governance_authority_evidence,
          verify_governance_authority_integrity)

Despite these advances, each governance dimension still lives in its own
surface.  There was no single, canonical pipeline object that:

1. Evaluates **all four evidence dimensions** in one call.
2. Produces a unified canonical verdict that gates V2 execution.
3. Explicitly bounds every remaining optimistic fallback path so that
   absent, simulated, loosely structured, or stale Android evidence is
   **never** silently treated as sufficient.
4. Provides rich diagnostics when evidence is degraded so that
   observability tooling can attribute the exact dimension and cause.

Purpose
-------
This module closes that gap.  It is the **final integration layer**
that ties the previously introduced evidence surfaces into a single
end-to-end execution gate:

    Capability truth quality  (classify_canonical_proof_input_diagnosis)
    ↓
    Lifecycle truth quality   (get_execution_lifecycle_truth_binding)
    ↓
    Audit authority chain     (verify_governance_authority_integrity)
    ↓
    Closed-loop invariants    (assert_closed_loop_invariants)
    ↓
    AndroidEvidenceIntegrationVerdict  ← single gate output

All four dimensions are evaluated.  If **any** dimension is degraded,
``integration_allowed`` is ``False`` and ``degradation_causes`` names
every contributing factor.  Optimistic fallback paths are explicitly
bounded: an absent, stale, or simulated Android truth **never** produces
a passing verdict through this pipeline.

Design principles
-----------------
1. **Additive only** — does not modify any existing module; reads from
   the four existing governance surfaces via their public APIs.
2. **Never raises** — all public functions are documented to never raise;
   errors are captured as ``evidence_grade=absent`` with diagnostics.
3. **JSON-serialisable** — all dataclasses expose ``to_dict()``.
4. **Optimistic path elimination** — the OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY
   sentinel documents every remaining fallback path and its explicit bound.

Authority sentinel
------------------
``ANDROID_EVIDENCE_INTEGRATION_SENTINEL`` — import this constant to assert
that the PR-8 final integration pipeline is present.

Public API
----------
Sentinels / version::

    ANDROID_EVIDENCE_INTEGRATION_SENTINEL
    ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION
    END_TO_END_ANDROID_EVIDENCE_GATE_POLICY
    OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY

Enums::

    AndroidEvidenceDimension
    AndroidEvidenceGrade
    IntegrationDecision

Dataclasses::

    AndroidEvidenceDimensionResult
    AndroidEvidenceIntegrationVerdict

Functions::

    evaluate_android_evidence_integration(device_id, execution_id, ...)
    get_android_evidence_integration_summary(device_id, execution_id, ...)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidEvidenceIntegrationPipeline")

# ---------------------------------------------------------------------------
# Lazy module-level imports — kept at module scope for patchability
# ---------------------------------------------------------------------------
# Each dependency is imported unconditionally at module load with a fallback
# stub so that the module is always importable even when a sub-module is
# unavailable.  Tests may patch these names directly on this module.

try:
    from core.unified_execution_governance import (  # noqa: E402
        classify_canonical_proof_input_diagnosis,
        get_execution_lifecycle_truth_binding,
    )
except Exception:  # pragma: no cover
    def classify_canonical_proof_input_diagnosis(snapshot):  # type: ignore[misc]
        return {
            "proof_input_class": "missing",
            "proof_input_degradation_causes": ["module_unavailable"],
            "proof_input_conflicts": [],
        }

    def get_execution_lifecycle_truth_binding(device_id):  # type: ignore[misc]
        return None  # type: ignore[return-value]

try:
    from core.execution_governance_audit_authority import (  # noqa: E402
        build_governance_authority_evidence,
        verify_governance_authority_integrity,
    )
except Exception:  # pragma: no cover
    def build_governance_authority_evidence(execution_id, device_id):  # type: ignore[misc]
        return None  # type: ignore[return-value]

    def verify_governance_authority_integrity(execution_id, device_id):  # type: ignore[misc]
        return []

try:
    from core.closed_loop_governance_consolidation import (  # noqa: E402
        assert_closed_loop_invariants,
        query_closed_loop_governance_state,
    )
except Exception:  # pragma: no cover
    def query_closed_loop_governance_state(execution_id, device_id):  # type: ignore[misc]
        return None  # type: ignore[return-value]

    def assert_closed_loop_invariants(execution_id, device_id):  # type: ignore[misc]
        return []

# ---------------------------------------------------------------------------
# Authority sentinels & contract version
# ---------------------------------------------------------------------------

ANDROID_EVIDENCE_INTEGRATION_SENTINEL: str = (
    "ANDROID_EVIDENCE_INTEGRATION_SENTINEL::PR8_V2::present "
    "core.android_evidence_integration_pipeline is the canonical center-side "
    "final integration layer that unifies Android capability truth quality, "
    "execution lifecycle truth quality, governance audit authority chain "
    "integrity, and closed-loop governance invariant compliance into a single "
    "end-to-end execution gate verdict. All V2 canonical execution admissions "
    "and readiness verdicts MUST be gated by this pipeline when Android evidence "
    "quality is a governance input. Absent, simulated, stale, loosely structured, "
    "or optimistic Android evidence is NEVER sufficient for a passing integration "
    "verdict. See OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY."
)

ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION: str = "8.0.0"

END_TO_END_ANDROID_EVIDENCE_GATE_POLICY: str = (
    "POLICY::END_TO_END_ANDROID_EVIDENCE_GATE_V1: "
    "V2 canonical execution readiness and governance decisions MUST be gated by "
    "real or contract-valid Android evidence across four dimensions: "
    "(1) CAPABILITY TRUTH — Android capability truth quality classified from "
    "    classify_canonical_proof_input_diagnosis() must be 'complete'; "
    "(2) LIFECYCLE TRUTH — Android execution lifecycle truth quality from "
    "    get_execution_lifecycle_truth_binding() must not be "
    "    'missing_remote', 'stale_remote', or 'conflicting_remote' when V2 "
    "    is tracking active executions; "
    "(3) AUDIT AUTHORITY — verify_governance_authority_integrity() must return "
    "    zero integrity violations for the governed execution; "
    "(4) CLOSED-LOOP INVARIANTS — assert_closed_loop_invariants() must return "
    "    zero cross-stage invariant violations. "
    "A passing integration verdict requires ALL four dimensions to be non-degraded. "
    "Degraded Android truth causes diagnosable degradation in the integration "
    "verdict; the exact dimension and reason are recorded in degradation_causes."
)

OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY: str = (
    "POLICY::OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_V1: "
    "The following optimistic fallback paths are explicitly bounded: "
    "(A) CAPABILITY_TRUTH_ABSENT_FALLBACK — When no Android capability snapshot "
    "    is present, proof_input_class='missing' forces the capability truth "
    "    dimension to DEGRADED. V2 MUST NOT infer capability readiness from "
    "    device registration alone. Bound: ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_"
    "    READINESS_POLICY in core.android_mode_gate_policy; "
    "(B) LIFECYCLE_TRUTH_V2_LOCAL_ONLY_FALLBACK — When V2 tracks active executions "
    "    but has received no Android lifecycle events, truth quality is "
    "    'missing_remote'. This dimension is degraded: V2-local bookkeeping alone "
    "    is NOT treated as execution truth. Bound: ANDROID_EXECUTION_LIFECYCLE_TRUTH_"
    "    POLICY in core.unified_execution_governance; "
    "(C) AUDIT_CHAIN_ABSENT_FALLBACK — When no lifecycle history or uplink records "
    "    exist for an execution, the audit chain has zero stages reached. The audit "
    "    authority dimension is degraded. V2 MUST NOT allow execution to proceed "
    "    without an auditable admission evidence record. Bound: "
    "    GOVERNANCE_AUDIT_AUTHORITY_POLICY in core.execution_governance_audit_authority; "
    "(D) CLOSED_LOOP_UNKNOWN_FALLBACK — When the closed-loop stage is 'unknown' "
    "    and cross-stage invariants cannot be confirmed, the closed-loop dimension "
    "    is degraded. V2 MUST NOT treat unknown governance stage as idle/clean. "
    "    Bound: CROSS_STAGE_INVARIANT_POLICY in core.closed_loop_governance_consolidation."
)


# ---------------------------------------------------------------------------
# AndroidEvidenceDimension
# ---------------------------------------------------------------------------


class AndroidEvidenceDimension(str, Enum):
    """The four evidence dimensions evaluated by the integration pipeline.

    Values
    ------
    capability_truth
        Android-reported capability snapshot quality (from
        ``classify_canonical_proof_input_diagnosis``).

    lifecycle_truth
        Android execution lifecycle truth quality relative to V2-local
        tracking (from ``get_execution_lifecycle_truth_binding``).

    audit_authority
        Governance audit authority chain integrity (from
        ``verify_governance_authority_integrity``).

    closed_loop
        Closed-loop cross-stage invariant compliance (from
        ``assert_closed_loop_invariants``).
    """

    capability_truth = "capability_truth"
    lifecycle_truth = "lifecycle_truth"
    audit_authority = "audit_authority"
    closed_loop = "closed_loop"


# ---------------------------------------------------------------------------
# AndroidEvidenceGrade
# ---------------------------------------------------------------------------


class AndroidEvidenceGrade(str, Enum):
    """Overall grade for a single evidence dimension or the unified verdict.

    Values
    ------
    strong
        Android evidence is complete, fresh, and confirmed (e.g.,
        proof_input_class='complete', lifecycle='android_remote_confirmed',
        zero audit violations, zero closed-loop violations).

    adequate
        Evidence is present and meets the minimum threshold but is not
        fully confirmed (e.g., partial proof inputs, v2_local_only lifecycle
        when no active executions exist, audit chain with admission only).

    degraded
        Evidence exists but is stale, conflicting, or carries violations
        that prevent a passing integration verdict.  ``integration_allowed``
        will be ``False`` for any dimension with this grade.

    absent
        No Android evidence is available for this dimension (e.g., no
        capability snapshot, no lifecycle events, no governance artifacts).
        Like ``degraded``, this prevents a passing integration verdict.
    """

    strong = "strong"
    adequate = "adequate"
    degraded = "degraded"
    absent = "absent"


# ---------------------------------------------------------------------------
# IntegrationDecision
# ---------------------------------------------------------------------------


class IntegrationDecision(str, Enum):
    """Unified integration decision for the Android evidence pipeline.

    Values
    ------
    allow
        All four evidence dimensions meet the minimum threshold.  V2 may
        proceed with canonical execution admission.

    deny
        One or more dimensions are degraded or absent.  V2 MUST NOT
        admit execution until Android evidence quality improves.  The
        ``degradation_causes`` list identifies the failing dimensions.

    conditionally_allow
        All dimensions are adequate (no degraded/absent), but at least
        one dimension fell short of ``strong``.  V2 may proceed but SHOULD
        surface the evidence grade in diagnostics.
    """

    allow = "allow"
    deny = "deny"
    conditionally_allow = "conditionally_allow"


# ---------------------------------------------------------------------------
# AndroidEvidenceDimensionResult
# ---------------------------------------------------------------------------


@dataclass
class AndroidEvidenceDimensionResult:
    """Result for a single evidence dimension evaluation.

    Attributes
    ----------
    dimension
        Which evidence dimension this result covers.
    grade
        Evaluated quality grade for this dimension.
    passed
        Whether this dimension is non-degraded (i.e., ``grade`` is
        ``strong`` or ``adequate``).
    reason
        Human-readable reason for the grade.
    detail
        Structured evidence detail (JSON-serialisable).
    evaluated_at
        Unix epoch when this dimension was evaluated.
    """

    dimension: AndroidEvidenceDimension
    grade: AndroidEvidenceGrade
    passed: bool
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "grade": self.grade.value,
            "passed": self.passed,
            "reason": self.reason,
            "detail": self.detail,
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# AndroidEvidenceIntegrationVerdict
# ---------------------------------------------------------------------------


@dataclass
class AndroidEvidenceIntegrationVerdict:
    """Unified end-to-end Android evidence integration verdict.

    This is the canonical output of
    :func:`evaluate_android_evidence_integration`.  All four evidence
    dimensions are evaluated and their results are combined into a single
    ``integration_decision`` and ``overall_grade``.

    Attributes
    ----------
    device_id
        Android device under evaluation.
    execution_id
        Execution identifier (may be ``""`` when evaluating pre-admission).
    integration_decision
        The unified decision: allow / deny / conditionally_allow.
    integration_allowed
        Convenience boolean: ``True`` only when decision is ``allow`` or
        ``conditionally_allow``.
    overall_grade
        Worst dimension grade across all four dimensions.
    dimension_results
        Per-dimension results (always four entries).
    degradation_causes
        List of structured cause strings for failing dimensions.  Empty
        when ``integration_allowed`` is ``True``.
    evaluated_at
        Unix epoch when the verdict was produced.
    """

    device_id: str
    execution_id: str
    integration_decision: IntegrationDecision
    integration_allowed: bool
    overall_grade: AndroidEvidenceGrade
    dimension_results: List[AndroidEvidenceDimensionResult] = field(default_factory=list)
    degradation_causes: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "execution_id": self.execution_id,
            "integration_decision": self.integration_decision.value,
            "integration_allowed": self.integration_allowed,
            "overall_grade": self.overall_grade.value,
            "dimension_results": [r.to_dict() for r in self.dimension_results],
            "degradation_causes": list(self.degradation_causes),
            "evaluated_at": self.evaluated_at,
            "_sentinel": ANDROID_EVIDENCE_INTEGRATION_SENTINEL,
            "_contract_version": ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION,
            "_policy": END_TO_END_ANDROID_EVIDENCE_GATE_POLICY,
        }


# ---------------------------------------------------------------------------
# Internal helpers — one per evidence dimension
# ---------------------------------------------------------------------------

# Capability truth quality values that are explicitly non-passing.
# Only proof_input_class="complete" is treated as positive capability evidence.
_NON_PASSING_CAPABILITY_TRUTH_CLASSES: frozenset = frozenset(
    {"missing", "stale", "conflicting", "downgraded", "partial", "unknown", "malformed"}
)

# Lifecycle truth quality values that degrade the gate when V2 has active
# executions.
_DEGRADING_LIFECYCLE_TRUTH_QUALITIES: frozenset = frozenset(
    {"missing_remote", "stale_remote", "conflicting_remote"}
)


def _evaluate_capability_truth_dimension(
    device_id: str,
    runtime_state: Optional[Dict[str, Any]],
) -> AndroidEvidenceDimensionResult:
    """Evaluate the capability truth dimension for *device_id*.

    Reads Android capability snapshot quality from
    ``classify_canonical_proof_input_diagnosis``. Only ``proof_input_class=
    "complete"`` passes this dimension. All other classes are explicitly
    non-passing so Android-backed evidence remains the canonical source of
    truth for execution readiness.
    """
    try:
        snapshot = runtime_state or {}
        diagnosis = classify_canonical_proof_input_diagnosis(snapshot)
        proof_class = str(diagnosis.get("proof_input_class") or "missing").strip().lower()
        degradation_causes = list(diagnosis.get("proof_input_degradation_causes") or [])
        conflicts = list(diagnosis.get("proof_input_conflicts") or [])

        if proof_class != "complete":
            if proof_class not in _NON_PASSING_CAPABILITY_TRUTH_CLASSES:
                # Defensive forward-compatibility: unknown/new proof classes
                # must fail the gate and remain explicitly diagnosable.
                degradation_causes.append(
                    f"unrecognized_proof_input_class:{proof_class or 'missing'}"
                )
            return AndroidEvidenceDimensionResult(
                dimension=AndroidEvidenceDimension.capability_truth,
                grade=AndroidEvidenceGrade.degraded if proof_class != "missing" else AndroidEvidenceGrade.absent,
                passed=False,
                reason=(
                    f"capability_truth_class={proof_class!r} is non-passing; "
                    f"optimistic_fallback_eliminated_by:"
                    f"ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY"
                ),
                detail={
                    "proof_input_class": proof_class,
                    "degradation_causes": degradation_causes,
                    "conflicts": conflicts,
                    "bound_policy": "ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY",
                },
            )

        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.capability_truth,
            grade=AndroidEvidenceGrade.strong,
            passed=True,
            reason=f"capability_truth_class={proof_class!r} is non-degrading",
            detail={
                "proof_input_class": proof_class,
                "degradation_causes": degradation_causes,
                "conflicts": conflicts,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_evaluate_capability_truth_dimension: error for %r: %s",
            device_id,
            exc,
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.capability_truth,
            grade=AndroidEvidenceGrade.absent,
            passed=False,
            reason=f"capability_truth_evaluation_error:{type(exc).__name__}",
            detail={"error": str(exc)},
        )


def _evaluate_lifecycle_truth_dimension(
    device_id: str,
) -> AndroidEvidenceDimensionResult:
    """Evaluate the execution lifecycle truth dimension for *device_id*.

    Reads Android execution lifecycle truth quality from
    ``get_execution_lifecycle_truth_binding``.  Degraded qualities
    (missing_remote, stale_remote, conflicting_remote) → DEGRADED.
    v2_local_only with no active executions → ADEQUATE (clean idle).
    """
    try:
        binding = get_execution_lifecycle_truth_binding(device_id)
        quality_value = str(
            getattr(binding.android_lifecycle_truth_quality, "value", "v2_local_only")
        )
        degraded = bool(getattr(binding, "android_lifecycle_truth_degraded", False))
        reason_str = str(getattr(binding, "android_lifecycle_truth_reason", "unknown"))
        active_count = int(getattr(binding, "active_execution_count", 0))
        governance_impact = str(
            getattr(binding, "android_lifecycle_truth_governance_impact", "none")
        )

        if quality_value in _DEGRADING_LIFECYCLE_TRUTH_QUALITIES and degraded:
            return AndroidEvidenceDimensionResult(
                dimension=AndroidEvidenceDimension.lifecycle_truth,
                grade=AndroidEvidenceGrade.degraded,
                passed=False,
                reason=(
                    f"lifecycle_truth_quality={quality_value!r} is degraded; "
                    f"reason={reason_str!r}; "
                    f"optimistic_fallback_eliminated_by:"
                    f"ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY"
                ),
                detail={
                    "lifecycle_truth_quality": quality_value,
                    "lifecycle_truth_degraded": degraded,
                    "active_execution_count": active_count,
                    "governance_impact": governance_impact,
                    "reason": reason_str,
                    "bound_policy": "ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY",
                },
            )

        grade = (
            AndroidEvidenceGrade.strong
            if quality_value == "android_remote_confirmed"
            else AndroidEvidenceGrade.adequate
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.lifecycle_truth,
            grade=grade,
            passed=True,
            reason=f"lifecycle_truth_quality={quality_value!r} is non-degrading",
            detail={
                "lifecycle_truth_quality": quality_value,
                "lifecycle_truth_degraded": degraded,
                "active_execution_count": active_count,
                "governance_impact": governance_impact,
                "reason": reason_str,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_evaluate_lifecycle_truth_dimension: error for %r: %s",
            device_id,
            exc,
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.lifecycle_truth,
            grade=AndroidEvidenceGrade.absent,
            passed=False,
            reason=f"lifecycle_truth_evaluation_error:{type(exc).__name__}",
            detail={"error": str(exc)},
        )


def _evaluate_audit_authority_dimension(
    execution_id: str,
    device_id: str,
) -> AndroidEvidenceDimensionResult:
    """Evaluate the governance audit authority chain for *execution_id*/*device_id*.

    Calls ``verify_governance_authority_integrity``.  Any violations →
    DEGRADED.  Empty execution_id or no artifacts → ABSENT (not silently
    passing).
    """
    if not execution_id:
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.audit_authority,
            grade=AndroidEvidenceGrade.absent,
            passed=False,
            reason=(
                "audit_authority_absent: no execution_id provided; "
                "absent audit chain is NOT treated as clean; "
                "optimistic_fallback_eliminated_by:GOVERNANCE_AUDIT_AUTHORITY_POLICY"
            ),
            detail={
                "execution_id": execution_id,
                "bound_policy": "GOVERNANCE_AUDIT_AUTHORITY_POLICY",
            },
        )

    try:
        evidence = build_governance_authority_evidence(execution_id, device_id)
        violations = verify_governance_authority_integrity(execution_id, device_id)

        stages_reached = [
            e.stage.value
            for e in (getattr(evidence, "audit_entries", []) or [])
            if getattr(e, "reached", False)
        ]
        violation_dicts = [
            v.to_dict() for v in (violations or [])
        ]

        if violations:
            return AndroidEvidenceDimensionResult(
                dimension=AndroidEvidenceDimension.audit_authority,
                grade=AndroidEvidenceGrade.degraded,
                passed=False,
                reason=(
                    f"audit_authority_violations={len(violations)}: "
                    + "; ".join(
                        f"{v.invariant_id}:{v.description[:60]}" for v in violations
                    )
                ),
                detail={
                    "violations": violation_dicts,
                    "stages_reached": stages_reached,
                    "bound_policy": "GOVERNANCE_AUDIT_AUTHORITY_POLICY",
                },
            )

        if not stages_reached:
            return AndroidEvidenceDimensionResult(
                dimension=AndroidEvidenceDimension.audit_authority,
                grade=AndroidEvidenceGrade.absent,
                passed=False,
                reason=(
                    "audit_authority_absent: no audit stages reached for execution; "
                    "optimistic_fallback_eliminated_by:GOVERNANCE_AUDIT_AUTHORITY_POLICY"
                ),
                detail={
                    "stages_reached": stages_reached,
                    "bound_policy": "GOVERNANCE_AUDIT_AUTHORITY_POLICY",
                },
            )

        grade = (
            AndroidEvidenceGrade.strong
            if "terminal" in stages_reached
            else AndroidEvidenceGrade.adequate
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.audit_authority,
            grade=grade,
            passed=True,
            reason=(
                f"audit_authority_chain_intact: "
                f"stages_reached={stages_reached!r}; zero violations"
            ),
            detail={
                "stages_reached": stages_reached,
                "violations": [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_evaluate_audit_authority_dimension: error for exec=%r device=%r: %s",
            execution_id,
            device_id,
            exc,
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.audit_authority,
            grade=AndroidEvidenceGrade.absent,
            passed=False,
            reason=f"audit_authority_evaluation_error:{type(exc).__name__}",
            detail={"error": str(exc)},
        )


def _evaluate_closed_loop_dimension(
    execution_id: str,
    device_id: str,
) -> AndroidEvidenceDimensionResult:
    """Evaluate closed-loop cross-stage invariant compliance.

    Calls ``assert_closed_loop_invariants``.  Any violations → DEGRADED.
    Unknown governance stage → ABSENT (not silently passing; the
    CLOSED_LOOP_UNKNOWN_FALLBACK path is explicitly bounded).
    """
    if not execution_id:
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.closed_loop,
            grade=AndroidEvidenceGrade.absent,
            passed=False,
            reason=(
                "closed_loop_absent: no execution_id provided; "
                "unknown stage is NOT treated as clean; "
                "optimistic_fallback_eliminated_by:CROSS_STAGE_INVARIANT_POLICY"
            ),
            detail={
                "execution_id": execution_id,
                "bound_policy": "CROSS_STAGE_INVARIANT_POLICY",
            },
        )

    try:
        view = query_closed_loop_governance_state(execution_id, device_id)
        violations = assert_closed_loop_invariants(execution_id, device_id)
        stage_value = str(getattr(getattr(view, "stage", None), "value", "unknown"))
        violation_dicts = [v.to_dict() for v in (violations or [])]

        if violations:
            return AndroidEvidenceDimensionResult(
                dimension=AndroidEvidenceDimension.closed_loop,
                grade=AndroidEvidenceGrade.degraded,
                passed=False,
                reason=(
                    f"closed_loop_invariant_violations={len(violations)}: "
                    + "; ".join(
                        f"{v.invariant_id}:{v.description[:60]}" for v in violations
                    )
                ),
                detail={
                    "stage": stage_value,
                    "violations": violation_dicts,
                    "bound_policy": "CROSS_STAGE_INVARIANT_POLICY",
                },
            )

        if stage_value == "unknown":
            return AndroidEvidenceDimensionResult(
                dimension=AndroidEvidenceDimension.closed_loop,
                grade=AndroidEvidenceGrade.absent,
                passed=False,
                reason=(
                    "closed_loop_stage=unknown; "
                    "absent/unknown governance stage is NOT treated as idle/clean; "
                    "optimistic_fallback_eliminated_by:CROSS_STAGE_INVARIANT_POLICY"
                ),
                detail={
                    "stage": stage_value,
                    "bound_policy": "CROSS_STAGE_INVARIANT_POLICY",
                },
            )

        grade = (
            AndroidEvidenceGrade.strong
            if stage_value == "completion"
            else AndroidEvidenceGrade.adequate
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.closed_loop,
            grade=grade,
            passed=True,
            reason=(
                f"closed_loop_stage={stage_value!r}; zero invariant violations"
            ),
            detail={
                "stage": stage_value,
                "violations": [],
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_evaluate_closed_loop_dimension: error for exec=%r device=%r: %s",
            execution_id,
            device_id,
            exc,
        )
        return AndroidEvidenceDimensionResult(
            dimension=AndroidEvidenceDimension.closed_loop,
            grade=AndroidEvidenceGrade.absent,
            passed=False,
            reason=f"closed_loop_evaluation_error:{type(exc).__name__}",
            detail={"error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Grade aggregation
# ---------------------------------------------------------------------------

# Grade ordinal (higher = worse)
_GRADE_ORDINAL: Dict[AndroidEvidenceGrade, int] = {
    AndroidEvidenceGrade.strong: 0,
    AndroidEvidenceGrade.adequate: 1,
    AndroidEvidenceGrade.degraded: 2,
    AndroidEvidenceGrade.absent: 3,
}


def _worst_grade(grades: List[AndroidEvidenceGrade]) -> AndroidEvidenceGrade:
    """Return the worst (highest ordinal) grade from *grades*."""
    if not grades:
        return AndroidEvidenceGrade.absent
    return max(grades, key=lambda g: _GRADE_ORDINAL.get(g, 99))


def _derive_decision(
    overall_grade: AndroidEvidenceGrade,
    all_passed: bool,
) -> IntegrationDecision:
    """Derive the integration decision from *overall_grade* and *all_passed*."""
    if not all_passed:
        return IntegrationDecision.deny
    if overall_grade == AndroidEvidenceGrade.strong:
        return IntegrationDecision.allow
    return IntegrationDecision.conditionally_allow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_android_evidence_integration(
    device_id: str,
    execution_id: str = "",
    *,
    runtime_state: Optional[Dict[str, Any]] = None,
) -> AndroidEvidenceIntegrationVerdict:
    """Evaluate the full Android evidence integration pipeline for *device_id*.

    This is the canonical PR-8 entry point.  It evaluates all four evidence
    dimensions and returns a unified :class:`AndroidEvidenceIntegrationVerdict`.

    Parameters
    ----------
    device_id:
        The Android device identifier to evaluate.
    execution_id:
        Optional execution identifier.  When provided, the audit authority
        and closed-loop dimensions are evaluated against this specific
        execution.  When absent, those dimensions will return grade=absent.
    runtime_state:
        Optional pre-computed runtime state dict (e.g., from
        ``_get_android_runtime_pressure_snapshot``).  When absent, the
        capability truth dimension will use an empty snapshot (which
        produces proof_input_class='missing').

    Returns
    -------
    AndroidEvidenceIntegrationVerdict
        Always returned; never raises.
    """
    eval_time = time.time()
    try:
        dim_capability = _evaluate_capability_truth_dimension(device_id, runtime_state)
        dim_lifecycle = _evaluate_lifecycle_truth_dimension(device_id)
        dim_audit = _evaluate_audit_authority_dimension(execution_id, device_id)
        dim_closed_loop = _evaluate_closed_loop_dimension(execution_id, device_id)

        dimension_results = [
            dim_capability,
            dim_lifecycle,
            dim_audit,
            dim_closed_loop,
        ]

        all_passed = all(r.passed for r in dimension_results)
        overall_grade = _worst_grade([r.grade for r in dimension_results])
        decision = _derive_decision(overall_grade, all_passed)
        integration_allowed = decision != IntegrationDecision.deny

        degradation_causes: List[str] = []
        for r in dimension_results:
            if not r.passed:
                degradation_causes.append(
                    f"{r.dimension.value}:{r.grade.value}:{r.reason[:120]}"
                )

        return AndroidEvidenceIntegrationVerdict(
            device_id=device_id,
            execution_id=execution_id,
            integration_decision=decision,
            integration_allowed=integration_allowed,
            overall_grade=overall_grade,
            dimension_results=dimension_results,
            degradation_causes=degradation_causes,
            evaluated_at=eval_time,
        )
    except Exception as exc:  # noqa: BLE001
        # Broad catch is intentional: this function is documented to never raise.
        # All errors produce a conservative deny verdict.
        logger.warning(
            "evaluate_android_evidence_integration: unexpected error "
            "for device=%r exec=%r: %s",
            device_id,
            execution_id,
            exc,
        )
        return AndroidEvidenceIntegrationVerdict(
            device_id=device_id,
            execution_id=execution_id,
            integration_decision=IntegrationDecision.deny,
            integration_allowed=False,
            overall_grade=AndroidEvidenceGrade.absent,
            dimension_results=[],
            degradation_causes=[f"integration_pipeline_error:{type(exc).__name__}:{exc}"],
            evaluated_at=eval_time,
        )


def get_android_evidence_integration_summary(
    device_id: str,
    execution_id: str = "",
    *,
    runtime_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a JSON-serialisable summary of the Android evidence integration verdict.

    Wraps :func:`evaluate_android_evidence_integration` and serialises the
    result via :meth:`AndroidEvidenceIntegrationVerdict.to_dict`.

    Never raises.
    """
    try:
        verdict = evaluate_android_evidence_integration(
            device_id,
            execution_id,
            runtime_state=runtime_state,
        )
        return verdict.to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "get_android_evidence_integration_summary: error for device=%r: %s",
            device_id,
            exc,
        )
        return {
            "device_id": device_id,
            "execution_id": execution_id,
            "integration_decision": IntegrationDecision.deny.value,
            "integration_allowed": False,
            "overall_grade": AndroidEvidenceGrade.absent.value,
            "dimension_results": [],
            "degradation_causes": [f"summary_error:{type(exc).__name__}"],
            "evaluated_at": time.time(),
            "_sentinel": ANDROID_EVIDENCE_INTEGRATION_SENTINEL,
            "_contract_version": ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION,
        }
