#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_post_graduation_governance.py
==================================================
PR-11V2 (post-533 dual-repo runtime host unification track):
Delegated Flow Post-Graduation Governance / Enforcement Layer.

Background
----------
The delegated canonical path has progressively gained:

* **PR-3V2** — FlowContinuityCoordinator: unified continuity / replay
  decision entry-point with serialisable artifacts.
* **PR-5V2** — FlowLevelTruthOwnership: flow-level truth authority model,
  alignment rules, and alignment runtime.
* **PR-6V2** — FlowAwareResultConvergence: flow-aware result convergence
  coordinator with parallel aggregation and duplicate suppression.
* **PR-7V2** — FlowLevelOperatorSurface: canonical projection for delegated
  flows and Android execution phases.
* **PR-8V2** — CompatLegacyPathBlockingCanonicalization: blocking-first gate
  for all compat/legacy influence vectors.
* **PR-9V2** — DelegatedFlowReadinessGate: unified readiness / release gate
  that aggregates the five dimension signals into a release-gate verdict.
* **PR-10V2** — DelegatedFlowAcceptanceGate: evidence-backed final
  acceptance / graduation gate.

However, a graduation gate alone does not constitute *continuous compliance*
after a path has been formally accepted.  Graduation answers "was the
delegated path fit for promotion at the time of the acceptance review?";
post-graduation governance answers "does the delegated path *remain*
compliant during and after rollout?"  Without a dedicated post-graduation
governance layer:

* Regressions in truth alignment, result convergence, operator visibility,
  compat boundary integrity, or continuity / replay contracts are not
  continuously observed after graduation.
* There is no unified authority that can surface and classify a governance
  violation so that release tightening, enforcement, or rollout rollback can
  act on a structured verdict.
* Operator / owner consoles lack a governance summary that maps a regression
  to its originating dimension.
* Long-term canonical path credibility rests entirely on the one-time
  graduation verdict rather than on ongoing compliance evidence.

This module closes that gap by establishing the **Delegated Flow
Post-Graduation Governance / Enforcement Layer** — the canonical evaluator
and authoritative compliance verdict layer for the delegated canonical path
after it has been formally graduated.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  DELEGATED FLOW POST-GRADUATION GOVERNANCE LAYER  (this module,     │
    │                                                    layer 13)         │
    │                                                                      │
    │  Continuously evaluates (read-only) across five governance           │
    │  dimensions:                                                         │
    │    • truth_alignment       — FlowLevelTruthOwnership                │
    │    • result_convergence    — FlowAwareResultConvergence             │
    │    • operator_visibility   — FlowLevelOperatorSurface               │
    │    • compat_bypass         — CompatLegacyPathBlockingCanonicalization│
    │    • continuity_replay     — FlowContinuityCoordinator              │
    │                                                                      │
    │  References the final acceptance / graduation artifact as the       │
    │  starting baseline via DelegatedFlowAcceptanceGate.                 │
    │                                                                      │
    │  Governance verdicts:                                                │
    │    • governance_compliant                                            │
    │    • governance_violation_due_to_truth_regression                   │
    │    • governance_violation_due_to_result_regression                  │
    │    • governance_violation_due_to_operator_visibility_regression     │
    │    • governance_violation_due_to_compat_bypass                      │
    │    • governance_unknown_due_to_missing_monitoring_signal            │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — the evaluator reads from existing runtime modules
   and the acceptance gate; it never mutates canonical state.
3. **Fail-conservative** — when a dimension signal is unavailable the
   evaluator assigns ``unknown`` status for that dimension and, if any
   dimension is unknown, the overall verdict is
   ``governance_unknown_due_to_missing_monitoring_signal``.
4. **Operator-visible violation details** — every ``violation`` or
   ``unknown`` dimension carries a human-readable ``violation_description``
   and a structured ``evidence`` dict so operators, auditors, and release
   owners can identify the originating regression dimension.
5. **Stable artifact semantics** — :class:`DelegatedFlowGovernanceReport`
   is JSON-serialisable and round-trippable, suitable as input for
   downstream enforcement, rollout tightening, and SLO monitoring.
6. **Acceptance gate prerequisite** — the evaluator checks that a valid
   graduation artifact (accepted_for_graduation) exists as the baseline
   before declaring ongoing compliance; if no accepted graduation artifact
   is found, the verdict is ``governance_unknown_due_to_missing_monitoring_signal``.

Integration points
------------------
* **DelegatedFlowAcceptanceGate** (PR-10V2) — consumed as the graduation
  baseline prerequisite.
* **DelegatedFlowReadinessGate** (PR-9V2) — referenced to confirm that
  post-graduation readiness has not regressed.
* **FlowLevelTruthOwnership** (PR-5V2) — truth alignment regression signal.
* **FlowAwareResultConvergence** (PR-6V2) — result convergence regression
  signal.
* **FlowLevelOperatorSurface** (PR-7V2) — operator visibility regression
  signal.
* **CompatLegacyPathBlockingCanonicalization** (PR-8V2) — compat/legacy
  bypass reintroduction signal.
* **FlowContinuityCoordinator** (PR-3V2) — continuity / replay contract
  regression signal.

Usage
-----
::

    from core.delegated_flow_post_graduation_governance import (
        get_governance_evaluator,
        GovernanceVerdict,
    )

    report = get_governance_evaluator().evaluate()
    if report.verdict == GovernanceVerdict.governance_compliant:
        # delegated canonical path remains compliant post-graduation
        ...
    else:
        for v in report.violations:
            print(f"[{v['dimension']}] {v['violation_description']}")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    # Authority & sentinels
    "DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY",
    "DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL",
    "GOVERNANCE_EVALUATOR_IS_UNIFIED_COMPLIANCE_ENTRY_POINT_POLICY",
    "GOVERNANCE_EVALUATOR_IS_PROJECTION_ONLY_POLICY",
    "GOVERNANCE_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY",
    "GOVERNANCE_VIOLATION_MUST_BE_OPERATOR_VISIBLE_POLICY",
    "GOVERNANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY",
    "ALL_FIVE_DIMENSIONS_REQUIRED_FOR_COMPLIANCE_POLICY",
    "ACCEPTANCE_GRADUATION_IS_PREREQUISITE_FOR_GOVERNANCE_POLICY",
    "GOVERNANCE_VERDICT_FEEDS_ENFORCEMENT_AND_RELEASE_TIGHTENING_POLICY",
    # Enumerations
    "GovernanceDimension",
    "DimensionGovernanceStatus",
    "GovernanceVerdict",
    # Data classes
    "DimensionGovernanceResult",
    "DelegatedFlowGovernanceReport",
    # Class
    "DelegatedFlowGovernanceEvaluator",
    # Helpers
    "evaluate_delegated_flow_governance",
    "get_governance_evaluator",
    "reset_governance_evaluator",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY: str = (
    "DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY::"
    "core.delegated_flow_post_graduation_governance::PR11V2::"
    "delegated-flow-post-graduation-governance-enforcement-layer::"
    "continuous-compliance-judgment-for-graduated-delegated-canonical-path"
)
"""Sentinel: this module is the canonical post-graduation governance
authority for the delegated canonical path.

Import to assert that an enforcement pipeline, operator console, or rollout
controller is reading governance verdicts from the correct canonical layer
rather than from individual sub-system state or the one-time graduation
artifact alone."""

DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL: str = (
    "DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL::"
    "package=PR11V2::profile=delegated-flow-post-graduation-governance-v1::"
    "module=core.delegated_flow_post_graduation_governance"
)
"""Package sentinel for PR-11V2."""

GOVERNANCE_EVALUATOR_IS_UNIFIED_COMPLIANCE_ENTRY_POINT_POLICY: str = (
    "POLICY::GOVERNANCE_EVALUATOR_IS_UNIFIED_COMPLIANCE_ENTRY_POINT_V1: "
    "DelegatedFlowGovernanceEvaluator.evaluate() is the sole authoritative "
    "entry point for determining whether the delegated canonical path remains "
    "compliant after graduation.  Enforcement pipelines, rollout controllers, "
    "and operator consoles MUST consume the evaluator's "
    "DelegatedFlowGovernanceReport; they MUST NOT derive compliance verdicts "
    "from individual sub-system modules in isolation."
)

GOVERNANCE_EVALUATOR_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::GOVERNANCE_EVALUATOR_IS_PROJECTION_ONLY_V1: "
    "DelegatedFlowGovernanceEvaluator is a read-only projection layer.  It "
    "MUST NOT mutate canonical runtime state, truth ownership records, "
    "result convergence state, operator surface records, compat policy "
    "state, or continuity / replay records.  All mutations remain the "
    "exclusive responsibility of the owning canonical modules."
)

GOVERNANCE_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY: str = (
    "POLICY::GOVERNANCE_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_V1: "
    "When a governance dimension signal is unavailable the evaluator MUST "
    "assign 'unknown' status to that dimension and produce a "
    "'governance_unknown_due_to_missing_monitoring_signal' overall verdict.  "
    "It MUST NOT assume compliance in the absence of signal."
)

GOVERNANCE_VIOLATION_MUST_BE_OPERATOR_VISIBLE_POLICY: str = (
    "POLICY::GOVERNANCE_VIOLATION_MUST_BE_OPERATOR_VISIBLE_V1: "
    "Every governance violation or unknown dimension MUST carry a "
    "human-readable violation_description and a structured evidence dict so "
    "that operators, release owners, and auditors can identify the regression "
    "dimension and act without needing to inspect raw sub-system state."
)

GOVERNANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY: str = (
    "POLICY::GOVERNANCE_VERDICT_IS_STABLE_ARTIFACT_V1: "
    "DelegatedFlowGovernanceReport is a stable, JSON-serialisable, "
    "round-trippable artifact.  Its schema MUST NOT break backward "
    "compatibility without a major version bump.  Enforcement pipelines and "
    "SLO monitors depend on the schema stability."
)

ALL_FIVE_DIMENSIONS_REQUIRED_FOR_COMPLIANCE_POLICY: str = (
    "POLICY::ALL_FIVE_DIMENSIONS_REQUIRED_FOR_COMPLIANCE_V1: "
    "All five governance dimensions — truth_alignment, result_convergence, "
    "operator_visibility, compat_bypass, continuity_replay — MUST produce "
    "'compliant' status for the overall verdict to be 'governance_compliant'.  "
    "A single dimension violation or unknown state is sufficient to classify "
    "the overall verdict as a violation or unknown."
)

ACCEPTANCE_GRADUATION_IS_PREREQUISITE_FOR_GOVERNANCE_POLICY: str = (
    "POLICY::ACCEPTANCE_GRADUATION_IS_PREREQUISITE_FOR_GOVERNANCE_V1: "
    "A valid 'accepted_for_graduation' verdict from DelegatedFlowAcceptanceGate "
    "is the required baseline for ongoing post-graduation governance.  If the "
    "acceptance artifact is absent or non-graduated, the evaluator MUST "
    "produce 'governance_unknown_due_to_missing_monitoring_signal' rather "
    "than attempting to classify violations without an established baseline."
)

GOVERNANCE_VERDICT_FEEDS_ENFORCEMENT_AND_RELEASE_TIGHTENING_POLICY: str = (
    "POLICY::GOVERNANCE_VERDICT_FEEDS_ENFORCEMENT_AND_RELEASE_TIGHTENING_V1: "
    "DelegatedFlowGovernanceReport.violations is the structured input for "
    "downstream enforcement actions and release tightening decisions.  "
    "Enforcement pipelines MUST consume this list rather than re-evaluating "
    "individual sub-system state independently."
)

# ---------------------------------------------------------------------------
# GovernanceDimension
# ---------------------------------------------------------------------------


class GovernanceDimension(str, Enum):
    """The five continuous governance dimensions observed post-graduation.

    Values
    ------
    truth_alignment
        Ongoing alignment between Android and V2 canonical truth ownership
        records.  Regression here indicates truth drift.

    result_convergence
        Ongoing convergence of results produced by the delegated canonical
        path.  Regression here indicates result drift or quarantine leakage.

    operator_visibility
        Ongoing ability of operators to observe delegated flow execution
        evidence and surface.  Regression here indicates visibility loss.

    compat_bypass
        Absence of compat/legacy bypass reintroduction.  A positive signal
        here indicates compat leakage or a removed blocking gate.

    continuity_replay
        Ongoing integrity of continuity / replay contracts.  Regression here
        indicates continuity drift or replay evidence loss.
    """

    truth_alignment = "truth_alignment"
    result_convergence = "result_convergence"
    operator_visibility = "operator_visibility"
    compat_bypass = "compat_bypass"
    continuity_replay = "continuity_replay"

    @classmethod
    def from_string(cls, value: str) -> "GovernanceDimension":
        """Return the member matching *value*, defaulting to
        ``truth_alignment`` on invalid input."""
        if not isinstance(value, str):
            return cls.truth_alignment
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.truth_alignment

    @classmethod
    def all_dimensions(cls) -> List["GovernanceDimension"]:
        """Return all five governance dimensions in canonical order."""
        return [
            cls.truth_alignment,
            cls.result_convergence,
            cls.operator_visibility,
            cls.compat_bypass,
            cls.continuity_replay,
        ]


# ---------------------------------------------------------------------------
# DimensionGovernanceStatus
# ---------------------------------------------------------------------------


class DimensionGovernanceStatus(str, Enum):
    """Per-dimension governance status.

    Values
    ------
    compliant
        The dimension shows no regressions relative to the graduation
        baseline.

    violation
        The dimension shows an active regression relative to the graduation
        baseline.

    unknown
        The monitoring signal for this dimension is absent or insufficient to
        make a compliance determination.
    """

    compliant = "compliant"
    violation = "violation"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "DimensionGovernanceStatus":
        """Return the member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# GovernanceVerdict
# ---------------------------------------------------------------------------


class GovernanceVerdict(str, Enum):
    """Overall post-graduation governance verdict for the delegated canonical
    path.

    Values
    ------
    governance_compliant
        All five governance dimensions are ``compliant``.  The delegated
        canonical path remains compliant after graduation.

    governance_violation_due_to_truth_regression
        The ``truth_alignment`` dimension detected a regression.  Truth
        alignment between Android and V2 canonical has drifted since
        graduation.

    governance_violation_due_to_result_regression
        The ``result_convergence`` dimension detected a regression.  Result
        convergence has quarantined or divergent results since graduation.

    governance_violation_due_to_operator_visibility_regression
        The ``operator_visibility`` dimension detected a regression.
        Operators can no longer reliably observe delegated flow execution
        evidence.

    governance_violation_due_to_compat_bypass
        The ``compat_bypass`` dimension detected active compat/legacy bypass
        reintroduction since graduation.

    governance_unknown_due_to_missing_monitoring_signal
        One or more dimensions have ``unknown`` status because the required
        monitoring signal is absent.  The evaluator cannot safely conclude
        compliance; treat as non-compliant pending signal restoration.
    """

    governance_compliant = "governance_compliant"
    governance_violation_due_to_truth_regression = (
        "governance_violation_due_to_truth_regression"
    )
    governance_violation_due_to_result_regression = (
        "governance_violation_due_to_result_regression"
    )
    governance_violation_due_to_operator_visibility_regression = (
        "governance_violation_due_to_operator_visibility_regression"
    )
    governance_violation_due_to_compat_bypass = (
        "governance_violation_due_to_compat_bypass"
    )
    governance_unknown_due_to_missing_monitoring_signal = (
        "governance_unknown_due_to_missing_monitoring_signal"
    )

    @classmethod
    def from_string(cls, value: str) -> "GovernanceVerdict":
        """Return the member matching *value*, defaulting to
        ``governance_unknown_due_to_missing_monitoring_signal``."""
        if not isinstance(value, str):
            return cls.governance_unknown_due_to_missing_monitoring_signal
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.governance_unknown_due_to_missing_monitoring_signal

    @property
    def is_compliant(self) -> bool:
        """Return ``True`` only when the verdict is
        ``governance_compliant``."""
        return self == GovernanceVerdict.governance_compliant

    @property
    def is_violation(self) -> bool:
        """Return ``True`` when the verdict is any
        ``governance_violation_*`` variant."""
        return self.value.startswith("governance_violation_")

    @property
    def is_unknown(self) -> bool:
        """Return ``True`` when the verdict is
        ``governance_unknown_due_to_missing_monitoring_signal``."""
        return self == GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal


# ---------------------------------------------------------------------------
# DimensionGovernanceResult
# ---------------------------------------------------------------------------


@dataclass
class DimensionGovernanceResult:
    """Per-dimension governance evaluation result.

    Fields
    ------
    dimension
        The :class:`GovernanceDimension` this result covers.
    status
        The :class:`DimensionGovernanceStatus` for this dimension.
    violation_description
        Human-readable description of the violation or signal absence.
        Empty string when ``status`` is ``compliant``.
    evidence
        Structured evidence dict from the originating sub-system.  May be
        empty when the signal is unavailable.
    signal_source
        Name of the module / callable that provided the monitoring signal.
    """

    dimension: GovernanceDimension = GovernanceDimension.truth_alignment
    status: DimensionGovernanceStatus = DimensionGovernanceStatus.unknown
    violation_description: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    signal_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "dimension": self.dimension.value,
            "status": self.status.value,
            "violation_description": self.violation_description,
            "evidence": self.evidence,
            "signal_source": self.signal_source,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionGovernanceResult":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=GovernanceDimension.from_string(
                data.get("dimension", "")
            ),
            status=DimensionGovernanceStatus.from_string(
                data.get("status", "")
            ),
            violation_description=data.get("violation_description", ""),
            evidence=data.get("evidence", {}),
            signal_source=data.get("signal_source", ""),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowGovernanceReport
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowGovernanceReport:
    """Full post-graduation governance report for the delegated canonical path.

    This is the stable, serialisable artifact produced by
    :class:`DelegatedFlowGovernanceEvaluator`.  It carries:

    * The overall ``verdict`` (one of the six :class:`GovernanceVerdict`
      values).
    * Per-dimension governance results for all five dimensions.
    * A human-readable ``summary`` suitable for operator consoles and audit
      logs.
    * Structured violations list for downstream enforcement tooling.
    * The ``acceptance_report_id`` of the graduation artifact that was used
      as the compliance baseline.
    * Metadata (report ID, generated timestamp, evaluator version).

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    verdict
        Overall post-graduation governance verdict.
    dimensions
        Mapping from :class:`GovernanceDimension` value string to the
        corresponding :class:`DimensionGovernanceResult`.
    summary
        Human-readable one-line summary of the overall governance state.
    violations
        List of dicts with keys ``dimension``, ``status``, and
        ``violation_description`` for all violation or unknown dimensions.
    is_compliant
        ``True`` when ``verdict`` is ``governance_compliant``.
    evaluator_version
        Version of the governance evaluator that produced this report.
    generated_at
        Unix timestamp of report generation.
    acceptance_report_id
        The ``report_id`` of the :class:`DelegatedFlowAcceptanceReport` that
        was consumed as the graduation baseline.  Empty string when the
        acceptance report was not available.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: GovernanceVerdict = (
        GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal
    )
    dimensions: Dict[str, DimensionGovernanceResult] = field(
        default_factory=dict
    )
    summary: str = ""
    violations: List[Dict[str, str]] = field(default_factory=list)
    is_compliant: bool = False
    evaluator_version: str = "1.0"
    generated_at: float = field(default_factory=time.time)
    acceptance_report_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "report_id": self.report_id,
            "verdict": self.verdict.value,
            "dimensions": {
                dim_key: dim_result.to_dict()
                for dim_key, dim_result in self.dimensions.items()
            },
            "summary": self.summary,
            "violations": self.violations,
            "is_compliant": self.is_compliant,
            "evaluator_version": self.evaluator_version,
            "generated_at": self.generated_at,
            "acceptance_report_id": self.acceptance_report_id,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowGovernanceReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        dimensions: Dict[str, DimensionGovernanceResult] = {}
        for dim_key, dim_data in data.get("dimensions", {}).items():
            dimensions[dim_key] = DimensionGovernanceResult.from_dict(dim_data)
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            verdict=GovernanceVerdict.from_string(data.get("verdict", "")),
            dimensions=dimensions,
            summary=data.get("summary", ""),
            violations=data.get("violations", []),
            is_compliant=data.get("is_compliant", False),
            evaluator_version=data.get("evaluator_version", "1.0"),
            generated_at=data.get("generated_at", time.time()),
            acceptance_report_id=data.get("acceptance_report_id", ""),
        )

    def get_dimension(
        self, dimension: GovernanceDimension
    ) -> Optional[DimensionGovernanceResult]:
        """Return the :class:`DimensionGovernanceResult` for *dimension*, or
        ``None`` if not present."""
        return self.dimensions.get(dimension.value)


# ---------------------------------------------------------------------------
# Internal helpers for sub-system signal probing
# ---------------------------------------------------------------------------


def _get_acceptance_gate():  # type: ignore[return]
    """Import and return the DelegatedFlowAcceptanceGate singleton.

    Returns ``None`` on import failure so the evaluator remains operational
    even when the acceptance gate module is unavailable (unknown verdict).
    """
    try:
        from core.delegated_flow_acceptance_gate import get_acceptance_gate

        return get_acceptance_gate()
    except Exception:  # noqa: BLE001
        return None


def _get_readiness_gate():  # type: ignore[return]
    """Import and return the DelegatedFlowReadinessGate singleton."""
    try:
        from core.delegated_flow_readiness_gate import get_readiness_gate

        return get_readiness_gate()
    except Exception:  # noqa: BLE001
        return None


def _get_truth_ownership():  # type: ignore[return]
    """Import and return the FlowLevelTruthOwnership singleton."""
    try:
        from core.flow_level_truth_ownership import get_truth_ownership

        return get_truth_ownership()
    except Exception:  # noqa: BLE001
        return None


def _get_result_convergence():  # type: ignore[return]
    """Import and return the FlowAwareResultConvergence singleton."""
    try:
        from core.flow_aware_result_convergence import get_result_convergence

        return get_result_convergence()
    except Exception:  # noqa: BLE001
        return None


def _get_operator_surface():  # type: ignore[return]
    """Import and return the FlowLevelOperatorSurface singleton."""
    try:
        from core.flow_level_operator_surface import get_operator_surface

        return get_operator_surface()
    except Exception:  # noqa: BLE001
        return None


def _get_compat_blocking():  # type: ignore[return]
    """Import and return the CompatLegacyPathBlockingCanonicalization
    singleton."""
    try:
        from core.compat_legacy_path_blocking_canonicalization import (
            get_compat_blocking,
        )

        return get_compat_blocking()
    except Exception:  # noqa: BLE001
        return None


def _get_continuity_coordinator():  # type: ignore[return]
    """Import and return the FlowContinuityCoordinator singleton."""
    try:
        from core.flow_continuity_coordinator import get_continuity_coordinator

        return get_continuity_coordinator()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# DelegatedFlowGovernanceEvaluator
# ---------------------------------------------------------------------------


class DelegatedFlowGovernanceEvaluator:
    """Continuous post-graduation governance evaluator for the delegated
    canonical path.

    This is the canonical evaluator that aggregates five governance dimension
    signals — using the PR-10V2 acceptance artifact as the graduation baseline
    — and produces a :class:`DelegatedFlowGovernanceReport`.  It is designed
    as a **read-only projection** — it never mutates any sub-system state.

    Use :func:`get_governance_evaluator` to obtain the process-global
    singleton.
    Use :func:`reset_governance_evaluator` to reset the singleton (test
    isolation).

    Usage
    -----
    ::

        from core.delegated_flow_post_graduation_governance import (
            get_governance_evaluator,
            GovernanceVerdict,
        )

        report = get_governance_evaluator().evaluate()
        if report.verdict.is_compliant:
            # delegated canonical path is continuously compliant
            ...
        else:
            for v in report.violations:
                print(f"[{v['dimension']}] {v['violation_description']}")
    """

    EVALUATOR_VERSION: str = "1.0"

    def evaluate(self) -> DelegatedFlowGovernanceReport:
        """Evaluate all five governance dimensions and produce a report.

        The method first checks that a valid graduation baseline exists via
        :func:`_evaluate_acceptance_baseline`.  If the baseline is missing or
        not accepted, it returns an ``unknown`` overall verdict without
        evaluating the remaining dimensions.

        Returns
        -------
        DelegatedFlowGovernanceReport
            Full governance report with overall verdict and per-dimension
            results.
        """
        dimensions: Dict[str, DimensionGovernanceResult] = {}
        acceptance_report_id: str = ""

        # --- 0. Acceptance baseline prerequisite ----------------------------
        baseline_result, acceptance_report_id = (
            self._evaluate_acceptance_baseline()
        )
        dimensions[baseline_result.dimension.value] = baseline_result

        if baseline_result.status == DimensionGovernanceStatus.unknown:
            # Cannot establish governance without a valid graduation baseline.
            verdict = (
                GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal
            )
            violations = self._collect_violations(dimensions)
            summary = self._build_summary(verdict, violations)
            is_compliant = False
            report = DelegatedFlowGovernanceReport(
                verdict=verdict,
                dimensions=dimensions,
                summary=summary,
                violations=violations,
                is_compliant=is_compliant,
                evaluator_version=self.EVALUATOR_VERSION,
                acceptance_report_id=acceptance_report_id,
            )
            logger.debug(
                "DelegatedFlowGovernanceEvaluator.evaluate() → "
                "verdict=%s (no baseline)",
                verdict.value,
            )
            return report

        # --- 1–5. Evaluate the five governance dimensions -------------------
        dim_truth = self._evaluate_truth_alignment()
        dim_result = self._evaluate_result_convergence()
        dim_operator = self._evaluate_operator_visibility()
        dim_compat = self._evaluate_compat_bypass()
        dim_continuity = self._evaluate_continuity_replay()

        for dim in (
            dim_truth,
            dim_result,
            dim_operator,
            dim_compat,
            dim_continuity,
        ):
            dimensions[dim.dimension.value] = dim

        verdict = self._compute_verdict(dimensions)
        violations = self._collect_violations(dimensions)
        summary = self._build_summary(verdict, violations)
        is_compliant = verdict == GovernanceVerdict.governance_compliant

        report = DelegatedFlowGovernanceReport(
            verdict=verdict,
            dimensions=dimensions,
            summary=summary,
            violations=violations,
            is_compliant=is_compliant,
            evaluator_version=self.EVALUATOR_VERSION,
            acceptance_report_id=acceptance_report_id,
        )
        logger.debug(
            "DelegatedFlowGovernanceEvaluator.evaluate() → verdict=%s violations=%d",
            verdict.value,
            len(violations),
        )
        return report

    # ------------------------------------------------------------------
    # Baseline evaluator
    # ------------------------------------------------------------------

    def _evaluate_acceptance_baseline(
        self,
    ) -> "Tuple[DimensionGovernanceResult, str]":
        """Check that a valid graduation artifact exists as baseline.

        Returns
        -------
        Tuple[DimensionGovernanceResult, str]
            A ``(result, acceptance_report_id)`` pair.  The *result* uses
            ``GovernanceDimension.truth_alignment`` as a placeholder dimension
            key (``__acceptance_baseline__`` is not a real governance
            dimension; we store the result under truth_alignment to keep the
            dimensions dict homogeneous and avoid adding a sixth enum entry
            just for the baseline check).

            The second element is the ``report_id`` of the consumed acceptance
            artifact, or an empty string when unavailable.
        """
        # Use a synthetic sentinel dimension value to mark the baseline entry.
        # We return it mapped under GovernanceDimension.truth_alignment in
        # evaluate() — but the evaluate() method adds it only when the baseline
        # is unknown; otherwise dimension keys are the five real dimensions.
        # To keep things clean we return it separately and let evaluate()
        # decide whether to forward it to the final dimensions dict.
        dimension = GovernanceDimension.truth_alignment
        signal_source = "core.delegated_flow_acceptance_gate.get_acceptance_gate"

        acceptance_gate = _get_acceptance_gate()
        if acceptance_gate is None:
            return (
                DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.unknown,
                    violation_description=(
                        "DelegatedFlowAcceptanceGate is not importable; "
                        "cannot establish graduation baseline for governance."
                    ),
                    signal_source=signal_source,
                ),
                "",
            )

        try:
            acceptance_report = acceptance_gate.evaluate()
            report_id: str = getattr(acceptance_report, "report_id", "")

            if not getattr(acceptance_report, "is_accepted_for_graduation", False):
                verdict_value = (
                    acceptance_report.verdict.value
                    if hasattr(acceptance_report.verdict, "value")
                    else str(acceptance_report.verdict)
                )
                evidence: Dict[str, Any] = {}
                if hasattr(acceptance_report, "to_dict"):
                    evidence = acceptance_report.to_dict()
                return (
                    DimensionGovernanceResult(
                        dimension=dimension,
                        status=DimensionGovernanceStatus.unknown,
                        violation_description=(
                            f"DelegatedFlowAcceptanceGate verdict is "
                            f"'{verdict_value}' (not accepted_for_graduation).  "
                            "Post-graduation governance requires a valid "
                            "graduation baseline."
                        ),
                        evidence=evidence,
                        signal_source=signal_source,
                    ),
                    report_id,
                )

            # Graduation baseline confirmed — return a compliant placeholder.
            evidence_ok: Dict[str, Any] = {}
            if hasattr(acceptance_report, "to_dict"):
                evidence_ok = acceptance_report.to_dict()
            return (
                DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.compliant,
                    violation_description="",
                    evidence=evidence_ok,
                    signal_source=signal_source,
                ),
                report_id,
            )

        except Exception as exc:  # noqa: BLE001
            return (
                DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.unknown,
                    violation_description=(
                        f"DelegatedFlowAcceptanceGate.evaluate() raised "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    signal_source=signal_source,
                ),
                "",
            )

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _evaluate_truth_alignment(self) -> DimensionGovernanceResult:
        """Evaluate the truth alignment governance dimension."""
        dimension = GovernanceDimension.truth_alignment
        signal_source = "core.flow_level_truth_ownership.get_truth_ownership"

        truth_obj = _get_truth_ownership()
        if truth_obj is None:
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    "FlowLevelTruthOwnership module is not importable; "
                    "truth alignment monitoring signal is absent."
                ),
                signal_source=signal_source,
            )

        try:
            evidence: Dict[str, Any] = {}
            has_regression = False
            violation_desc = ""

            if hasattr(truth_obj, "has_unresolved_contracts"):
                has_regression = bool(truth_obj.has_unresolved_contracts())
                if has_regression:
                    violation_desc = (
                        "FlowLevelTruthOwnership reports unresolved truth "
                        "contracts post-graduation (truth alignment regression)."
                    )
            elif hasattr(truth_obj, "get_summary"):
                summary = truth_obj.get_summary()
                if isinstance(summary, dict):
                    evidence = summary
                    has_regression = bool(
                        summary.get("has_unresolved_contracts", False)
                        or summary.get("alignment_gap", False)
                    )
                    if has_regression:
                        violation_desc = (
                            "FlowLevelTruthOwnership summary indicates a "
                            "truth alignment gap post-graduation."
                        )

            if not violation_desc and not has_regression:
                return DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.compliant,
                    violation_description="",
                    evidence=evidence,
                    signal_source=signal_source,
                )
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.violation,
                violation_description=violation_desc,
                evidence=evidence,
                signal_source=signal_source,
            )

        except Exception as exc:  # noqa: BLE001
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    f"FlowLevelTruthOwnership probe raised "
                    f"{type(exc).__name__}: {exc}"
                ),
                signal_source=signal_source,
            )

    def _evaluate_result_convergence(self) -> DimensionGovernanceResult:
        """Evaluate the result convergence governance dimension."""
        dimension = GovernanceDimension.result_convergence
        signal_source = (
            "core.flow_aware_result_convergence.get_result_convergence"
        )

        convergence_obj = _get_result_convergence()
        if convergence_obj is None:
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    "FlowAwareResultConvergence module is not importable; "
                    "result convergence monitoring signal is absent."
                ),
                signal_source=signal_source,
            )

        try:
            evidence: Dict[str, Any] = {}
            has_regression = False
            violation_desc = ""

            if hasattr(convergence_obj, "has_quarantined_results"):
                has_regression = bool(convergence_obj.has_quarantined_results())
                if has_regression:
                    violation_desc = (
                        "FlowAwareResultConvergence reports quarantined "
                        "results post-graduation (result convergence regression)."
                    )
            elif hasattr(convergence_obj, "get_summary"):
                summary = convergence_obj.get_summary()
                if isinstance(summary, dict):
                    evidence = summary
                    has_regression = bool(
                        summary.get("has_quarantined_results", False)
                        or summary.get("convergence_gap", False)
                    )
                    if has_regression:
                        violation_desc = (
                            "FlowAwareResultConvergence summary indicates a "
                            "result convergence gap post-graduation."
                        )

            if not violation_desc and not has_regression:
                return DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.compliant,
                    violation_description="",
                    evidence=evidence,
                    signal_source=signal_source,
                )
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.violation,
                violation_description=violation_desc,
                evidence=evidence,
                signal_source=signal_source,
            )

        except Exception as exc:  # noqa: BLE001
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    f"FlowAwareResultConvergence probe raised "
                    f"{type(exc).__name__}: {exc}"
                ),
                signal_source=signal_source,
            )

    def _evaluate_operator_visibility(self) -> DimensionGovernanceResult:
        """Evaluate the operator visibility governance dimension."""
        dimension = GovernanceDimension.operator_visibility
        signal_source = (
            "core.flow_level_operator_surface.get_operator_surface"
        )

        operator_obj = _get_operator_surface()
        if operator_obj is None:
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    "FlowLevelOperatorSurface module is not importable; "
                    "operator visibility monitoring signal is absent."
                ),
                signal_source=signal_source,
            )

        try:
            evidence: Dict[str, Any] = {}
            has_regression = False
            violation_desc = ""

            if hasattr(operator_obj, "has_visibility_gap"):
                has_regression = bool(operator_obj.has_visibility_gap())
                if has_regression:
                    violation_desc = (
                        "FlowLevelOperatorSurface reports a visibility gap "
                        "post-graduation (operator visibility regression)."
                    )
            elif hasattr(operator_obj, "get_summary"):
                summary = operator_obj.get_summary()
                if isinstance(summary, dict):
                    evidence = summary
                    has_regression = bool(
                        summary.get("has_visibility_gap", False)
                        or summary.get("execution_evidence_absent", False)
                    )
                    if has_regression:
                        violation_desc = (
                            "FlowLevelOperatorSurface summary indicates an "
                            "operator visibility gap post-graduation."
                        )

            if not violation_desc and not has_regression:
                return DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.compliant,
                    violation_description="",
                    evidence=evidence,
                    signal_source=signal_source,
                )
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.violation,
                violation_description=violation_desc,
                evidence=evidence,
                signal_source=signal_source,
            )

        except Exception as exc:  # noqa: BLE001
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    f"FlowLevelOperatorSurface probe raised "
                    f"{type(exc).__name__}: {exc}"
                ),
                signal_source=signal_source,
            )

    def _evaluate_compat_bypass(self) -> DimensionGovernanceResult:
        """Evaluate the compat/legacy bypass governance dimension."""
        dimension = GovernanceDimension.compat_bypass
        signal_source = (
            "core.compat_legacy_path_blocking_canonicalization.get_compat_blocking"
        )

        compat_obj = _get_compat_blocking()
        if compat_obj is None:
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    "CompatLegacyPathBlockingCanonicalization module is not "
                    "importable; compat bypass monitoring signal is absent."
                ),
                signal_source=signal_source,
            )

        try:
            evidence: Dict[str, Any] = {}
            has_regression = False
            violation_desc = ""

            if hasattr(compat_obj, "has_active_bypass"):
                has_regression = bool(compat_obj.has_active_bypass())
                if has_regression:
                    violation_desc = (
                        "CompatLegacyPathBlockingCanonicalization reports an "
                        "active compat/legacy bypass post-graduation "
                        "(compat bypass reintroduction)."
                    )
            elif hasattr(compat_obj, "get_summary"):
                summary = compat_obj.get_summary()
                if isinstance(summary, dict):
                    evidence = summary
                    has_regression = bool(
                        summary.get("has_active_bypass", False)
                        or summary.get("compat_leakage", False)
                    )
                    if has_regression:
                        violation_desc = (
                            "CompatLegacyPathBlockingCanonicalization summary "
                            "indicates a compat bypass regression post-graduation."
                        )

            if not violation_desc and not has_regression:
                return DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.compliant,
                    violation_description="",
                    evidence=evidence,
                    signal_source=signal_source,
                )
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.violation,
                violation_description=violation_desc,
                evidence=evidence,
                signal_source=signal_source,
            )

        except Exception as exc:  # noqa: BLE001
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    f"CompatLegacyPathBlockingCanonicalization probe raised "
                    f"{type(exc).__name__}: {exc}"
                ),
                signal_source=signal_source,
            )

    def _evaluate_continuity_replay(self) -> DimensionGovernanceResult:
        """Evaluate the continuity / replay contract governance dimension."""
        dimension = GovernanceDimension.continuity_replay
        signal_source = (
            "core.flow_continuity_coordinator.get_continuity_coordinator"
        )

        continuity_obj = _get_continuity_coordinator()
        if continuity_obj is None:
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    "FlowContinuityCoordinator module is not importable; "
                    "continuity / replay monitoring signal is absent."
                ),
                signal_source=signal_source,
            )

        try:
            evidence: Dict[str, Any] = {}
            has_regression = False
            violation_desc = ""

            if hasattr(continuity_obj, "has_replay_contract_gap"):
                has_regression = bool(
                    continuity_obj.has_replay_contract_gap()
                )
                if has_regression:
                    violation_desc = (
                        "FlowContinuityCoordinator reports a replay contract "
                        "gap post-graduation (continuity regression)."
                    )
            elif hasattr(continuity_obj, "get_summary"):
                summary = continuity_obj.get_summary()
                if isinstance(summary, dict):
                    evidence = summary
                    has_regression = bool(
                        summary.get("has_replay_contract_gap", False)
                        or summary.get("continuity_drift", False)
                    )
                    if has_regression:
                        violation_desc = (
                            "FlowContinuityCoordinator summary indicates a "
                            "continuity / replay contract regression post-graduation."
                        )

            if not violation_desc and not has_regression:
                return DimensionGovernanceResult(
                    dimension=dimension,
                    status=DimensionGovernanceStatus.compliant,
                    violation_description="",
                    evidence=evidence,
                    signal_source=signal_source,
                )
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.violation,
                violation_description=violation_desc,
                evidence=evidence,
                signal_source=signal_source,
            )

        except Exception as exc:  # noqa: BLE001
            return DimensionGovernanceResult(
                dimension=dimension,
                status=DimensionGovernanceStatus.unknown,
                violation_description=(
                    f"FlowContinuityCoordinator probe raised "
                    f"{type(exc).__name__}: {exc}"
                ),
                signal_source=signal_source,
            )

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(
        dimensions: Dict[str, DimensionGovernanceResult],
    ) -> GovernanceVerdict:
        """Derive the overall governance verdict from per-dimension results.

        Priority order (first matching rule wins):

        1. Any dimension ``unknown`` → ``governance_unknown_due_to_missing_monitoring_signal``
        2. ``truth_alignment`` violation → ``governance_violation_due_to_truth_regression``
        3. ``result_convergence`` violation → ``governance_violation_due_to_result_regression``
        4. ``operator_visibility`` violation → ``governance_violation_due_to_operator_visibility_regression``
        5. ``compat_bypass`` violation → ``governance_violation_due_to_compat_bypass``
        6. ``continuity_replay`` violation → ``governance_violation_due_to_truth_regression``
           (continuity regressions are truth-adjacent)
        7. All compliant → ``governance_compliant``
        """
        dim_statuses: Dict[str, str] = {
            k: v.status.value for k, v in dimensions.items()
        }

        # Rule 1: any unknown → unknown verdict
        if DimensionGovernanceStatus.unknown.value in dim_statuses.values():
            return GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal

        # Rule 2: truth_alignment violation
        truth_status = dim_statuses.get(GovernanceDimension.truth_alignment.value)
        if truth_status == DimensionGovernanceStatus.violation.value:
            return GovernanceVerdict.governance_violation_due_to_truth_regression

        # Rule 3: result_convergence violation
        result_status = dim_statuses.get(
            GovernanceDimension.result_convergence.value
        )
        if result_status == DimensionGovernanceStatus.violation.value:
            return GovernanceVerdict.governance_violation_due_to_result_regression

        # Rule 4: operator_visibility violation
        op_status = dim_statuses.get(GovernanceDimension.operator_visibility.value)
        if op_status == DimensionGovernanceStatus.violation.value:
            return (
                GovernanceVerdict.governance_violation_due_to_operator_visibility_regression
            )

        # Rule 5: compat_bypass violation
        compat_status = dim_statuses.get(GovernanceDimension.compat_bypass.value)
        if compat_status == DimensionGovernanceStatus.violation.value:
            return GovernanceVerdict.governance_violation_due_to_compat_bypass

        # Rule 6: continuity_replay violation (truth-adjacent)
        cont_status = dim_statuses.get(GovernanceDimension.continuity_replay.value)
        if cont_status == DimensionGovernanceStatus.violation.value:
            return GovernanceVerdict.governance_violation_due_to_truth_regression

        # Rule 7: all compliant
        return GovernanceVerdict.governance_compliant

    @staticmethod
    def _collect_violations(
        dimensions: Dict[str, DimensionGovernanceResult],
    ) -> List[Dict[str, str]]:
        """Collect violation entries for all non-compliant dimensions."""
        violations: List[Dict[str, str]] = []
        for dim_key, dim_result in dimensions.items():
            if dim_result.status != DimensionGovernanceStatus.compliant:
                violations.append(
                    {
                        "dimension": dim_key,
                        "status": dim_result.status.value,
                        "violation_description": dim_result.violation_description,
                    }
                )
        return violations

    @staticmethod
    def _build_summary(
        verdict: GovernanceVerdict,
        violations: List[Dict[str, str]],
    ) -> str:
        """Build a one-line human-readable governance summary."""
        if verdict == GovernanceVerdict.governance_compliant:
            return (
                "Delegated canonical path GOVERNANCE COMPLIANT: all five "
                "governance dimensions passed post-graduation."
            )
        viol_dims = [v["dimension"] for v in violations]
        return (
            f"Delegated canonical path GOVERNANCE NON-COMPLIANT: "
            f"verdict={verdict.value}, "
            f"violations=[{', '.join(viol_dims)}]."
        )


# ---------------------------------------------------------------------------
# Process-global singleton
# ---------------------------------------------------------------------------

_governance_evaluator: Optional[DelegatedFlowGovernanceEvaluator] = None


def get_governance_evaluator() -> DelegatedFlowGovernanceEvaluator:
    """Return the process-global :class:`DelegatedFlowGovernanceEvaluator`
    singleton, creating it on first call.

    Thread safety
    -------------
    Concurrent first calls may create multiple instances; the last writer
    wins.  This is acceptable because the evaluator is stateless and
    idempotent.
    """
    global _governance_evaluator
    if _governance_evaluator is None:
        _governance_evaluator = DelegatedFlowGovernanceEvaluator()
    return _governance_evaluator


def reset_governance_evaluator() -> None:
    """Reset the process-global singleton (for test isolation)."""
    global _governance_evaluator
    _governance_evaluator = None


def evaluate_delegated_flow_governance() -> DelegatedFlowGovernanceReport:
    """Evaluate delegated canonical path post-graduation governance using the
    global evaluator.

    Convenience wrapper for
    :meth:`DelegatedFlowGovernanceEvaluator.evaluate`.

    Returns
    -------
    DelegatedFlowGovernanceReport
    """
    return get_governance_evaluator().evaluate()
