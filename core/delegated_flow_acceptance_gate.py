#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_acceptance_gate.py
=======================================
PR-10V2 (post-533 dual-repo runtime host unification track):
Delegated Flow Final Acceptance / Graduation Gate.

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

However, a readiness gate alone does not constitute a *final acceptance*
judgment.  Readiness answers "are all subsystems nominally ready?"; acceptance
answers "is there sufficient cross-artifact evidence to formally graduate this
delegated canonical path into a higher-trust rollout tier?"  Without a
dedicated acceptance gate:

* Graduation decisions remain informal even when readiness passes.
* Evidence gaps (missing replay records, unresolved truth contracts, absent
  operator visibility confirmations) are not formally surfaced as acceptance
  blockers.
* Audit trails lack a structured acceptance artifact that downstream release
  enforcement, rollout tightening, and default-on promotion can reference.

This module closes that gap by establishing the **Delegated Flow Final
Acceptance / Graduation Gate** — the evidence-backed evaluator and
authoritative acceptance verdict layer for whether the delegated canonical
path can be formally graduated into a higher-trust rollout tier.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  DELEGATED FLOW FINAL ACCEPTANCE / GRADUATION GATE  (layer 12)     │
    │                                                                     │
    │  Evaluates (read-only) across six acceptance dimensions:           │
    │    • continuity_replay_evidence  — FlowContinuityCoordinator       │
    │    • truth_ownership_evidence    — FlowLevelTruthOwnership         │
    │    • result_convergence_evidence — FlowAwareResultConvergence      │
    │    • operator_visibility_evidence— FlowLevelOperatorSurface        │
    │    • compat_bypass_evidence      — CompatLegacyPathBlocking        │
    │    • readiness_prerequisite      — DelegatedFlowReadinessGate      │
    │                                                                     │
    │  Acceptance verdicts:                                              │
    │    • accepted_for_graduation                                       │
    │    • rejected_due_to_missing_evidence                              │
    │    • rejected_due_to_truth_contract_gap                            │
    │    • rejected_due_to_result_contract_gap                           │
    │    • rejected_due_to_operator_visibility_gap                       │
    │    • rejected_due_to_compat_bypass_risk                            │
    │    • acceptance_unknown_due_to_incomplete_signals                  │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — the gate reads from existing runtime modules and
   the readiness gate; it never mutates canonical state.
3. **Fail-conservative** — when a dimension signal is unavailable the gate
   assigns ``unknown`` status for that dimension and, if any critical
   dimension is unknown, the overall verdict is
   ``acceptance_unknown_due_to_incomplete_signals``.
4. **Operator-visible evidence gaps** — every ``rejected_*`` or ``unknown``
   dimension carries a human-readable ``gap_description`` and a structured
   ``evidence`` dict so operators, auditors, and release owners can see
   exactly why acceptance was denied or deferred.
5. **Stable artifacts** — all data classes are fully serialisable
   (``to_dict`` / ``to_json``) so they can be persisted, diffed, and
   consumed by release pipelines.
6. **Readiness as prerequisite** — the readiness gate verdict (PR-9V2) is
   evaluated as the ``readiness_prerequisite`` dimension; a non-ready
   verdict is an immediate acceptance blocker.

Public API
----------
Authority sentinels::

    DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY
    DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL

Policy sentinels::

    ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY
    ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY
    ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY
    ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY
    ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY
    ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY
    READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY
    ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY

Enumerations::

    AcceptanceDimension
    DimensionEvidenceStatus
    DelegatedFlowAcceptanceVerdict

Data classes::

    DimensionEvidenceResult
    DelegatedFlowAcceptanceReport

Class::

    DelegatedFlowAcceptanceGate

Helpers::

    evaluate_delegated_flow_acceptance() -> DelegatedFlowAcceptanceReport
    get_acceptance_gate()  -> DelegatedFlowAcceptanceGate
    reset_acceptance_gate() -> None  # testing only
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DelegatedFlowAcceptanceGate")

_POLICY_EXCERPT_LEN: int = 80
"""Maximum characters of a policy sentinel to embed in a gap description."""


def _policy_excerpt(policy: str) -> str:
    """Return the first ``_POLICY_EXCERPT_LEN`` characters of *policy* with an
    ellipsis appended when truncated."""
    if len(policy) <= _POLICY_EXCERPT_LEN:
        return policy
    return policy[:_POLICY_EXCERPT_LEN] + "…"


__all__ = [
    # Authority sentinels
    "DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY",
    "DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL",
    # Policy sentinels
    "ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY",
    "ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY",
    "ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY",
    "ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY",
    "ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY",
    "ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY",
    "READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY",
    "ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY",
    # Enumerations
    "AcceptanceDimension",
    "DimensionEvidenceStatus",
    "DelegatedFlowAcceptanceVerdict",
    # Data classes
    "DimensionEvidenceResult",
    "DelegatedFlowAcceptanceReport",
    # Class
    "DelegatedFlowAcceptanceGate",
    # Helpers
    "evaluate_delegated_flow_acceptance",
    "get_acceptance_gate",
    "reset_acceptance_gate",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY: str = (
    "DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY::"
    "core.delegated_flow_acceptance_gate::PR10V2::"
    "delegated-flow-final-acceptance-graduation-gate::"
    "evidence-backed-acceptance-judgment-for-delegated-canonical-path"
)
"""Sentinel: this module is the canonical final acceptance / graduation gate
authority.

Import to assert that a release pipeline, operator console, or rollout
controller is reading the acceptance verdict from the correct canonical gate
rather than from individual sub-system state or the readiness gate alone."""

DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL: str = (
    "DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL::"
    "package=PR10V2::profile=delegated-flow-acceptance-gate-v1::"
    "module=core.delegated_flow_acceptance_gate"
)
"""Package sentinel for PR-10V2."""

ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY: str = (
    "POLICY::ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_V1: "
    "DelegatedFlowAcceptanceGate.evaluate() is the sole authoritative entry "
    "point for determining whether the delegated canonical path is formally "
    "accepted for graduation.  Acceptance verdicts MUST be based on "
    "cross-artifact evidence across all six acceptance dimensions.  Release "
    "pipelines and rollout controllers MUST NOT substitute informal judgment "
    "or partial readiness signals for the acceptance gate verdict."
)
"""Policy: the acceptance gate is the evidence-backed judgment entry point."""

ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::ACCEPTANCE_GATE_IS_PROJECTION_ONLY_V1: "
    "DelegatedFlowAcceptanceGate reads from existing runtime modules and the "
    "PR-9V2 readiness gate.  It MUST NOT mutate canonical state, sub-system "
    "registries, or readiness/truth/convergence/operator/compat module state.  "
    "It is a read-only projection over the current system evidence."
)
"""Policy: the acceptance gate never mutates any sub-system state."""

ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY: str = (
    "POLICY::ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_V1: "
    "When any acceptance dimension signal is unavailable or its evidence is "
    "absent, the gate MUST assign ``unknown`` status for that dimension.  If "
    "any dimension is ``unknown`` the overall verdict MUST be "
    "``acceptance_unknown_due_to_incomplete_signals``.  The gate MUST NOT "
    "infer acceptance from partial evidence."
)
"""Policy: fail-conservative when evidence is missing."""

ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY: str = (
    "POLICY::ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_V1: "
    "Every rejected or unknown acceptance dimension MUST carry a non-empty "
    "gap_description and structured evidence dict so that operators, auditors, "
    "and release owners can inspect why acceptance was denied or deferred.  "
    "Opaque rejection without evidence reference is not permitted."
)
"""Policy: every evidence gap must be operator-visible with structured detail."""

ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY: str = (
    "POLICY::ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_V1: "
    "DelegatedFlowAcceptanceReport is a stable, JSON-serialisable artifact.  "
    "It MUST be persistable, diffable, and consumable by release enforcement, "
    "rollout tightening, default-on promotion, and audit tooling without loss "
    "of information."
)
"""Policy: acceptance reports are stable, serialisable artifacts."""

ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY: str = (
    "POLICY::ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_V1: "
    "Formal graduation requires all six acceptance dimensions to produce "
    "``accepted`` status.  A single ``rejected`` or ``unknown`` dimension "
    "is sufficient to block graduation.  There are no optional dimensions."
)
"""Policy: all six acceptance dimensions must pass for graduation."""

READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY: str = (
    "POLICY::READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_V1: "
    "The PR-9V2 readiness gate verdict is evaluated as the "
    "``readiness_prerequisite`` acceptance dimension.  A non-ready readiness "
    "verdict is an immediate graduation blocker regardless of the status of "
    "other evidence dimensions.  Acceptance MUST NOT bypass readiness."
)
"""Policy: readiness gate verdict is a prerequisite acceptance dimension."""

ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY: str = (
    "POLICY::ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_V1: "
    "Each acceptance dimension evaluation MUST reference its canonical "
    "evidence source module (continuity coordinator, truth alignment snapshot, "
    "convergence snapshot, operator surface, compat blocking snapshot, "
    "readiness gate report).  Evidence references enable downstream audit "
    "tooling to trace acceptance verdicts back to authoritative artifacts."
)
"""Policy: acceptance must reference canonical evidence sources for traceability."""


# ---------------------------------------------------------------------------
# AcceptanceDimension
# ---------------------------------------------------------------------------


class AcceptanceDimension(str, Enum):
    """The six canonical acceptance evidence dimensions.

    Values
    ------
    continuity_replay_evidence
        Evidence from :class:`core.flow_continuity_coordinator.FlowContinuityCoordinator`
        that continuity / replay artifacts exist and are non-trivially populated.

    truth_ownership_evidence
        Evidence from :class:`core.flow_level_truth_ownership` that truth
        alignment between Android and V2 canonical has a defined contract with
        no unresolved gaps.

    result_convergence_evidence
        Evidence from :class:`core.flow_aware_result_convergence` that result
        convergence has processed decisions with no quarantined or unresolved
        gaps that would block graduation.

    operator_visibility_evidence
        Evidence from :class:`core.flow_level_operator_surface` that operator
        visibility is confirmed across execution events and flow projections.

    compat_bypass_evidence
        Evidence from :class:`core.compat_legacy_path_blocking_canonicalization`
        that no unresolved compat/legacy bypass risk is present.

    readiness_prerequisite
        The PR-9V2 :class:`core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate`
        verdict, consumed as a prerequisite acceptance dimension.
    """

    continuity_replay_evidence = "continuity_replay_evidence"
    truth_ownership_evidence = "truth_ownership_evidence"
    result_convergence_evidence = "result_convergence_evidence"
    operator_visibility_evidence = "operator_visibility_evidence"
    compat_bypass_evidence = "compat_bypass_evidence"
    readiness_prerequisite = "readiness_prerequisite"

    @classmethod
    def from_string(cls, value: str) -> "AcceptanceDimension":
        """Return the member matching *value*, defaulting to
        ``continuity_replay_evidence`` when unrecognised."""
        if not isinstance(value, str):
            return cls.continuity_replay_evidence
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.continuity_replay_evidence

    @classmethod
    def all_dimensions(cls) -> List["AcceptanceDimension"]:
        """Return all six dimensions in canonical evaluation order."""
        return [
            cls.continuity_replay_evidence,
            cls.truth_ownership_evidence,
            cls.result_convergence_evidence,
            cls.operator_visibility_evidence,
            cls.compat_bypass_evidence,
            cls.readiness_prerequisite,
        ]


# ---------------------------------------------------------------------------
# DimensionEvidenceStatus
# ---------------------------------------------------------------------------


class DimensionEvidenceStatus(str, Enum):
    """Per-dimension evidence status produced by the acceptance gate.

    Values
    ------
    accepted
        Sufficient evidence exists for this dimension; it does not block
        graduation.

    rejected
        Evidence is present but reveals a gap or contract failure that
        blocks graduation.

    unknown
        The evidence signal for this dimension is absent or unavailable.
        Treated as a graduation blocker per fail-conservative policy.
    """

    accepted = "accepted"
    rejected = "rejected"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "DimensionEvidenceStatus":
        """Return the member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# DelegatedFlowAcceptanceVerdict
# ---------------------------------------------------------------------------


class DelegatedFlowAcceptanceVerdict(str, Enum):
    """Overall acceptance / graduation verdict for the delegated canonical path.

    Values
    ------
    accepted_for_graduation
        All six acceptance dimensions produced ``accepted`` status.  The
        delegated canonical path is formally accepted for graduation into a
        higher-trust rollout tier.

    rejected_due_to_missing_evidence
        One or more dimensions lack sufficient evidence artifacts.  The path
        cannot be accepted without complete evidence.

    rejected_due_to_truth_contract_gap
        The ``truth_ownership_evidence`` dimension revealed an unresolved
        truth contract gap between Android and V2 canonical.

    rejected_due_to_result_contract_gap
        The ``result_convergence_evidence`` dimension revealed quarantined or
        unresolved result contract gaps.

    rejected_due_to_operator_visibility_gap
        The ``operator_visibility_evidence`` dimension revealed that operator
        visibility is insufficient for graduation.

    rejected_due_to_compat_bypass_risk
        The ``compat_bypass_evidence`` dimension revealed an unresolved
        compat/legacy bypass risk that blocks graduation.

    acceptance_unknown_due_to_incomplete_signals
        One or more dimensions have ``unknown`` evidence status because the
        required runtime signal is absent.  The gate cannot safely conclude
        acceptance; treat as not-accepted.
    """

    accepted_for_graduation = "accepted_for_graduation"
    rejected_due_to_missing_evidence = "rejected_due_to_missing_evidence"
    rejected_due_to_truth_contract_gap = "rejected_due_to_truth_contract_gap"
    rejected_due_to_result_contract_gap = "rejected_due_to_result_contract_gap"
    rejected_due_to_operator_visibility_gap = (
        "rejected_due_to_operator_visibility_gap"
    )
    rejected_due_to_compat_bypass_risk = "rejected_due_to_compat_bypass_risk"
    acceptance_unknown_due_to_incomplete_signals = (
        "acceptance_unknown_due_to_incomplete_signals"
    )

    @classmethod
    def from_string(cls, value: str) -> "DelegatedFlowAcceptanceVerdict":
        """Return the member matching *value*, defaulting to
        ``acceptance_unknown_due_to_incomplete_signals``."""
        if not isinstance(value, str):
            return cls.acceptance_unknown_due_to_incomplete_signals
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.acceptance_unknown_due_to_incomplete_signals

    @property
    def is_accepted(self) -> bool:
        """Return ``True`` only when the verdict is ``accepted_for_graduation``."""
        return self == DelegatedFlowAcceptanceVerdict.accepted_for_graduation

    @property
    def is_rejected(self) -> bool:
        """Return ``True`` when the verdict is any ``rejected_*`` variant."""
        return self.value.startswith("rejected_")

    @property
    def is_unknown(self) -> bool:
        """Return ``True`` when the verdict is the incomplete-signals sentinel."""
        return self == DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals


# ---------------------------------------------------------------------------
# DimensionEvidenceResult
# ---------------------------------------------------------------------------


@dataclass
class DimensionEvidenceResult:
    """Per-dimension evidence evaluation result produced by the acceptance gate.

    Fields
    ------
    dimension
        Which of the six canonical acceptance dimensions was evaluated.
    status
        The evidence status for this dimension.
    gap_description
        Human-readable description of the evidence gap (empty when
        ``status`` is ``accepted``).  MUST be non-empty when ``status`` is
        ``rejected`` or ``unknown``.
    signal_source
        Name of the module or snapshot that was consulted as the evidence
        source.
    evidence
        Structured evidence dict for operator / audit inspection.  Contains
        the raw evidence artifacts that drove this dimension evaluation.
    evaluated_at
        Unix timestamp of this dimension evaluation.
    """

    dimension: AcceptanceDimension = AcceptanceDimension.continuity_replay_evidence
    status: DimensionEvidenceStatus = DimensionEvidenceStatus.unknown
    gap_description: str = ""
    signal_source: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "dimension": self.dimension.value,
            "status": self.status.value,
            "gap_description": self.gap_description,
            "signal_source": self.signal_source,
            "evidence": self.evidence,
            "evaluated_at": self.evaluated_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionEvidenceResult":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=AcceptanceDimension.from_string(data.get("dimension", "")),
            status=DimensionEvidenceStatus.from_string(data.get("status", "")),
            gap_description=data.get("gap_description", ""),
            signal_source=data.get("signal_source", ""),
            evidence=data.get("evidence", {}),
            evaluated_at=data.get("evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowAcceptanceReport
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowAcceptanceReport:
    """Full acceptance / graduation report for the delegated canonical path.

    This is the stable, serialisable artifact produced by
    :class:`DelegatedFlowAcceptanceGate`.  It carries:

    * The overall ``verdict`` (one of the seven
      :class:`DelegatedFlowAcceptanceVerdict` values).
    * Per-dimension evidence results for all six dimensions.
    * A human-readable ``summary`` suitable for operator consoles and audit
      logs.
    * Structured evidence gap list for downstream tooling.
    * Metadata (report ID, generated timestamp, gate version).

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    verdict
        Overall acceptance / graduation verdict.
    dimensions
        Mapping from :class:`AcceptanceDimension` value string to the
        corresponding :class:`DimensionEvidenceResult`.
    summary
        Human-readable one-line summary of the overall acceptance state.
    evidence_gaps
        List of dicts with keys ``dimension``, ``status``, and
        ``gap_description`` for all rejected or unknown dimensions.
    is_accepted_for_graduation
        ``True`` when ``verdict`` is ``accepted_for_graduation``.
    gate_version
        Version of the acceptance gate that produced this report.
    generated_at
        Unix timestamp of report generation.
    readiness_report_id
        The ``report_id`` of the :class:`DelegatedFlowReadinessReport` that
        was consumed as the ``readiness_prerequisite`` evidence dimension.
        Empty string when the readiness report was not available.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: DelegatedFlowAcceptanceVerdict = (
        DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals
    )
    dimensions: Dict[str, DimensionEvidenceResult] = field(default_factory=dict)
    summary: str = ""
    evidence_gaps: List[Dict[str, str]] = field(default_factory=list)
    is_accepted_for_graduation: bool = False
    gate_version: str = "1.0"
    generated_at: float = field(default_factory=time.time)
    readiness_report_id: str = ""

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
            "evidence_gaps": self.evidence_gaps,
            "is_accepted_for_graduation": self.is_accepted_for_graduation,
            "gate_version": self.gate_version,
            "generated_at": self.generated_at,
            "readiness_report_id": self.readiness_report_id,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowAcceptanceReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        dimensions: Dict[str, DimensionEvidenceResult] = {}
        for dim_key, dim_data in data.get("dimensions", {}).items():
            dimensions[dim_key] = DimensionEvidenceResult.from_dict(dim_data)
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            verdict=DelegatedFlowAcceptanceVerdict.from_string(
                data.get("verdict", "")
            ),
            dimensions=dimensions,
            summary=data.get("summary", ""),
            evidence_gaps=data.get("evidence_gaps", []),
            is_accepted_for_graduation=data.get("is_accepted_for_graduation", False),
            gate_version=data.get("gate_version", "1.0"),
            generated_at=data.get("generated_at", time.time()),
            readiness_report_id=data.get("readiness_report_id", ""),
        )

    def get_dimension(
        self, dim: AcceptanceDimension
    ) -> Optional[DimensionEvidenceResult]:
        """Return the :class:`DimensionEvidenceResult` for *dim*, or ``None``."""
        return self.dimensions.get(dim.value)


# ---------------------------------------------------------------------------
# Optional integration imports — all guarded to keep the module self-contained
# ---------------------------------------------------------------------------

# FlowContinuityCoordinator (PR-3V2) — continuity_replay_evidence dimension
try:
    from core.flow_continuity_coordinator import (  # type: ignore[import]
        get_flow_continuity_coordinator as _get_continuity_coordinator,
    )
    _CONTINUITY_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _CONTINUITY_AVAILABLE = False
    _get_continuity_coordinator = None  # type: ignore[assignment]

# FlowTruthAlignmentRuntime (PR-5V2) — truth_ownership_evidence dimension
try:
    from core.flow_level_truth_ownership import (  # type: ignore[import]
        build_flow_truth_alignment_snapshot as _build_truth_snapshot,
    )
    _TRUTH_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _TRUTH_AVAILABLE = False
    _build_truth_snapshot = None  # type: ignore[assignment]

# FlowAwareConvergenceCoordinator (PR-6V2) — result_convergence_evidence dimension
try:
    from core.flow_aware_result_convergence import (  # type: ignore[import]
        build_flow_convergence_snapshot as _build_convergence_snapshot,
    )
    _CONVERGENCE_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _CONVERGENCE_AVAILABLE = False
    _build_convergence_snapshot = None  # type: ignore[assignment]

# FlowLevelOperatorSurface (PR-7V2) — operator_visibility_evidence dimension
try:
    from core.flow_level_operator_surface import (  # type: ignore[import]
        get_flow_level_operator_surface as _get_operator_surface,
    )
    _OPERATOR_SURFACE_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _OPERATOR_SURFACE_AVAILABLE = False
    _get_operator_surface = None  # type: ignore[assignment]

# CompatLegacyPathBlockingCanonicalization (PR-8V2) — compat_bypass_evidence dimension
try:
    from core.compat_legacy_path_blocking_canonicalization import (  # type: ignore[import]
        build_blocking_canonicalization_snapshot as _build_blocking_snapshot,
    )
    _COMPAT_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _COMPAT_AVAILABLE = False
    _build_blocking_snapshot = None  # type: ignore[assignment]

# DelegatedFlowReadinessGate (PR-9V2) — readiness_prerequisite dimension
try:
    from core.delegated_flow_readiness_gate import (  # type: ignore[import]
        get_readiness_gate as _get_readiness_gate,
        DelegatedFlowReadinessVerdict as _ReadinessVerdict,
    )
    _READINESS_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _READINESS_AVAILABLE = False
    _get_readiness_gate = None  # type: ignore[assignment]
    _ReadinessVerdict = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# DelegatedFlowAcceptanceGate
# ---------------------------------------------------------------------------


class DelegatedFlowAcceptanceGate:
    """Evidence-backed final acceptance / graduation gate for the delegated
    canonical path.

    This is the canonical evaluator that aggregates six evidence dimension
    signals — including the PR-9V2 readiness gate verdict as a prerequisite —
    and produces a :class:`DelegatedFlowAcceptanceReport`.  It is designed as
    a **read-only projection** — it never mutates any sub-system state.

    Use :func:`get_acceptance_gate` to obtain the process-global singleton.
    Use :func:`reset_acceptance_gate` to reset the singleton (test isolation).

    Usage
    -----
    ::

        from core.delegated_flow_acceptance_gate import (
            get_acceptance_gate,
            DelegatedFlowAcceptanceVerdict,
        )

        report = get_acceptance_gate().evaluate()
        if report.verdict.is_accepted:
            # proceed to graduation / higher-trust rollout
            ...
        else:
            for gap in report.evidence_gaps:
                print(f"[{gap['dimension']}] {gap['gap_description']}")
    """

    GATE_VERSION: str = "1.0"

    def evaluate(self) -> DelegatedFlowAcceptanceReport:
        """Evaluate all six acceptance dimensions and produce a report.

        Returns
        -------
        DelegatedFlowAcceptanceReport
            Full acceptance report with overall verdict, per-dimension evidence
            results, and structured evidence gaps.
        """
        dimensions: Dict[str, DimensionEvidenceResult] = {}

        dim_continuity = self._evaluate_continuity_replay_evidence()
        dim_truth = self._evaluate_truth_ownership_evidence()
        dim_convergence = self._evaluate_result_convergence_evidence()
        dim_operator = self._evaluate_operator_visibility_evidence()
        dim_compat = self._evaluate_compat_bypass_evidence()
        dim_readiness, readiness_report_id = self._evaluate_readiness_prerequisite()

        for dim_result in (
            dim_continuity,
            dim_truth,
            dim_convergence,
            dim_operator,
            dim_compat,
            dim_readiness,
        ):
            dimensions[dim_result.dimension.value] = dim_result

        verdict = self._compute_verdict(dimensions)
        evidence_gaps = self._collect_evidence_gaps(dimensions)
        summary = self._build_summary(verdict, evidence_gaps)
        is_accepted = verdict == DelegatedFlowAcceptanceVerdict.accepted_for_graduation

        report = DelegatedFlowAcceptanceReport(
            verdict=verdict,
            dimensions=dimensions,
            summary=summary,
            evidence_gaps=evidence_gaps,
            is_accepted_for_graduation=is_accepted,
            gate_version=self.GATE_VERSION,
            readiness_report_id=readiness_report_id,
        )
        logger.debug(
            "DelegatedFlowAcceptanceGate.evaluate() → verdict=%s gaps=%d",
            verdict.value,
            len(evidence_gaps),
        )
        return report

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _evaluate_continuity_replay_evidence(self) -> DimensionEvidenceResult:
        """Evaluate the continuity / replay evidence dimension."""
        dimension = AcceptanceDimension.continuity_replay_evidence
        signal_source = "core.flow_continuity_coordinator"

        if not _CONTINUITY_AVAILABLE or _get_continuity_coordinator is None:
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    "FlowContinuityCoordinator (PR-3V2) is not available.  "
                    "Cannot assess continuity / replay evidence.  "
                    "Ensure core.flow_continuity_coordinator is importable."
                ),
                signal_source=signal_source,
            )

        try:
            coordinator = _get_continuity_coordinator()
            snapshot = coordinator.build_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            total_decisions = evidence.get("total_decisions", 0)
            decision_counts = evidence.get("decision_counts", {})
            fail_closed_count = decision_counts.get("fail_closed", 0)

            if total_decisions == 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        "FlowContinuityCoordinator has zero continuity decisions recorded.  "
                        "No continuity / replay evidence artifact exists yet.  "
                        "The delegated path must have processed at least one continuity "
                        "decision before it can be accepted for graduation."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if fail_closed_count > 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.rejected,
                    gap_description=(
                        f"FlowContinuityCoordinator has {fail_closed_count} "
                        f"fail_closed decision(s) out of {total_decisions} total.  "
                        "Unresolved fail_closed continuity gaps block graduation.  "
                        f"Policy: {_policy_excerpt(ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY)}"
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.accepted,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    f"Error evaluating continuity / replay evidence: {exc}.  "
                    "Cannot assess this dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_truth_ownership_evidence(self) -> DimensionEvidenceResult:
        """Evaluate the truth ownership / alignment evidence dimension."""
        dimension = AcceptanceDimension.truth_ownership_evidence
        signal_source = "core.flow_level_truth_ownership"

        if not _TRUTH_AVAILABLE or _build_truth_snapshot is None:
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    "FlowLevelTruthOwnership (PR-5V2) is not available.  "
                    "Cannot assess truth ownership / alignment evidence.  "
                    "Ensure core.flow_level_truth_ownership is importable."
                ),
                signal_source=signal_source,
            )

        try:
            snapshot = _build_truth_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            total_artifacts = evidence.get("total_artifacts", 0)
            decision_counts = evidence.get("decision_counts", {})
            block_count = decision_counts.get(
                "block_due_to_compat_influence", 0
            ) + decision_counts.get("reject_due_to_canonical_terminal", 0)
            conflict_count = decision_counts.get("quarantine_due_to_posture_conflict", 0)

            if total_artifacts == 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        "FlowLevelTruthOwnership has zero truth alignment artifacts.  "
                        "No truth ownership evidence exists yet.  "
                        "The delegated path must have processed at least one truth "
                        "alignment decision before it can be accepted for graduation."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if conflict_count > 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.rejected,
                    gap_description=(
                        f"FlowLevelTruthOwnership has {conflict_count} "
                        "quarantined posture conflict(s).  "
                        "Unresolved truth contract gaps block graduation.  "
                        f"Policy: {_policy_excerpt(READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY)}"
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if block_count > 0:
                # Blocks are expected evidence of canonical enforcement — not a gap
                # unless they dominate (> 50% of all decisions).
                if total_artifacts > 0 and block_count / total_artifacts > 0.5:
                    return DimensionEvidenceResult(
                        dimension=dimension,
                        status=DimensionEvidenceStatus.rejected,
                        gap_description=(
                            f"FlowLevelTruthOwnership: {block_count}/{total_artifacts} "
                            "decisions are blocks, exceeding 50% of all decisions.  "
                            "This indicates a pervasive truth contract gap.  "
                            "Investigate truth alignment before graduation."
                        ),
                        signal_source=signal_source,
                        evidence=evidence,
                    )

            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.accepted,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    f"Error evaluating truth ownership evidence: {exc}.  "
                    "Cannot assess this dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_result_convergence_evidence(self) -> DimensionEvidenceResult:
        """Evaluate the result convergence evidence dimension."""
        dimension = AcceptanceDimension.result_convergence_evidence
        signal_source = "core.flow_aware_result_convergence"

        if not _CONVERGENCE_AVAILABLE or _build_convergence_snapshot is None:
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    "FlowAwareConvergenceCoordinator (PR-6V2) is not available.  "
                    "Cannot assess result convergence evidence.  "
                    "Ensure core.flow_aware_result_convergence is importable."
                ),
                signal_source=signal_source,
            )

        try:
            snapshot = _build_convergence_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            total_decisions = evidence.get("total_artifacts", 0)
            decision_counts = evidence.get("decision_counts", {})
            quarantine_count = decision_counts.get("quarantine", 0)

            if total_decisions == 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        "FlowAwareConvergenceCoordinator has zero convergence decisions.  "
                        "No result convergence evidence exists yet.  "
                        "The delegated path must have processed at least one convergence "
                        "decision before it can be accepted for graduation."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if quarantine_count > 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.rejected,
                    gap_description=(
                        f"FlowAwareConvergenceCoordinator has {quarantine_count} "
                        "quarantined result(s).  "
                        "Quarantined results indicate unresolved result contract gaps "
                        "that block graduation.  "
                        f"Policy: {_policy_excerpt(ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY)}"
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.accepted,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    f"Error evaluating result convergence evidence: {exc}.  "
                    "Cannot assess this dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_operator_visibility_evidence(self) -> DimensionEvidenceResult:
        """Evaluate the operator visibility evidence dimension."""
        dimension = AcceptanceDimension.operator_visibility_evidence
        signal_source = "core.flow_level_operator_surface"

        if not _OPERATOR_SURFACE_AVAILABLE or _get_operator_surface is None:
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    "FlowLevelOperatorSurface (PR-7V2) is not available.  "
                    "Cannot assess operator visibility evidence.  "
                    "Ensure core.flow_level_operator_surface is importable."
                ),
                signal_source=signal_source,
            )

        try:
            surface = _get_operator_surface()
            snapshot = surface.build_snapshot() if hasattr(surface, "build_snapshot") else None
            evidence: Dict[str, Any] = {}
            if snapshot is not None and hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            total_events = evidence.get("total_execution_events", 0)
            total_projections = evidence.get("total_flow_projections", 0)

            if total_events == 0 and total_projections == 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        "FlowLevelOperatorSurface has zero execution events and "
                        "zero flow projections.  "
                        "No operator visibility evidence exists yet.  "
                        "The delegated path must have produced at least one execution "
                        "event or flow projection before it can be accepted for graduation."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            visibility_confirmed = evidence.get("visibility_confirmed", False)
            if not visibility_confirmed and total_events == 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.rejected,
                    gap_description=(
                        "FlowLevelOperatorSurface: operator visibility is not confirmed.  "
                        "No execution events recorded; operators cannot observe delegated "
                        "flow execution state.  "
                        f"Policy: {_policy_excerpt(ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY)}"
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.accepted,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    f"Error evaluating operator visibility evidence: {exc}.  "
                    "Cannot assess this dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_compat_bypass_evidence(self) -> DimensionEvidenceResult:
        """Evaluate the compat / legacy bypass evidence dimension."""
        dimension = AcceptanceDimension.compat_bypass_evidence
        signal_source = "core.compat_legacy_path_blocking_canonicalization"

        if not _COMPAT_AVAILABLE or _build_blocking_snapshot is None:
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    "CompatLegacyPathBlockingCanonicalization (PR-8V2) is not available.  "
                    "Cannot assess compat / legacy bypass evidence.  "
                    "Ensure core.compat_legacy_path_blocking_canonicalization is importable."
                ),
                signal_source=signal_source,
            )

        try:
            snapshot = _build_blocking_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            quarantine_count = evidence.get("quarantine_count", 0)
            block_dispatch_count = evidence.get("block_dispatch_count", 0)
            block_truth_count = evidence.get("block_truth_count", 0)
            total_records = evidence.get("total_records", 0)

            if total_records == 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        "CompatLegacyPathBlockingCanonicalization has zero blocking records.  "
                        "No compat bypass evidence exists yet.  "
                        "The delegated path must have been evaluated by the compat blocking "
                        "gate at least once before it can be accepted for graduation."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if quarantine_count > 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.rejected,
                    gap_description=(
                        f"CompatLegacyPathBlockingCanonicalization has {quarantine_count} "
                        "quarantined compat/legacy influence vector(s).  "
                        "Unresolved quarantined vectors indicate compat bypass risk "
                        "that blocks graduation.  "
                        f"Policy: {_policy_excerpt(ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY)}"
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            active_blocks = block_dispatch_count + block_truth_count
            if active_blocks > 0:
                return DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.rejected,
                    gap_description=(
                        f"CompatLegacyPathBlockingCanonicalization has {active_blocks} "
                        f"active block(s) (dispatch={block_dispatch_count}, "
                        f"truth={block_truth_count}).  "
                        "Active compat/legacy blocks indicate bypass risk vectors "
                        "that have not been fully resolved.  Review before graduation."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.accepted,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionEvidenceResult(
                dimension=dimension,
                status=DimensionEvidenceStatus.unknown,
                gap_description=(
                    f"Error evaluating compat bypass evidence: {exc}.  "
                    "Cannot assess this dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_readiness_prerequisite(
        self,
    ) -> "tuple[DimensionEvidenceResult, str]":
        """Evaluate the PR-9V2 readiness gate verdict as a prerequisite dimension.

        Returns
        -------
        tuple[DimensionEvidenceResult, str]
            The dimension result and the readiness report ID (empty string when
            unavailable).
        """
        dimension = AcceptanceDimension.readiness_prerequisite
        signal_source = "core.delegated_flow_readiness_gate"

        if not _READINESS_AVAILABLE or _get_readiness_gate is None:
            return (
                DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        "DelegatedFlowReadinessGate (PR-9V2) is not available.  "
                        "Cannot assess readiness prerequisite.  "
                        "Ensure core.delegated_flow_readiness_gate is importable.  "
                        f"Policy: {_policy_excerpt(READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY)}"
                    ),
                    signal_source=signal_source,
                ),
                "",
            )

        try:
            readiness_gate = _get_readiness_gate()
            readiness_report = readiness_gate.evaluate()
            evidence: Dict[str, Any] = {}
            if hasattr(readiness_report, "to_dict"):
                evidence = readiness_report.to_dict()

            readiness_report_id: str = getattr(readiness_report, "report_id", "")

            if not readiness_report.is_ready_for_release:
                verdict_value = (
                    readiness_report.verdict.value
                    if hasattr(readiness_report.verdict, "value")
                    else str(readiness_report.verdict)
                )
                return (
                    DimensionEvidenceResult(
                        dimension=dimension,
                        status=DimensionEvidenceStatus.rejected,
                        gap_description=(
                            f"DelegatedFlowReadinessGate verdict is '{verdict_value}' "
                            "(not ready_for_release).  "
                            "Readiness is a prerequisite for acceptance.  "
                            "All readiness gaps must be resolved before graduation.  "
                            f"Policy: {_policy_excerpt(READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY)}"
                        ),
                        signal_source=signal_source,
                        evidence=evidence,
                    ),
                    readiness_report_id,
                )

            return (
                DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.accepted,
                    gap_description="",
                    signal_source=signal_source,
                    evidence=evidence,
                ),
                readiness_report_id,
            )

        except Exception as exc:  # pragma: no cover
            return (
                DimensionEvidenceResult(
                    dimension=dimension,
                    status=DimensionEvidenceStatus.unknown,
                    gap_description=(
                        f"Error evaluating readiness prerequisite: {exc}.  "
                        "Cannot assess this dimension."
                    ),
                    signal_source=signal_source,
                ),
                "",
            )

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(
        dimensions: Dict[str, DimensionEvidenceResult],
    ) -> DelegatedFlowAcceptanceVerdict:
        """Compute the overall acceptance verdict from per-dimension results.

        Priority order
        --------------
        1. Any ``unknown`` dimension → ``acceptance_unknown_due_to_incomplete_signals``.
        2. ``readiness_prerequisite`` rejected → ``rejected_due_to_missing_evidence``
           (readiness failure is treated as missing evidence at the acceptance level).
        3. ``truth_ownership_evidence`` rejected → ``rejected_due_to_truth_contract_gap``.
        4. ``result_convergence_evidence`` rejected → ``rejected_due_to_result_contract_gap``.
        5. ``operator_visibility_evidence`` rejected → ``rejected_due_to_operator_visibility_gap``.
        6. ``compat_bypass_evidence`` rejected → ``rejected_due_to_compat_bypass_risk``.
        7. ``continuity_replay_evidence`` rejected → ``rejected_due_to_missing_evidence``.
        8. All accepted → ``accepted_for_graduation``.
        """
        # 1. Unknown check (fail-conservative)
        for dim_result in dimensions.values():
            if dim_result.status == DimensionEvidenceStatus.unknown:
                return DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals

        # 2–7. Rejected checks in priority order
        readiness_dim = dimensions.get(AcceptanceDimension.readiness_prerequisite.value)
        if readiness_dim and readiness_dim.status == DimensionEvidenceStatus.rejected:
            return DelegatedFlowAcceptanceVerdict.rejected_due_to_missing_evidence

        truth_dim = dimensions.get(AcceptanceDimension.truth_ownership_evidence.value)
        if truth_dim and truth_dim.status == DimensionEvidenceStatus.rejected:
            return DelegatedFlowAcceptanceVerdict.rejected_due_to_truth_contract_gap

        conv_dim = dimensions.get(AcceptanceDimension.result_convergence_evidence.value)
        if conv_dim and conv_dim.status == DimensionEvidenceStatus.rejected:
            return DelegatedFlowAcceptanceVerdict.rejected_due_to_result_contract_gap

        op_dim = dimensions.get(AcceptanceDimension.operator_visibility_evidence.value)
        if op_dim and op_dim.status == DimensionEvidenceStatus.rejected:
            return DelegatedFlowAcceptanceVerdict.rejected_due_to_operator_visibility_gap

        compat_dim = dimensions.get(AcceptanceDimension.compat_bypass_evidence.value)
        if compat_dim and compat_dim.status == DimensionEvidenceStatus.rejected:
            return DelegatedFlowAcceptanceVerdict.rejected_due_to_compat_bypass_risk

        cont_dim = dimensions.get(AcceptanceDimension.continuity_replay_evidence.value)
        if cont_dim and cont_dim.status == DimensionEvidenceStatus.rejected:
            return DelegatedFlowAcceptanceVerdict.rejected_due_to_missing_evidence

        # 8. All accepted
        return DelegatedFlowAcceptanceVerdict.accepted_for_graduation

    @staticmethod
    def _collect_evidence_gaps(
        dimensions: Dict[str, DimensionEvidenceResult],
    ) -> List[Dict[str, str]]:
        """Collect structured evidence gap entries for rejected/unknown dimensions."""
        gaps: List[Dict[str, str]] = []
        for dim_key in [d.value for d in AcceptanceDimension.all_dimensions()]:
            result = dimensions.get(dim_key)
            if result is None:
                continue
            if result.status in (
                DimensionEvidenceStatus.rejected,
                DimensionEvidenceStatus.unknown,
            ):
                gaps.append(
                    {
                        "dimension": dim_key,
                        "status": result.status.value,
                        "gap_description": result.gap_description,
                        "signal_source": result.signal_source,
                    }
                )
        return gaps

    @staticmethod
    def _build_summary(
        verdict: DelegatedFlowAcceptanceVerdict,
        evidence_gaps: List[Dict[str, str]],
    ) -> str:
        """Build a one-line human-readable summary."""
        if verdict == DelegatedFlowAcceptanceVerdict.accepted_for_graduation:
            return (
                "Delegated canonical path ACCEPTED FOR GRADUATION: all six "
                "acceptance evidence dimensions passed."
            )
        gap_dims = [g["dimension"] for g in evidence_gaps]
        return (
            f"Delegated canonical path NOT ACCEPTED: "
            f"verdict={verdict.value}, "
            f"evidence_gaps=[{', '.join(gap_dims)}]."
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_default_acceptance_gate: Optional[DelegatedFlowAcceptanceGate] = None
_DEFAULT_GATE_LOCK = None

try:
    import threading as _threading
    _DEFAULT_GATE_LOCK = _threading.Lock()
except Exception as exc:
    logger.debug("Suppressed: %s", exc)


def get_acceptance_gate() -> DelegatedFlowAcceptanceGate:
    """Return the process-level :class:`DelegatedFlowAcceptanceGate` singleton.

    Creates a new instance on first call.  Thread-safe.
    """
    global _default_acceptance_gate
    if _DEFAULT_GATE_LOCK is not None:
        with _DEFAULT_GATE_LOCK:
            if _default_acceptance_gate is None:
                _default_acceptance_gate = DelegatedFlowAcceptanceGate()
            return _default_acceptance_gate
    if _default_acceptance_gate is None:  # pragma: no cover
        _default_acceptance_gate = DelegatedFlowAcceptanceGate()
    return _default_acceptance_gate


def reset_acceptance_gate() -> None:
    """Reset the process-level singleton (test isolation only)."""
    global _default_acceptance_gate
    if _DEFAULT_GATE_LOCK is not None:
        with _DEFAULT_GATE_LOCK:
            _default_acceptance_gate = None
    else:  # pragma: no cover
        _default_acceptance_gate = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def evaluate_delegated_flow_acceptance() -> DelegatedFlowAcceptanceReport:
    """Evaluate delegated canonical path acceptance using the global gate.

    Convenience wrapper for :meth:`DelegatedFlowAcceptanceGate.evaluate`.

    Returns
    -------
    DelegatedFlowAcceptanceReport
    """
    return get_acceptance_gate().evaluate()
