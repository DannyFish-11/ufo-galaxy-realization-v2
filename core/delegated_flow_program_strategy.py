#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_program_strategy.py
========================================
PR-12V2 (post-533 dual-repo runtime host unification track):
Delegated Flow Program Strategy / Evolution Control Layer.

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
* **PR-11V2** — DelegatedFlowPostGraduationGovernance: continuous
  post-graduation compliance enforcement layer.

However, a governance / enforcement layer alone does not constitute a
*program-level strategy*.  Governance answers "does the delegated path remain
compliant right now?"; program strategy answers higher-order questions:

* How is the delegated canonical path's **long-term evolution posture**
  trending across contract stability, governance health, rollout maturity,
  regression pressure, and cross-subsystem coupling risk?
* Which subsystem changes threaten the canonical contracts at a *strategic*
  level, requiring roadmap-level decisions rather than a local patch?
* How should governance discoveries escalate into route-level evolution
  decisions, rather than remaining as isolated enforcement findings?
* What is the **program-level evolution posture** that operator/owner/release
  teams need to assess strategic risk over the planning horizon?

Without a dedicated program-strategy layer:

* Delegated path evolution remains fragmented: each governance finding is
  handled locally without cohesive strategic direction.
* Architecture drift re-accumulates silently between major governance reviews.
* Operator / owner consoles surface only point-in-time compliance, not the
  evolving risk trajectory of the delegated program.
* Release teams lack a stable strategy signal for roadmap planning, migration
  sequencing, or default-on policy tightening.

This module closes that gap by establishing the **Delegated Flow Program
Strategy / Evolution Control Layer** — the canonical evaluator and
authoritative program-strategy verdict layer for the delegated canonical path.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  DELEGATED FLOW PROGRAM STRATEGY / EVOLUTION CONTROL LAYER          │
    │                                    (this module, layer 14 / PR-12V2)│
    │                                                                      │
    │  Evaluates (read-only) across five strategy dimensions:             │
    │    • contract_stability       — canonical contract health trend      │
    │    • governance_trend         — governance/enforcement regression     │
    │    • rollout_maturity         — release posture / rollout maturity   │
    │    • regression_pressure      — accumulated regression / risk        │
    │    • cross_subsystem_coupling — cross-subsystem evolution coupling   │
    │                                                                      │
    │  References governance report, acceptance artifact, and readiness   │
    │  gate as upstream program signals.                                  │
    │                                                                      │
    │  Strategy verdicts:                                                  │
    │    • strategy_on_track                                               │
    │    • strategy_risk_due_to_contract_instability                       │
    │    • strategy_risk_due_to_governance_regression_trend                │
    │    • strategy_risk_due_to_rollout_maturity_gap                       │
    │    • strategy_risk_due_to_cross_subsystem_drift                      │
    │    • strategy_unknown_due_to_missing_program_signal                  │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — the evaluator reads from existing runtime modules
   and the governance / acceptance / readiness gate; it never mutates
   canonical state.
3. **Fail-conservative** — when a dimension signal is unavailable the
   evaluator assigns ``unknown`` status for that dimension and, if any
   dimension is unknown, the overall verdict is
   ``strategy_unknown_due_to_missing_program_signal``.
4. **Operator-visible risk details** — every ``at_risk`` or ``unknown``
   dimension carries a human-readable ``risk_description`` and a structured
   ``evidence`` dict so operators, release owners, and roadmap planners can
   identify the originating risk dimension without inspecting raw sub-system
   state.
5. **Stable artifact semantics** — :class:`DelegatedFlowStrategyReport` is
   JSON-serialisable and round-trippable, suitable as input for downstream
   roadmap planning, migration sequencing, and release policy tightening.
6. **Governance report as program signal** — the evaluator consumes the
   :class:`DelegatedFlowGovernanceReport` as the primary program-level
   signal, treating a non-compliant governance report as a strategy risk
   input rather than a terminal blocker.

Integration points
------------------
* **DelegatedFlowPostGraduationGovernance** (PR-11V2) — consumed as the
  primary program governance signal; its verdict and violations feed the
  ``governance_trend`` and ``regression_pressure`` dimensions.
* **DelegatedFlowAcceptanceGate** (PR-10V2) — consumed for ``contract_stability``
  and ``rollout_maturity`` dimensions.
* **DelegatedFlowReadinessGate** (PR-9V2) — consumed for ``rollout_maturity``
  dimension.
* **CompatLegacyPathBlockingCanonicalization** (PR-8V2) — cross-referenced
  for ``cross_subsystem_coupling`` risk.
* **FlowLevelTruthOwnership** (PR-5V2) — cross-referenced for
  ``contract_stability`` and ``cross_subsystem_coupling`` risk.
* **FlowAwareResultConvergence** (PR-6V2) — cross-referenced for
  ``cross_subsystem_coupling`` risk.
* **FlowContinuityCoordinator** (PR-3V2) — cross-referenced for
  ``cross_subsystem_coupling`` and ``regression_pressure`` risk.

Usage
-----
::

    from core.delegated_flow_program_strategy import (
        get_strategy_evaluator,
        StrategyVerdict,
    )

    report = get_strategy_evaluator().evaluate()
    if report.verdict == StrategyVerdict.strategy_on_track:
        # delegated canonical path program is on strategic track
        ...
    else:
        for r in report.risks:
            print(f"[{r['dimension']}] {r['risk_description']}")

Public API
----------
Authority sentinels::

    DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY
    DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL

Policy sentinels::

    STRATEGY_EVALUATOR_IS_PROGRAM_LEVEL_ENTRY_POINT_POLICY
    STRATEGY_EVALUATOR_IS_PROJECTION_ONLY_POLICY
    STRATEGY_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY
    STRATEGY_RISK_MUST_BE_OPERATOR_VISIBLE_POLICY
    STRATEGY_VERDICT_IS_STABLE_ARTIFACT_POLICY
    ALL_FIVE_STRATEGY_DIMENSIONS_REQUIRED_FOR_ON_TRACK_POLICY
    GOVERNANCE_REPORT_IS_PRIMARY_PROGRAM_SIGNAL_POLICY
    STRATEGY_VERDICT_FEEDS_ROADMAP_AND_RELEASE_POLICY_TIGHTENING_POLICY

Enumerations::

    StrategyDimension
    DimensionStrategyStatus
    StrategyVerdict

Data classes::

    DimensionStrategyResult
    DelegatedFlowStrategyReport

Class::

    DelegatedFlowStrategyEvaluator

Helpers::

    evaluate_delegated_flow_strategy() -> DelegatedFlowStrategyReport
    get_strategy_evaluator()  -> DelegatedFlowStrategyEvaluator
    reset_strategy_evaluator() -> None  # testing only
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.DelegatedFlowProgramStrategy")

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    # Authority & sentinels
    "DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY",
    "DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL",
    "STRATEGY_EVALUATOR_IS_PROGRAM_LEVEL_ENTRY_POINT_POLICY",
    "STRATEGY_EVALUATOR_IS_PROJECTION_ONLY_POLICY",
    "STRATEGY_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY",
    "STRATEGY_RISK_MUST_BE_OPERATOR_VISIBLE_POLICY",
    "STRATEGY_VERDICT_IS_STABLE_ARTIFACT_POLICY",
    "ALL_FIVE_STRATEGY_DIMENSIONS_REQUIRED_FOR_ON_TRACK_POLICY",
    "GOVERNANCE_REPORT_IS_PRIMARY_PROGRAM_SIGNAL_POLICY",
    "STRATEGY_VERDICT_FEEDS_ROADMAP_AND_RELEASE_POLICY_TIGHTENING_POLICY",
    # Enumerations
    "StrategyDimension",
    "DimensionStrategyStatus",
    "StrategyVerdict",
    # Data classes
    "DimensionStrategyResult",
    "DelegatedFlowStrategyReport",
    # Class
    "DelegatedFlowStrategyEvaluator",
    # Helpers
    "evaluate_delegated_flow_strategy",
    "get_strategy_evaluator",
    "reset_strategy_evaluator",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY: str = (
    "DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY::"
    "core.delegated_flow_program_strategy::PR12V2::"
    "delegated-flow-program-strategy-evolution-control-layer::"
    "program-level-posture-and-strategic-risk-for-delegated-canonical-path"
)
"""Sentinel: this module is the canonical program-strategy and evolution
control authority for the delegated canonical path.

Import to assert that a roadmap planner, release controller, or operator
console is reading strategy verdicts from the correct canonical layer rather
than from individual governance findings or point-in-time sub-system state."""

DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL: str = (
    "DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL::"
    "package=PR12V2::profile=delegated-flow-program-strategy-v1::"
    "module=core.delegated_flow_program_strategy"
)
"""Package sentinel for PR-12V2."""

STRATEGY_EVALUATOR_IS_PROGRAM_LEVEL_ENTRY_POINT_POLICY: str = (
    "POLICY::STRATEGY_EVALUATOR_IS_PROGRAM_LEVEL_ENTRY_POINT_V1: "
    "DelegatedFlowStrategyEvaluator.evaluate() is the sole authoritative "
    "program-level entry point for determining the delegated canonical path's "
    "strategic evolution posture.  Roadmap planners, release controllers, and "
    "operator consoles MUST consume the evaluator's "
    "DelegatedFlowStrategyReport; they MUST NOT derive strategy conclusions "
    "from individual governance findings or sub-system state in isolation."
)

STRATEGY_EVALUATOR_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::STRATEGY_EVALUATOR_IS_PROJECTION_ONLY_V1: "
    "DelegatedFlowStrategyEvaluator is a read-only projection layer.  It "
    "MUST NOT mutate canonical runtime state, governance records, "
    "acceptance gate artifacts, readiness gate state, or any sub-system "
    "module state.  All mutations remain the exclusive responsibility of the "
    "owning canonical modules."
)

STRATEGY_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY: str = (
    "POLICY::STRATEGY_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_V1: "
    "When a strategy dimension signal is unavailable the evaluator MUST "
    "assign 'unknown' status to that dimension and produce a "
    "'strategy_unknown_due_to_missing_program_signal' overall verdict.  "
    "It MUST NOT assume on-track posture in the absence of signal."
)

STRATEGY_RISK_MUST_BE_OPERATOR_VISIBLE_POLICY: str = (
    "POLICY::STRATEGY_RISK_MUST_BE_OPERATOR_VISIBLE_V1: "
    "Every strategy risk or unknown dimension MUST carry a human-readable "
    "risk_description and a structured evidence dict so that operators, "
    "release owners, and roadmap planners can identify the originating risk "
    "dimension and act without needing to inspect raw sub-system state."
)

STRATEGY_VERDICT_IS_STABLE_ARTIFACT_POLICY: str = (
    "POLICY::STRATEGY_VERDICT_IS_STABLE_ARTIFACT_V1: "
    "DelegatedFlowStrategyReport is a stable, JSON-serialisable, "
    "round-trippable artifact.  Its schema MUST NOT break backward "
    "compatibility without a major version bump.  Roadmap planners, release "
    "controllers, and SLO monitors depend on the schema stability."
)

ALL_FIVE_STRATEGY_DIMENSIONS_REQUIRED_FOR_ON_TRACK_POLICY: str = (
    "POLICY::ALL_FIVE_STRATEGY_DIMENSIONS_REQUIRED_FOR_ON_TRACK_V1: "
    "All five strategy dimensions — contract_stability, governance_trend, "
    "rollout_maturity, regression_pressure, cross_subsystem_coupling — MUST "
    "produce 'on_track' status for the overall verdict to be "
    "'strategy_on_track'.  A single dimension at_risk or unknown state is "
    "sufficient to classify the overall verdict as a risk or unknown."
)

GOVERNANCE_REPORT_IS_PRIMARY_PROGRAM_SIGNAL_POLICY: str = (
    "POLICY::GOVERNANCE_REPORT_IS_PRIMARY_PROGRAM_SIGNAL_V1: "
    "The DelegatedFlowGovernanceReport from PR-11V2 is the primary "
    "program-level signal for strategy evaluation.  A non-compliant "
    "governance report contributes to strategy risk without being a terminal "
    "blocker; the evaluator integrates it as one of five strategy dimension "
    "signals.  Strategy evaluation MUST reference the governance report for "
    "governance_trend and regression_pressure dimensions."
)

STRATEGY_VERDICT_FEEDS_ROADMAP_AND_RELEASE_POLICY_TIGHTENING_POLICY: str = (
    "POLICY::STRATEGY_VERDICT_FEEDS_ROADMAP_AND_RELEASE_POLICY_TIGHTENING_V1: "
    "DelegatedFlowStrategyReport.risks is the structured input for downstream "
    "roadmap planning, migration sequencing, and release policy tightening "
    "decisions.  Roadmap planners MUST consume this list rather than "
    "re-deriving strategic risk from individual sub-system state."
)

# ---------------------------------------------------------------------------
# StrategyDimension
# ---------------------------------------------------------------------------


class StrategyDimension(str, Enum):
    """The five program-level strategy dimensions for delegated stack evolution.

    Values
    ------
    contract_stability
        Trend health of the canonical contracts underpinning the delegated
        path.  Instability here indicates that downstream subsystems consuming
        the canonical contracts may be silently broken by upstream changes.

    governance_trend
        Trend of the post-graduation governance compliance verdicts over time.
        A regression trend here indicates that the governance enforcement
        layer is detecting deteriorating compliance, suggesting a systemic
        issue rather than an isolated incident.

    rollout_maturity
        Readiness and release posture of the delegated canonical path.
        Immaturity here indicates the path is not ready for default-on
        promotion or higher-trust rollout tiers.

    regression_pressure
        Accumulated regression pressure or strategic risk from unresolved
        governance violations, evidence gaps, or truth ownership drift.
        High pressure here indicates the delegated path is carrying technical
        debt that may require roadmap-level remediation.

    cross_subsystem_coupling
        Evolution coupling risk across subsystems that share the delegated
        canonical path (truth ownership, result convergence, compat blocking,
        continuity / replay).  High coupling risk here indicates that a
        change in one subsystem could silently break the canonical path in
        another.
    """

    contract_stability = "contract_stability"
    governance_trend = "governance_trend"
    rollout_maturity = "rollout_maturity"
    regression_pressure = "regression_pressure"
    cross_subsystem_coupling = "cross_subsystem_coupling"

    @classmethod
    def from_string(cls, value: str) -> "StrategyDimension":
        """Return the member matching *value*, defaulting to
        ``contract_stability`` on invalid input."""
        if not isinstance(value, str):
            return cls.contract_stability
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.contract_stability

    @classmethod
    def all_dimensions(cls) -> List["StrategyDimension"]:
        """Return all five strategy dimensions in canonical order."""
        return [
            cls.contract_stability,
            cls.governance_trend,
            cls.rollout_maturity,
            cls.regression_pressure,
            cls.cross_subsystem_coupling,
        ]


# ---------------------------------------------------------------------------
# DimensionStrategyStatus
# ---------------------------------------------------------------------------


class DimensionStrategyStatus(str, Enum):
    """Per-dimension strategy evaluation status.

    Values
    ------
    on_track
        The dimension shows no strategic risk signals relative to the
        program's evolution targets.

    at_risk
        The dimension shows active strategic risk signals that require
        roadmap-level attention.

    unknown
        The program signal for this dimension is absent or insufficient to
        make a strategy determination.
    """

    on_track = "on_track"
    at_risk = "at_risk"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "DimensionStrategyStatus":
        """Return the member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# StrategyVerdict
# ---------------------------------------------------------------------------


class StrategyVerdict(str, Enum):
    """Overall program-level strategy verdict for the delegated canonical path.

    Values
    ------
    strategy_on_track
        All five strategy dimensions are ``on_track``.  The delegated
        canonical path program is proceeding on strategic track.

    strategy_risk_due_to_contract_instability
        The ``contract_stability`` dimension detected strategic risk.
        Canonical contracts underpinning the delegated path are unstable
        and require roadmap-level attention.

    strategy_risk_due_to_governance_regression_trend
        The ``governance_trend`` or ``regression_pressure`` dimension
        detected strategic risk.  Governance compliance is trending toward
        regression and requires program-level intervention.

    strategy_risk_due_to_rollout_maturity_gap
        The ``rollout_maturity`` dimension detected strategic risk.  The
        delegated path is not ready for default-on promotion or the next
        rollout tier, introducing migration delay risk.

    strategy_risk_due_to_cross_subsystem_drift
        The ``cross_subsystem_coupling`` dimension detected strategic risk.
        Evolution coupling between subsystems sharing the delegated path is
        accumulating architecture drift risk.

    strategy_unknown_due_to_missing_program_signal
        One or more dimensions have ``unknown`` status because the required
        program signal is absent.  The evaluator cannot safely conclude
        on-track posture; treat as at-risk pending signal restoration.
    """

    strategy_on_track = "strategy_on_track"
    strategy_risk_due_to_contract_instability = (
        "strategy_risk_due_to_contract_instability"
    )
    strategy_risk_due_to_governance_regression_trend = (
        "strategy_risk_due_to_governance_regression_trend"
    )
    strategy_risk_due_to_rollout_maturity_gap = (
        "strategy_risk_due_to_rollout_maturity_gap"
    )
    strategy_risk_due_to_cross_subsystem_drift = (
        "strategy_risk_due_to_cross_subsystem_drift"
    )
    strategy_unknown_due_to_missing_program_signal = (
        "strategy_unknown_due_to_missing_program_signal"
    )

    @classmethod
    def from_string(cls, value: str) -> "StrategyVerdict":
        """Return the member matching *value*, defaulting to
        ``strategy_unknown_due_to_missing_program_signal``."""
        if not isinstance(value, str):
            return cls.strategy_unknown_due_to_missing_program_signal
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.strategy_unknown_due_to_missing_program_signal

    @property
    def is_on_track(self) -> bool:
        """Return ``True`` only when the verdict is ``strategy_on_track``."""
        return self == StrategyVerdict.strategy_on_track

    @property
    def is_at_risk(self) -> bool:
        """Return ``True`` when the verdict is any ``strategy_risk_*``
        variant."""
        return self.value.startswith("strategy_risk_")

    @property
    def is_unknown(self) -> bool:
        """Return ``True`` when the verdict is
        ``strategy_unknown_due_to_missing_program_signal``."""
        return self == StrategyVerdict.strategy_unknown_due_to_missing_program_signal


# ---------------------------------------------------------------------------
# DimensionStrategyResult
# ---------------------------------------------------------------------------


@dataclass
class DimensionStrategyResult:
    """Per-dimension strategy evaluation result.

    Fields
    ------
    dimension
        The :class:`StrategyDimension` this result covers.
    status
        The :class:`DimensionStrategyStatus` for this dimension.
    risk_description
        Human-readable description of the risk or signal absence.
        Empty string when ``status`` is ``on_track``.
    evidence
        Structured evidence dict from the originating sub-system or
        program signal.  May be empty when the signal is unavailable.
    signal_source
        Name of the module / callable that provided the program signal.
    """

    dimension: StrategyDimension = StrategyDimension.contract_stability
    status: DimensionStrategyStatus = DimensionStrategyStatus.unknown
    risk_description: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    signal_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "dimension": self.dimension.value,
            "status": self.status.value,
            "risk_description": self.risk_description,
            "evidence": self.evidence,
            "signal_source": self.signal_source,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionStrategyResult":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=StrategyDimension.from_string(
                data.get("dimension", "")
            ),
            status=DimensionStrategyStatus.from_string(
                data.get("status", "")
            ),
            risk_description=data.get("risk_description", ""),
            evidence=data.get("evidence", {}),
            signal_source=data.get("signal_source", ""),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowStrategyReport
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowStrategyReport:
    """Full program-strategy report for the delegated canonical path.

    This is the stable, serialisable artifact produced by
    :class:`DelegatedFlowStrategyEvaluator`.  It carries:

    * The overall ``verdict`` (one of the six :class:`StrategyVerdict`
      values).
    * Per-dimension strategy results for all five dimensions.
    * A human-readable ``summary`` suitable for operator consoles, roadmap
      reviews, and release planning.
    * Structured risks list for downstream roadmap, migration sequencing, and
      release policy tightening tooling.
    * The ``governance_report_id`` of the governance artifact consumed as the
      primary program signal.
    * The ``acceptance_report_id`` of the graduation artifact referenced for
      contract stability and rollout maturity dimensions.
    * Metadata (report ID, generated timestamp, evaluator version).

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    verdict
        Overall program-level strategy verdict.
    dimensions
        Mapping from :class:`StrategyDimension` value string to the
        corresponding :class:`DimensionStrategyResult`.
    summary
        Human-readable one-line summary of the overall strategy posture.
    risks
        List of dicts with keys ``dimension``, ``status``, and
        ``risk_description`` for all at-risk or unknown dimensions.
    is_on_track
        ``True`` when ``verdict`` is ``strategy_on_track``.
    evaluator_version
        Version of the strategy evaluator that produced this report.
    generated_at
        Unix timestamp of report generation.
    governance_report_id
        The ``report_id`` of the :class:`DelegatedFlowGovernanceReport` that
        was consumed as the primary program signal.  Empty string when the
        governance report was not available.
    acceptance_report_id
        The ``report_id`` of the :class:`DelegatedFlowAcceptanceReport` that
        was referenced for contract stability and rollout maturity dimensions.
        Empty string when the acceptance report was not available.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: StrategyVerdict = (
        StrategyVerdict.strategy_unknown_due_to_missing_program_signal
    )
    dimensions: Dict[str, DimensionStrategyResult] = field(
        default_factory=dict
    )
    summary: str = ""
    risks: List[Dict[str, str]] = field(default_factory=list)
    is_on_track: bool = False
    evaluator_version: str = "1.0"
    generated_at: float = field(default_factory=time.time)
    governance_report_id: str = ""
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
            "risks": self.risks,
            "is_on_track": self.is_on_track,
            "evaluator_version": self.evaluator_version,
            "generated_at": self.generated_at,
            "governance_report_id": self.governance_report_id,
            "acceptance_report_id": self.acceptance_report_id,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowStrategyReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        dimensions: Dict[str, DimensionStrategyResult] = {}
        for dim_key, dim_data in data.get("dimensions", {}).items():
            dimensions[dim_key] = DimensionStrategyResult.from_dict(dim_data)
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            verdict=StrategyVerdict.from_string(data.get("verdict", "")),
            dimensions=dimensions,
            summary=data.get("summary", ""),
            risks=data.get("risks", []),
            is_on_track=data.get("is_on_track", False),
            evaluator_version=data.get("evaluator_version", "1.0"),
            generated_at=data.get("generated_at", time.time()),
            governance_report_id=data.get("governance_report_id", ""),
            acceptance_report_id=data.get("acceptance_report_id", ""),
        )

    def get_dimension(
        self, dimension: StrategyDimension
    ) -> Optional[DimensionStrategyResult]:
        """Return the :class:`DimensionStrategyResult` for *dimension*, or
        ``None`` if not present."""
        return self.dimensions.get(dimension.value)


# ---------------------------------------------------------------------------
# Internal helpers for program signal probing
# ---------------------------------------------------------------------------


def _get_governance_evaluator():  # type: ignore[return]
    """Import and return the DelegatedFlowGovernanceEvaluator singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the governance module is unavailable (unknown
    verdict).
    """
    try:
        from core.delegated_flow_post_graduation_governance import (
            get_governance_evaluator,
        )

        return get_governance_evaluator()
    except Exception:  # noqa: BLE001
        return None


def _get_acceptance_gate():  # type: ignore[return]
    """Import and return the DelegatedFlowAcceptanceGate singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the acceptance gate module is unavailable.
    """
    try:
        from core.delegated_flow_acceptance_gate import get_acceptance_gate

        return get_acceptance_gate()
    except Exception:  # noqa: BLE001
        return None


def _get_readiness_gate():  # type: ignore[return]
    """Import and return the DelegatedFlowReadinessGate singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the readiness gate module is unavailable.
    """
    try:
        from core.delegated_flow_readiness_gate import get_readiness_gate

        return get_readiness_gate()
    except Exception:  # noqa: BLE001
        return None


def _get_truth_ownership():  # type: ignore[return]
    """Import and return the FlowLevelTruthOwnership singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the truth ownership module is unavailable.
    """
    try:
        from core.flow_level_truth_ownership import get_truth_ownership

        return get_truth_ownership()
    except Exception:  # noqa: BLE001
        return None


def _get_result_convergence():  # type: ignore[return]
    """Import and return the FlowAwareResultConvergence singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the result convergence module is unavailable.
    """
    try:
        from core.flow_aware_result_convergence import get_result_convergence

        return get_result_convergence()
    except Exception:  # noqa: BLE001
        return None


def _get_continuity_coordinator():  # type: ignore[return]
    """Import and return the FlowContinuityCoordinator singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the continuity coordinator module is unavailable.
    """
    try:
        from core.flow_continuity_coordinator import get_continuity_coordinator

        return get_continuity_coordinator()
    except Exception:  # noqa: BLE001
        return None


def _get_compat_blocking():  # type: ignore[return]
    """Import and return the CompatLegacyPathBlockingCanonicalization singleton.

    Returns ``None`` on import failure so the strategy evaluator remains
    operational even when the compat blocking module is unavailable.
    """
    try:
        from core.compat_legacy_path_blocking_canonicalization import (
            get_compat_blocking,
        )

        return get_compat_blocking()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# DelegatedFlowStrategyEvaluator
# ---------------------------------------------------------------------------


class DelegatedFlowStrategyEvaluator:
    """Program-level strategy evaluator for the delegated canonical path.

    This is the canonical evaluator that aggregates five program-level
    strategy dimension signals — using the PR-11V2 governance report as the
    primary program signal — and produces a
    :class:`DelegatedFlowStrategyReport`.  It is designed as a **read-only
    projection** — it never mutates any sub-system state.

    Use :func:`get_strategy_evaluator` to obtain the process-global singleton.
    Use :func:`reset_strategy_evaluator` to reset the singleton (test
    isolation).

    Usage
    -----
    ::

        from core.delegated_flow_program_strategy import (
            get_strategy_evaluator,
            StrategyVerdict,
        )

        report = get_strategy_evaluator().evaluate()
        if report.verdict.is_on_track:
            # delegated canonical path program is on strategic track
            ...
        else:
            for r in report.risks:
                print(f"[{r['dimension']}] {r['risk_description']}")
    """

    EVALUATOR_VERSION: str = "1.0"

    def evaluate(self) -> DelegatedFlowStrategyReport:
        """Evaluate all five strategy dimensions and produce a report.

        Returns
        -------
        DelegatedFlowStrategyReport
            Full strategy report with overall verdict and per-dimension
            results.
        """
        dimensions: Dict[str, DimensionStrategyResult] = {}
        governance_report_id: str = ""
        acceptance_report_id: str = ""

        # --- Obtain the primary program signals (governance + acceptance) ---
        governance_report, governance_report_id = (
            self._fetch_governance_report()
        )
        acceptance_report, acceptance_report_id = (
            self._fetch_acceptance_report()
        )

        # --- 1. contract_stability -----------------------------------------
        dim_contract = self._evaluate_contract_stability(
            governance_report, acceptance_report
        )
        dimensions[dim_contract.dimension.value] = dim_contract

        # --- 2. governance_trend -------------------------------------------
        dim_gov_trend = self._evaluate_governance_trend(governance_report)
        dimensions[dim_gov_trend.dimension.value] = dim_gov_trend

        # --- 3. rollout_maturity -------------------------------------------
        dim_rollout = self._evaluate_rollout_maturity(
            governance_report, acceptance_report
        )
        dimensions[dim_rollout.dimension.value] = dim_rollout

        # --- 4. regression_pressure ----------------------------------------
        dim_regression = self._evaluate_regression_pressure(governance_report)
        dimensions[dim_regression.dimension.value] = dim_regression

        # --- 5. cross_subsystem_coupling -----------------------------------
        dim_coupling = self._evaluate_cross_subsystem_coupling(
            governance_report
        )
        dimensions[dim_coupling.dimension.value] = dim_coupling

        verdict = self._compute_verdict(dimensions)
        risks = self._collect_risks(dimensions)
        summary = self._build_summary(verdict, risks)
        is_on_track = verdict == StrategyVerdict.strategy_on_track

        report = DelegatedFlowStrategyReport(
            verdict=verdict,
            dimensions=dimensions,
            summary=summary,
            risks=risks,
            is_on_track=is_on_track,
            evaluator_version=self.EVALUATOR_VERSION,
            governance_report_id=governance_report_id,
            acceptance_report_id=acceptance_report_id,
        )
        logger.debug(
            "DelegatedFlowStrategyEvaluator.evaluate() → verdict=%s risks=%d",
            verdict.value,
            len(risks),
        )
        return report

    # ------------------------------------------------------------------
    # Program signal fetchers
    # ------------------------------------------------------------------

    def _fetch_governance_report(
        self,
    ) -> Tuple[Optional[Any], str]:
        """Fetch the governance report from the PR-11V2 governance evaluator.

        Returns
        -------
        Tuple[Optional[Any], str]
            ``(governance_report, report_id)``.  Both are falsy when the
            governance evaluator is unavailable.
        """
        gov_evaluator = _get_governance_evaluator()
        if gov_evaluator is None:
            return None, ""
        try:
            report = gov_evaluator.evaluate()
            report_id: str = getattr(report, "report_id", "")
            return report, report_id
        except Exception:  # noqa: BLE001
            return None, ""

    def _fetch_acceptance_report(
        self,
    ) -> Tuple[Optional[Any], str]:
        """Fetch the acceptance report from the PR-10V2 acceptance gate.

        Returns
        -------
        Tuple[Optional[Any], str]
            ``(acceptance_report, report_id)``.  Both are falsy when the
            acceptance gate is unavailable.
        """
        acceptance_gate = _get_acceptance_gate()
        if acceptance_gate is None:
            return None, ""
        try:
            report = acceptance_gate.evaluate()
            report_id: str = getattr(report, "report_id", "")
            return report, report_id
        except Exception:  # noqa: BLE001
            return None, ""

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _evaluate_contract_stability(
        self,
        governance_report: Optional[Any],
        acceptance_report: Optional[Any],
    ) -> DimensionStrategyResult:
        """Evaluate the canonical contract stability strategy dimension.

        Risk signals:
        * Governance report shows violations in truth_alignment or
          result_convergence dimensions (canonical contract erosion).
        * Acceptance report is not in accepted_for_graduation state (no
          stable contract baseline was established).
        * FlowLevelTruthOwnership reports unresolved contracts.
        """
        dimension = StrategyDimension.contract_stability
        signal_source = (
            "core.delegated_flow_post_graduation_governance + "
            "core.delegated_flow_acceptance_gate + "
            "core.flow_level_truth_ownership"
        )

        if governance_report is None and acceptance_report is None:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "Both governance report and acceptance report are "
                    "unavailable; cannot assess canonical contract stability."
                ),
                signal_source=signal_source,
            )

        at_risk = False
        risk_parts: List[str] = []
        evidence: Dict[str, Any] = {}

        # Check acceptance baseline
        if acceptance_report is not None:
            is_accepted = getattr(
                acceptance_report, "is_accepted_for_graduation", None
            )
            if is_accepted is False:
                at_risk = True
                verdict_val = ""
                if hasattr(acceptance_report, "verdict"):
                    verdict_val = (
                        acceptance_report.verdict.value
                        if hasattr(acceptance_report.verdict, "value")
                        else str(acceptance_report.verdict)
                    )
                risk_parts.append(
                    f"Acceptance gate verdict '{verdict_val}' indicates no "
                    "stable canonical contract baseline has been established."
                )
            if hasattr(acceptance_report, "to_dict"):
                try:
                    evidence["acceptance_report"] = acceptance_report.to_dict()
                except Exception:  # noqa: BLE001
                    pass

        # Check governance for truth/result violations
        if governance_report is not None:
            dims = getattr(governance_report, "dimensions", {})
            for contract_dim_key in ("truth_alignment", "result_convergence"):
                dim_result = dims.get(contract_dim_key)
                if dim_result is not None:
                    status_val = (
                        dim_result.status.value
                        if hasattr(dim_result.status, "value")
                        else str(getattr(dim_result, "status", ""))
                    )
                    if status_val == "violation":
                        at_risk = True
                        risk_parts.append(
                            f"Governance dimension '{contract_dim_key}' shows "
                            "a violation, indicating canonical contract erosion."
                        )
            if hasattr(governance_report, "to_dict"):
                try:
                    evidence["governance_report"] = governance_report.to_dict()
                except Exception:  # noqa: BLE001
                    pass

        # Check FlowLevelTruthOwnership directly
        truth_obj = _get_truth_ownership()
        if truth_obj is not None:
            try:
                if hasattr(truth_obj, "has_unresolved_contracts") and bool(
                    truth_obj.has_unresolved_contracts()
                ):
                    at_risk = True
                    risk_parts.append(
                        "FlowLevelTruthOwnership reports unresolved truth "
                        "contracts (contract stability at risk)."
                    )
            except Exception:  # noqa: BLE001
                pass

        if at_risk:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.at_risk,
                risk_description=" | ".join(risk_parts) if risk_parts else (
                    "Canonical contract stability at risk (unspecified signal)."
                ),
                evidence=evidence,
                signal_source=signal_source,
            )
        return DimensionStrategyResult(
            dimension=dimension,
            status=DimensionStrategyStatus.on_track,
            risk_description="",
            evidence=evidence,
            signal_source=signal_source,
        )

    def _evaluate_governance_trend(
        self,
        governance_report: Optional[Any],
    ) -> DimensionStrategyResult:
        """Evaluate the governance compliance trend strategy dimension.

        Risk signals:
        * Governance report is non-compliant (any violation verdict).
        * Governance report is unknown (missing monitoring signal).
        """
        dimension = StrategyDimension.governance_trend
        signal_source = "core.delegated_flow_post_graduation_governance"

        if governance_report is None:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "Governance report unavailable; cannot assess governance "
                    "compliance trend."
                ),
                signal_source=signal_source,
            )

        evidence: Dict[str, Any] = {}
        if hasattr(governance_report, "to_dict"):
            try:
                evidence = governance_report.to_dict()
            except Exception:  # noqa: BLE001
                pass

        verdict = getattr(governance_report, "verdict", None)
        if verdict is None:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "Governance report verdict field is absent; cannot assess "
                    "governance compliance trend."
                ),
                evidence=evidence,
                signal_source=signal_source,
            )

        verdict_value: str = (
            verdict.value if hasattr(verdict, "value") else str(verdict)
        )

        if verdict_value == "governance_compliant":
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.on_track,
                risk_description="",
                evidence=evidence,
                signal_source=signal_source,
            )

        if "unknown" in verdict_value:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    f"Governance verdict is '{verdict_value}' (unknown / "
                    "missing signal); governance compliance trend cannot be "
                    "determined."
                ),
                evidence=evidence,
                signal_source=signal_source,
            )

        # Any governance_violation_* verdict
        return DimensionStrategyResult(
            dimension=dimension,
            status=DimensionStrategyStatus.at_risk,
            risk_description=(
                f"Governance verdict is '{verdict_value}', indicating an "
                "active governance regression trend that requires program-level "
                "attention."
            ),
            evidence=evidence,
            signal_source=signal_source,
        )

    def _evaluate_rollout_maturity(
        self,
        governance_report: Optional[Any],
        acceptance_report: Optional[Any],
    ) -> DimensionStrategyResult:
        """Evaluate the rollout maturity / release posture strategy dimension.

        Risk signals:
        * Acceptance gate not accepted_for_graduation (no stable rollout
          baseline).
        * Readiness gate not ready (path not cleared for rollout).
        * Governance report shows compat_bypass violation (rollout integrity
          risk).
        """
        dimension = StrategyDimension.rollout_maturity
        signal_source = (
            "core.delegated_flow_acceptance_gate + "
            "core.delegated_flow_readiness_gate + "
            "core.delegated_flow_post_graduation_governance"
        )

        at_risk = False
        risk_parts: List[str] = []
        evidence: Dict[str, Any] = {}
        any_signal = False

        # Check acceptance gate
        if acceptance_report is not None:
            any_signal = True
            is_accepted = getattr(
                acceptance_report, "is_accepted_for_graduation", None
            )
            if is_accepted is False:
                at_risk = True
                risk_parts.append(
                    "Acceptance gate has not graduated the delegated path; "
                    "rollout maturity baseline is absent."
                )
            if hasattr(acceptance_report, "to_dict"):
                try:
                    evidence["acceptance_report"] = acceptance_report.to_dict()
                except Exception:  # noqa: BLE001
                    pass

        # Check readiness gate
        readiness_gate = _get_readiness_gate()
        if readiness_gate is not None:
            any_signal = True
            try:
                readiness_report = readiness_gate.evaluate()
                is_ready = getattr(readiness_report, "is_ready", None)
                if is_ready is False:
                    at_risk = True
                    risk_parts.append(
                        "DelegatedFlowReadinessGate verdict is not ready; "
                        "delegated path is not cleared for rollout."
                    )
                if hasattr(readiness_report, "to_dict"):
                    try:
                        evidence["readiness_report"] = readiness_report.to_dict()
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        # Check governance for compat_bypass violation
        if governance_report is not None:
            any_signal = True
            dims = getattr(governance_report, "dimensions", {})
            compat_dim = dims.get("compat_bypass")
            if compat_dim is not None:
                status_val = (
                    compat_dim.status.value
                    if hasattr(compat_dim.status, "value")
                    else str(getattr(compat_dim, "status", ""))
                )
                if status_val == "violation":
                    at_risk = True
                    risk_parts.append(
                        "Governance compat_bypass dimension shows a violation; "
                        "rollout integrity risk from compat/legacy bypass "
                        "reintroduction."
                    )

        if not any_signal:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "No rollout maturity signals available (acceptance gate, "
                    "readiness gate, and governance report all unavailable)."
                ),
                signal_source=signal_source,
            )

        if at_risk:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.at_risk,
                risk_description=" | ".join(risk_parts) if risk_parts else (
                    "Rollout maturity at risk (unspecified signal)."
                ),
                evidence=evidence,
                signal_source=signal_source,
            )
        return DimensionStrategyResult(
            dimension=dimension,
            status=DimensionStrategyStatus.on_track,
            risk_description="",
            evidence=evidence,
            signal_source=signal_source,
        )

    def _evaluate_regression_pressure(
        self,
        governance_report: Optional[Any],
    ) -> DimensionStrategyResult:
        """Evaluate the accumulated regression pressure strategy dimension.

        Risk signals:
        * Governance report has violations (accumulated regression count > 0).
        * Governance report has unknown dimensions (unresolved signal gaps
          contribute to regression pressure).
        """
        dimension = StrategyDimension.regression_pressure
        signal_source = "core.delegated_flow_post_graduation_governance"

        if governance_report is None:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "Governance report unavailable; cannot assess accumulated "
                    "regression pressure."
                ),
                signal_source=signal_source,
            )

        evidence: Dict[str, Any] = {}
        if hasattr(governance_report, "to_dict"):
            try:
                evidence = governance_report.to_dict()
            except Exception:  # noqa: BLE001
                pass

        violations = getattr(governance_report, "violations", None)
        if violations is None:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "Governance report violations field is absent; cannot "
                    "assess accumulated regression pressure."
                ),
                evidence=evidence,
                signal_source=signal_source,
            )

        violation_count = len(violations) if isinstance(violations, list) else 0

        # Unknown dimensions also contribute to regression pressure
        unknown_dims: List[str] = []
        dims = getattr(governance_report, "dimensions", {})
        for dim_key, dim_result in (dims.items() if isinstance(dims, dict) else []):
            status_val = (
                dim_result.status.value
                if hasattr(dim_result, "status") and hasattr(dim_result.status, "value")
                else str(getattr(dim_result, "status", ""))
            )
            if status_val == "unknown":
                unknown_dims.append(dim_key)

        if violation_count == 0 and not unknown_dims:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.on_track,
                risk_description="",
                evidence=evidence,
                signal_source=signal_source,
            )

        risk_parts: List[str] = []
        if violation_count > 0:
            risk_parts.append(
                f"Governance report shows {violation_count} active "
                f"violation(s); accumulated regression pressure requires "
                "roadmap-level remediation."
            )
        if unknown_dims:
            risk_parts.append(
                f"Governance dimensions {unknown_dims} have unknown status; "
                "unresolved signal gaps contribute to regression pressure."
            )

        return DimensionStrategyResult(
            dimension=dimension,
            status=DimensionStrategyStatus.at_risk,
            risk_description=" | ".join(risk_parts),
            evidence=evidence,
            signal_source=signal_source,
        )

    def _evaluate_cross_subsystem_coupling(
        self,
        governance_report: Optional[Any],
    ) -> DimensionStrategyResult:
        """Evaluate the cross-subsystem evolution coupling risk dimension.

        Risk signals:
        * Multiple governance dimensions show violations simultaneously
          (coupling: one root cause affects several subsystems).
        * FlowAwareResultConvergence reports quarantined results (coupling
          between result convergence and truth ownership).
        * FlowContinuityCoordinator reports replay contract gaps (coupling
          between continuity and execution path).
        * CompatLegacyPathBlockingCanonicalization reports active bypass
          (coupling risk: compat leakage can silently affect multiple
          subsystems).
        """
        dimension = StrategyDimension.cross_subsystem_coupling
        signal_source = (
            "core.delegated_flow_post_graduation_governance + "
            "core.flow_aware_result_convergence + "
            "core.flow_continuity_coordinator + "
            "core.compat_legacy_path_blocking_canonicalization"
        )

        at_risk = False
        risk_parts: List[str] = []
        evidence: Dict[str, Any] = {}
        any_signal = False

        # Count multi-dimension violations in governance report
        if governance_report is not None:
            any_signal = True
            violations = getattr(governance_report, "violations", [])
            violation_count = len(violations) if isinstance(violations, list) else 0
            if violation_count >= 2:
                at_risk = True
                risk_parts.append(
                    f"{violation_count} simultaneous governance violations "
                    "indicate cross-subsystem coupling risk: a single root "
                    "cause is affecting multiple canonical dimensions."
                )
            if hasattr(governance_report, "to_dict"):
                try:
                    evidence["governance_report"] = governance_report.to_dict()
                except Exception:  # noqa: BLE001
                    pass

        # Check result convergence for quarantined results
        convergence_obj = _get_result_convergence()
        if convergence_obj is not None:
            any_signal = True
            try:
                if hasattr(convergence_obj, "has_quarantined_results") and bool(
                    convergence_obj.has_quarantined_results()
                ):
                    at_risk = True
                    risk_parts.append(
                        "FlowAwareResultConvergence reports quarantined "
                        "results; cross-subsystem result/truth coupling risk."
                    )
            except Exception:  # noqa: BLE001
                pass

        # Check continuity coordinator for replay contract gaps
        continuity_obj = _get_continuity_coordinator()
        if continuity_obj is not None:
            any_signal = True
            try:
                if hasattr(continuity_obj, "has_replay_contract_gap") and bool(
                    continuity_obj.has_replay_contract_gap()
                ):
                    at_risk = True
                    risk_parts.append(
                        "FlowContinuityCoordinator reports a replay contract "
                        "gap; continuity/execution coupling risk."
                    )
            except Exception:  # noqa: BLE001
                pass

        # Check compat blocking for active bypass
        compat_obj = _get_compat_blocking()
        if compat_obj is not None:
            any_signal = True
            try:
                if hasattr(compat_obj, "has_active_bypass") and bool(
                    compat_obj.has_active_bypass()
                ):
                    at_risk = True
                    risk_parts.append(
                        "CompatLegacyPathBlockingCanonicalization reports an "
                        "active bypass; compat leakage can affect multiple "
                        "subsystems (cross-subsystem coupling risk)."
                    )
            except Exception:  # noqa: BLE001
                pass

        if not any_signal:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.unknown,
                risk_description=(
                    "No cross-subsystem coupling signals available (governance "
                    "report, result convergence, continuity coordinator, and "
                    "compat blocking all unavailable)."
                ),
                signal_source=signal_source,
            )

        if at_risk:
            return DimensionStrategyResult(
                dimension=dimension,
                status=DimensionStrategyStatus.at_risk,
                risk_description=" | ".join(risk_parts) if risk_parts else (
                    "Cross-subsystem coupling risk detected (unspecified signal)."
                ),
                evidence=evidence,
                signal_source=signal_source,
            )
        return DimensionStrategyResult(
            dimension=dimension,
            status=DimensionStrategyStatus.on_track,
            risk_description="",
            evidence=evidence,
            signal_source=signal_source,
        )

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(
        dimensions: Dict[str, DimensionStrategyResult],
    ) -> StrategyVerdict:
        """Derive the overall strategy verdict from per-dimension results.

        Priority order (first matching rule wins):

        1. Any dimension ``unknown`` → ``strategy_unknown_due_to_missing_program_signal``
        2. ``contract_stability`` at_risk → ``strategy_risk_due_to_contract_instability``
        3. ``governance_trend`` or ``regression_pressure`` at_risk →
           ``strategy_risk_due_to_governance_regression_trend``
        4. ``rollout_maturity`` at_risk → ``strategy_risk_due_to_rollout_maturity_gap``
        5. ``cross_subsystem_coupling`` at_risk → ``strategy_risk_due_to_cross_subsystem_drift``
        6. All on_track → ``strategy_on_track``
        """
        dim_statuses: Dict[str, str] = {
            k: v.status.value for k, v in dimensions.items()
        }

        # Rule 1: any unknown → unknown verdict
        if DimensionStrategyStatus.unknown.value in dim_statuses.values():
            return StrategyVerdict.strategy_unknown_due_to_missing_program_signal

        # Rule 2: contract_stability at_risk
        contract_status = dim_statuses.get(
            StrategyDimension.contract_stability.value
        )
        if contract_status == DimensionStrategyStatus.at_risk.value:
            return StrategyVerdict.strategy_risk_due_to_contract_instability

        # Rule 3: governance_trend or regression_pressure at_risk
        gov_trend_status = dim_statuses.get(
            StrategyDimension.governance_trend.value
        )
        regression_status = dim_statuses.get(
            StrategyDimension.regression_pressure.value
        )
        if (
            gov_trend_status == DimensionStrategyStatus.at_risk.value
            or regression_status == DimensionStrategyStatus.at_risk.value
        ):
            return StrategyVerdict.strategy_risk_due_to_governance_regression_trend

        # Rule 4: rollout_maturity at_risk
        rollout_status = dim_statuses.get(
            StrategyDimension.rollout_maturity.value
        )
        if rollout_status == DimensionStrategyStatus.at_risk.value:
            return StrategyVerdict.strategy_risk_due_to_rollout_maturity_gap

        # Rule 5: cross_subsystem_coupling at_risk
        coupling_status = dim_statuses.get(
            StrategyDimension.cross_subsystem_coupling.value
        )
        if coupling_status == DimensionStrategyStatus.at_risk.value:
            return StrategyVerdict.strategy_risk_due_to_cross_subsystem_drift

        # Rule 6: all on_track
        return StrategyVerdict.strategy_on_track

    @staticmethod
    def _collect_risks(
        dimensions: Dict[str, DimensionStrategyResult],
    ) -> List[Dict[str, str]]:
        """Collect risk entries for all non-on_track dimensions."""
        risks: List[Dict[str, str]] = []
        for dim_key, dim_result in dimensions.items():
            if dim_result.status != DimensionStrategyStatus.on_track:
                risks.append(
                    {
                        "dimension": dim_key,
                        "status": dim_result.status.value,
                        "risk_description": dim_result.risk_description,
                    }
                )
        return risks

    @staticmethod
    def _build_summary(
        verdict: StrategyVerdict,
        risks: List[Dict[str, str]],
    ) -> str:
        """Build a one-line human-readable strategy summary."""
        if verdict == StrategyVerdict.strategy_on_track:
            return (
                "Delegated canonical path STRATEGY ON TRACK: all five "
                "strategy dimensions are on-track for program evolution."
            )
        risk_dims = [r["dimension"] for r in risks]
        return (
            f"Delegated canonical path STRATEGY AT RISK: "
            f"verdict={verdict.value}, "
            f"risks=[{', '.join(risk_dims)}]."
        )


# ---------------------------------------------------------------------------
# Process-global singleton
# ---------------------------------------------------------------------------

_strategy_evaluator: Optional[DelegatedFlowStrategyEvaluator] = None


def get_strategy_evaluator() -> DelegatedFlowStrategyEvaluator:
    """Return the process-global :class:`DelegatedFlowStrategyEvaluator`
    singleton, creating it on first call.

    Thread safety
    -------------
    Concurrent first calls may create multiple instances; the last writer
    wins.  This is acceptable because the evaluator is stateless and
    idempotent.
    """
    global _strategy_evaluator
    if _strategy_evaluator is None:
        _strategy_evaluator = DelegatedFlowStrategyEvaluator()
    return _strategy_evaluator


def reset_strategy_evaluator() -> None:
    """Reset the process-global singleton (for test isolation)."""
    global _strategy_evaluator
    _strategy_evaluator = None


def evaluate_delegated_flow_strategy() -> DelegatedFlowStrategyReport:
    """Evaluate delegated canonical path program strategy using the global
    evaluator.

    Convenience wrapper for
    :meth:`DelegatedFlowStrategyEvaluator.evaluate`.

    Returns
    -------
    DelegatedFlowStrategyReport
    """
    return get_strategy_evaluator().evaluate()
