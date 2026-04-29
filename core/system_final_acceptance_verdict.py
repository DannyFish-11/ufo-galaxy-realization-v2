#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/system_final_acceptance_verdict.py
========================================
PR-17V2 (post-533 dual-repo runtime host unification track):
System-Level Final Acceptance Verdict — fully-operational acceptance
aggregation and formal release/readiness conclusion layer.

Background
----------
The V2 repository has accumulated progressively rigorous readiness and
governance evidence across multiple layers:

* **PR-9V2**  — DelegatedFlowReadinessGate: unified five-dimension
  release-gate verdict for the delegated canonical path.
* **PR-10V2** — DelegatedFlowAcceptanceGate: evidence-backed final
  acceptance / graduation gate.
* **PR-11V2** — DelegatedFlowPostGraduationGovernance: continuous
  compliance evaluation after graduation.
* **PR-12V2** — ProgramStrategy: long-horizon strategic risk / on-track
  evaluation.
* **PR-6V2-EVIDENCE** — V2ReadinessGovernanceEvidenceSurface: reviewable
  evidence aggregation.

Despite this evidence depth, no single module answers the top-level
question that release stakeholders, audit reviewers, and downstream
integrators (e.g. Home Assistant / Matter) actually ask:

    *Is the Galaxy V2 platform as a whole fully-operational and formally
    accepted for production use?*

Without a unified system-level verdict:

1. Separate improvements exist in tests, workflows, runtime, and audit
   layers without a single authoritative conclusion.
2. Whether the system is truly fully-operational still requires human
   reading of scattered materials rather than a single formal statement.
3. There is no unified acceptance checklist / verdict aggregation /
   release-readiness summary that downstream tooling, CI gates, and
   external integrations can consume directly.
4. "Locally valid" evidence cannot be elevated to a "system-level formal
   acceptance verdict".

This module closes that gap by establishing the **System-Level Final
Acceptance Verdict** — the top-level, evidence-backed aggregator that:

1. Consumes verdicts from all five acceptance dimensions:
   - ``runtime_readiness``     (DelegatedFlowReadinessGate, PR-9V2)
   - ``delegated_flow``        (DelegatedFlowAcceptanceGate, PR-10V2)
   - ``governance``            (DelegatedFlowPostGraduationGovernance,
                                PR-11V2)
   - ``multi_device_recovery`` (attached_runtime_recovery_readiness)
   - ``android_participant``   (android_delegated_runtime_audit /
                                android_evaluator_artifact_ingress)

2. Aggregates those five dimension verdicts into a single
   :class:`SystemAcceptanceVerdict`.

3. Produces a dual-format output:
   - **Machine-readable**: JSON-serialisable
     :class:`SystemAcceptanceReport` (consumed by CI, release gates,
     audit pipelines).
   - **Human-readable**: structured plain-text ``summary`` embedded in
     the same artifact (consumed by operator consoles and review UIs).

4. Enforces a fail-conservative policy: any unresolved or missing
   dimension defaults to ``unresolved``, and an unresolved critical
   dimension MUST produce a non-fully-operational verdict.

5. Maintains an ``unresolved_risk_summary`` list so that partial
   evidence states are always surfaced rather than silently optimistic.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  SYSTEM FINAL ACCEPTANCE VERDICT  (this module, PR-17V2)           │
    │                                                                     │
    │  Aggregates five system acceptance dimensions:                     │
    │    1. runtime_readiness      — DelegatedFlowReadinessGate          │
    │    2. delegated_flow         — DelegatedFlowAcceptanceGate         │
    │    3. governance             — PostGraduationGovernance            │
    │    4. multi_device_recovery  — AttachedRuntimeRecoveryReadiness    │
    │    5. android_participant    — AndroidDelegatedRuntimeAudit        │
    │                                                                     │
    │  Produces (dual-format):                                           │
    │    • SystemAcceptanceReport  (machine-readable JSON artifact)      │
    │    • .summary                (human-readable text, same object)    │
    │                                                                     │
    │  System-level verdicts:                                            │
    │    • fully_operational                                             │
    │    • not_fully_operational_pending_dimensions                      │
    │    • not_fully_operational_critical_risk                           │
    │    • acceptance_unknown_insufficient_evidence                      │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — all dimension probes are read-only; no canonical
   state is mutated by this module.
3. **Fail-conservative** — an absent or unavailable dimension signal is
   treated as ``unresolved``, never as a silent pass.
4. **Dual-format output** — both machine-readable JSON and human-readable
   text are produced in a single artifact.
5. **Unresolved-risk explicit** — every unresolved dimension populates the
   ``unresolved_risk_summary`` list; no optimistic suppression.
6. **Stable artifacts** — :class:`SystemAcceptanceReport` is fully
   round-trippable through ``to_dict()`` / ``to_json()`` for persistence,
   diffing, and CI consumption.

Public API
----------
Authority sentinels::

    SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY
    SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL

Policy sentinels::

    SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_POLICY
    SYSTEM_VERDICT_IS_PROJECTION_ONLY_POLICY
    SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_POLICY
    UNRESOLVED_RISK_MUST_BE_EXPLICIT_POLICY
    DUAL_FORMAT_OUTPUT_REQUIRED_POLICY
    ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_POLICY
    CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_POLICY

Enumerations::

    AcceptanceDimensionId
    DimensionStatus
    SystemAcceptanceVerdict

Data classes::

    AcceptanceChecklistItem
    SystemAcceptanceReport

Class::

    SystemFinalAcceptanceEvaluator

Helpers::

    evaluate_system_acceptance() -> SystemAcceptanceReport
    get_system_acceptance_evaluator() -> SystemFinalAcceptanceEvaluator
    reset_system_acceptance_evaluator() -> None  # testing only
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SystemFinalAcceptanceVerdict")

# ---------------------------------------------------------------------------
# Unified taxonomy alignment
# ---------------------------------------------------------------------------
try:
    from core.release_governance_taxonomy import (  # noqa: F401
        TAXONOMY_AUTHORITY as _TAXONOMY_AUTHORITY,
        IssueClassification as _IssueClassification,
        verdict_to_classification as _verdict_to_classification,
        operational_from_verdict as _operational_from_verdict,
    )
    _TAXONOMY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TAXONOMY_AVAILABLE = False

__all__ = [
    # Authority sentinels
    "SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY",
    "SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL",
    # Policy sentinels
    "SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_POLICY",
    "SYSTEM_VERDICT_IS_PROJECTION_ONLY_POLICY",
    "SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_POLICY",
    "UNRESOLVED_RISK_MUST_BE_EXPLICIT_POLICY",
    "DUAL_FORMAT_OUTPUT_REQUIRED_POLICY",
    "ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_POLICY",
    "CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_POLICY",
    # Enumerations
    "AcceptanceDimensionId",
    "DimensionStatus",
    "SystemAcceptanceVerdict",
    # Data classes
    "AcceptanceChecklistItem",
    "SystemAcceptanceReport",
    # Class
    "SystemFinalAcceptanceEvaluator",
    # Helpers
    "evaluate_system_acceptance",
    "get_system_acceptance_evaluator",
    "reset_system_acceptance_evaluator",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY: str = (
    "SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY::"
    "core.system_final_acceptance_verdict::PR17V2::"
    "system-level-final-acceptance-verdict::"
    "fully-operational-aggregation-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical system-level acceptance verdict
authority for the Galaxy V2 platform.

Import to assert that a release pipeline, audit reviewer, or external
integrator (e.g. Home Assistant / Matter bridge) is reading the
fully-operational judgment from the correct canonical aggregator rather
than from individual sub-system readiness states."""

SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL: str = (
    "SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL::"
    "package=PR17V2::profile=system-final-acceptance-verdict-v1::"
    "module=core.system_final_acceptance_verdict"
)
"""Package sentinel for PR-17V2."""

SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_POLICY: str = (
    "POLICY::SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_V1: "
    "SystemFinalAcceptanceEvaluator.evaluate() is the sole authoritative "
    "entry-point for the system-level fully-operational judgment.  Release "
    "pipelines, audit tools, and external integrations MUST consume the "
    "SystemAcceptanceReport produced by this evaluator; they MUST NOT derive "
    "a system-level verdict from individual sub-system readiness states or "
    "informal signals.  PR-17V2, system final acceptance verdict."
)

SYSTEM_VERDICT_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::SYSTEM_VERDICT_IS_PROJECTION_ONLY_V1: "
    "The system acceptance evaluator is a read-only projection layer.  It "
    "consumes verdicts from the five canonical acceptance dimension probes "
    "without mutating any canonical state, runtime, or sub-system decision "
    "history.  PR-17V2, system final acceptance verdict."
)

SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_POLICY: str = (
    "POLICY::SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_V1: "
    "When a dimension signal is unavailable (module not importable, probe "
    "raises, or sub-system returns no evidence), the evaluator MUST record "
    "DimensionStatus.unresolved for that dimension and MUST NOT produce a "
    "fully_operational verdict.  Silence is NOT acceptance.  "
    "PR-17V2, system final acceptance verdict."
)

UNRESOLVED_RISK_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::UNRESOLVED_RISK_MUST_BE_EXPLICIT_V1: "
    "Every unresolved dimension MUST populate the unresolved_risk_summary "
    "list in SystemAcceptanceReport with a human-readable description.  "
    "Optimistic suppression of unresolved risks is prohibited; the report "
    "MUST surface all unresolved dimensions so operators and reviewers can "
    "see exactly what is blocking full acceptance.  "
    "PR-17V2, system final acceptance verdict."
)

DUAL_FORMAT_OUTPUT_REQUIRED_POLICY: str = (
    "POLICY::DUAL_FORMAT_OUTPUT_REQUIRED_V1: "
    "SystemAcceptanceReport MUST provide both a machine-readable JSON form "
    "(via to_dict() / to_json()) and a human-readable text summary (via the "
    ".summary field).  Both forms MUST be derived from the same underlying "
    "evidence and MUST be consistent.  "
    "PR-17V2, system final acceptance verdict."
)

ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_POLICY: str = (
    "POLICY::ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_V1: "
    "A fully_operational verdict REQUIRES all six system acceptance dimensions "
    "(runtime_readiness, delegated_flow, governance, multi_device_recovery, "
    "android_participant, recovery_truth_surface) to have "
    "DimensionStatus.accepted status.  Any dimension that is pending or "
    "unresolved MUST prevent the overall verdict from reaching "
    "fully_operational.  "
    "PR-17V2, system final acceptance verdict."
)

CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_POLICY: str = (
    "POLICY::CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_V1: "
    "All five system acceptance dimensions are critical by definition.  An "
    "unresolved or missing signal in any single dimension MUST produce a "
    "non-fully_operational verdict.  No partial acceptance variant exists "
    "that allows a system-level fully_operational claim with unresolved "
    "critical dimensions.  "
    "PR-17V2, system final acceptance verdict."
)


# ---------------------------------------------------------------------------
# AcceptanceDimensionId
# ---------------------------------------------------------------------------


class AcceptanceDimensionId(str, Enum):
    """The six canonical system acceptance dimensions.

    Values
    ------
    runtime_readiness
        The delegated canonical path runtime readiness gate verdict
        (DelegatedFlowReadinessGate, PR-9V2).  Answers: are all five
        flow-level readiness dimensions (continuity, truth, convergence,
        operator surface, compat) ready for release?

    delegated_flow
        The final delegated-flow acceptance / graduation gate verdict
        (DelegatedFlowAcceptanceGate, PR-10V2).  Answers: is there
        sufficient cross-artifact evidence to formally graduate the
        delegated canonical path?

    governance
        The post-graduation governance compliance verdict
        (DelegatedFlowPostGraduationGovernance, PR-11V2).  Answers: does
        the delegated path remain compliant after graduation?

    multi_device_recovery
        Multi-device recovery readiness evidence
        (attached_runtime_recovery_readiness).  Answers: can the platform
        recover across attached runtime sessions and devices?

    android_participant
        Android participant operational evidence
        (android_delegated_runtime_audit / android_evaluator_artifact_ingress).
        Answers: is the Android participant running with honest capability
        declarations and lifecycle governance?

    recovery_truth_surface
        Structured multi-layer recovery truth surface
        (core.recovery_truth_surface, PR-5-TRUTH).  Answers: across the six
        recovery truth dimensions (participant_disconnect_observed,
        reconnect_observed, redispatch_triggered,
        in_flight_task_continuity_preserved, duplicate_dispatch_avoided,
        recovered_state_aligned) and four recovery levels (v2_internal,
        participant_reconnect, task_continuity, authority_state_alignment),
        what is the structured truth state of recovery?  Distinct from
        multi_device_recovery: this dimension surfaces *how* recovery is
        evidenced, not merely whether a readiness snapshot says ready.

    cross_repo_evidence_pipeline
        Canonical cross-repo evidence ingestion pipeline
        (core.canonical_cross_repo_evidence_pipeline, PR-05).  Answers:
        do all five cross-repo evidence source families (real-device
        participant verification, Android evaluator readiness artifacts,
        participant lifecycle truth, task-result runtime, delegated runtime
        audit) converge into a single canonical evidence chain with
        unified authority / freshness / completeness semantics?  This
        dimension is the final-closure gate that ensures cross-repo
        evidence is not merely a loose collection of parallel surfaces but
        a formally unified and consumable pipeline.

    multi_device_canonical_governance
        Formal canonical governance surface for multi-device / delegated
        runtime (core.multi_device_canonical_governance, PR-09).  Answers:
        has multi-device / delegated runtime been formally classified into
        its correct governance tier (default-mainline, conditional, guarded,
        partial, optional, single-device-baseline)?  This dimension enforces
        that the system does not report "fully active multi-device" merely
        because delegated hooks exist, and that the canonical participant
        role (primary / delegated / secondary / observer) and capability
        tier of every multi-device surface are explicitly classified.

    conversation_continuity
        Formal conversation continuity truth after crash / restart / process
        death / partial recovery
        (core.conversation_continuity_truth, PR-12).  Answers: what is the
        authoritative conversation continuity class after a recovery event?
        Distinguishes authoritative_continuity_restored, partial_continuity,
        history_only_restored, state_restored_rebind_required, and
        continuity_lost.  This dimension enforces that the system does not
        conflate "state still visible" or "history readable" with
        "conversation continuity has been authoritatively restored", and
        that crash / restart / process death always yields an honest
        continuity class rather than an optimistic promotion.

    task_continuity
        Formal in-flight task continuity taxonomy after restart / process
        bounce / controller recovery
        (core.inflight_task_continuity_taxonomy, PR-06).  Answers: what is
        the authoritative system-level in-flight task continuity class after
        a recovery event?  Distinguishes authoritative_task_continuity_restored,
        resumable_with_replay_or_reconcile, state_restored_not_resumed,
        history_or_evidence_only, and task_continuity_lost.  This dimension
        enforces that the system does not conflate "task snapshot present",
        "state in registry", or "replay/reconcile initiated" with "in-flight
        task continuity has been authoritatively restored", and that restart /
        recovery / process bounce always yields an honest continuity taxonomy
        class rather than an optimistic promotion.

    human_intervention
        Formal human escalation / operator takeover / manual intervention
        taxonomy (core.human_intervention_taxonomy, PR-08).  Answers: for
        any given operational closure or task completion, was it reached
        autonomously by the system, or did a human operator assist, confirm,
        override, or escalate?  Distinguishes autonomous_closure,
        operator_assisted_closure, human_confirmed_system_incomplete,
        manual_override, and escalation_required.  This dimension enforces
        that the system does not conflate "a human can take over" with "the
        system reached autonomous operational closure", and that any human
        involvement in the closure path is honestly surfaced rather than
        optimistically suppressed.
    """

    runtime_readiness = "runtime_readiness"
    delegated_flow = "delegated_flow"
    governance = "governance"
    multi_device_recovery = "multi_device_recovery"
    android_participant = "android_participant"
    recovery_truth_surface = "recovery_truth_surface"
    cross_repo_evidence_pipeline = "cross_repo_evidence_pipeline"
    multi_device_canonical_governance = "multi_device_canonical_governance"
    conversation_continuity = "conversation_continuity"
    task_continuity = "task_continuity"
    human_intervention = "human_intervention"

    @classmethod
    def from_string(cls, value: str) -> "AcceptanceDimensionId":
        """Return the member matching *value*, defaulting to ``runtime_readiness``."""
        if not isinstance(value, str):
            return cls.runtime_readiness
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.runtime_readiness

    @classmethod
    def all_dimensions(cls) -> List["AcceptanceDimensionId"]:
        """Return all eleven dimensions in canonical evaluation order."""
        return [
            cls.runtime_readiness,
            cls.delegated_flow,
            cls.governance,
            cls.multi_device_recovery,
            cls.android_participant,
            cls.recovery_truth_surface,
            cls.cross_repo_evidence_pipeline,
            cls.multi_device_canonical_governance,
            cls.conversation_continuity,
            cls.task_continuity,
            cls.human_intervention,
        ]


# ---------------------------------------------------------------------------
# DimensionStatus
# ---------------------------------------------------------------------------


class DimensionStatus(str, Enum):
    """Per-dimension acceptance status.

    Values
    ------
    accepted
        The dimension has passed all acceptance checks.  Evidence is
        present, complete, and conclusive.

    pending
        The dimension has partial evidence but has not reached the bar
        required for acceptance.  At least one gap remains.

    unresolved
        The dimension signal is absent, the probe raised an exception, or
        the sub-system module is unavailable.  Treated conservatively as
        a blocking gap.
    """

    accepted = "accepted"
    pending = "pending"
    unresolved = "unresolved"

    @classmethod
    def from_string(cls, value: str) -> "DimensionStatus":
        """Return the member matching *value*, defaulting to ``unresolved``."""
        if not isinstance(value, str):
            return cls.unresolved
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unresolved


# ---------------------------------------------------------------------------
# SystemAcceptanceVerdict
# ---------------------------------------------------------------------------


class SystemAcceptanceVerdict(str, Enum):
    """Top-level system-wide acceptance verdict.

    Values
    ------
    fully_operational
        All five acceptance dimensions have ``accepted`` status.  The
        Galaxy V2 platform is formally accepted as fully-operational.

    not_fully_operational_pending_dimensions
        One or more dimensions are ``pending`` (partial evidence, at
        least one gap remains).  The platform has not yet reached
        fully-operational status but is progressing.

    not_fully_operational_critical_risk
        One or more dimensions are ``unresolved`` (missing signal or
        unavailable sub-system).  The platform cannot be accepted as
        fully-operational due to a critical unresolved gap.

    acceptance_unknown_insufficient_evidence
        The evaluator could not obtain evidence from enough dimensions to
        reach any conclusion.  Treat as not-fully-operational.
    """

    fully_operational = "fully_operational"
    not_fully_operational_pending_dimensions = (
        "not_fully_operational_pending_dimensions"
    )
    not_fully_operational_critical_risk = "not_fully_operational_critical_risk"
    acceptance_unknown_insufficient_evidence = (
        "acceptance_unknown_insufficient_evidence"
    )

    @classmethod
    def from_string(cls, value: str) -> "SystemAcceptanceVerdict":
        """Return the member matching *value*, defaulting to
        ``acceptance_unknown_insufficient_evidence``."""
        if not isinstance(value, str):
            return cls.acceptance_unknown_insufficient_evidence
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.acceptance_unknown_insufficient_evidence

    @property
    def is_fully_operational(self) -> bool:
        """Return ``True`` only when the verdict is ``fully_operational``."""
        return self == SystemAcceptanceVerdict.fully_operational

    @property
    def is_blocked(self) -> bool:
        """Return ``True`` when the verdict signals a blocking gap."""
        return self in (
            SystemAcceptanceVerdict.not_fully_operational_critical_risk,
            SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence,
        )

    @property
    def is_pending(self) -> bool:
        """Return ``True`` when the verdict is the pending-dimensions variant."""
        return self == SystemAcceptanceVerdict.not_fully_operational_pending_dimensions


# ---------------------------------------------------------------------------
# AcceptanceChecklistItem
# ---------------------------------------------------------------------------


@dataclass
class AcceptanceChecklistItem:
    """Single item in the system acceptance checklist.

    Fields
    ------
    dimension
        Which of the five system acceptance dimensions this item covers.
    status
        The acceptance status for this dimension.
    evidence_summary
        Human-readable summary of the evidence for this dimension.
    evidence_linkage
        Dict mapping evidence source names to their key findings (for
        machine-readable audit consumption).
    gap_description
        Human-readable description of the gap when ``status`` is not
        ``accepted``.  MUST be non-empty when status is pending or
        unresolved.
    signal_source
        Name of the module or runtime that was probed for evidence.
    evaluated_at
        Unix timestamp of this dimension evaluation.
    """

    dimension: AcceptanceDimensionId = AcceptanceDimensionId.runtime_readiness
    status: DimensionStatus = DimensionStatus.unresolved
    evidence_summary: str = ""
    evidence_linkage: Dict[str, Any] = field(default_factory=dict)
    gap_description: str = ""
    signal_source: str = ""
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "dimension": self.dimension.value,
            "status": self.status.value,
            "evidence_summary": self.evidence_summary,
            "evidence_linkage": self.evidence_linkage,
            "gap_description": self.gap_description,
            "signal_source": self.signal_source,
            "evaluated_at": self.evaluated_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcceptanceChecklistItem":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=AcceptanceDimensionId.from_string(
                data.get("dimension", "")
            ),
            status=DimensionStatus.from_string(data.get("status", "")),
            evidence_summary=data.get("evidence_summary", ""),
            evidence_linkage=data.get("evidence_linkage", {}),
            gap_description=data.get("gap_description", ""),
            signal_source=data.get("signal_source", ""),
            evaluated_at=data.get("evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# SystemAcceptanceReport
# ---------------------------------------------------------------------------


@dataclass
class SystemAcceptanceReport:
    """Full system-level acceptance report for the Galaxy V2 platform.

    This is the stable, serialisable artifact produced by
    :class:`SystemFinalAcceptanceEvaluator`.  It carries:

    * The overall ``verdict`` (one of the four
      :class:`SystemAcceptanceVerdict` values).
    * Per-dimension checklist items for all five acceptance dimensions.
    * Aggregated ``unresolved_risk_summary`` for every dimension that is
      not ``accepted``.
    * A machine-readable ``evidence_linkage`` dict mapping each dimension
      to its key evidence artefacts.
    * A human-readable ``summary`` for operator consoles and review UIs.
    * Metadata (report ID, generated timestamp, evaluator version).

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    verdict
        Overall system-level acceptance verdict.
    checklist
        Mapping from :class:`AcceptanceDimensionId` value string to the
        corresponding :class:`AcceptanceChecklistItem`.
    unresolved_risk_summary
        List of dicts ``{dimension, risk_description}`` for all
        non-accepted dimensions.
    evidence_linkage
        Aggregated mapping from dimension name to evidence artefacts dict.
    summary
        Human-readable multi-line summary of the system acceptance state.
    is_fully_operational
        ``True`` when ``verdict`` is ``fully_operational``.
    evaluator_version
        Version of the evaluator that produced this report.
    generated_at
        Unix timestamp of report generation.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: SystemAcceptanceVerdict = (
        SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence
    )
    checklist: Dict[str, AcceptanceChecklistItem] = field(default_factory=dict)
    unresolved_risk_summary: List[Dict[str, str]] = field(default_factory=list)
    evidence_linkage: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    is_fully_operational: bool = False
    evaluator_version: str = "1.0"
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation (machine-readable output)."""
        result: Dict[str, Any] = {
            "report_id": self.report_id,
            "verdict": self.verdict.value,
            "checklist": {
                dim_key: item.to_dict()
                for dim_key, item in self.checklist.items()
            },
            "unresolved_risk_summary": self.unresolved_risk_summary,
            "evidence_linkage": self.evidence_linkage,
            "summary": self.summary,
            "is_fully_operational": self.is_fully_operational,
            "evaluator_version": self.evaluator_version,
            "generated_at": self.generated_at,
        }
        if _TAXONOMY_AVAILABLE:
            result["taxonomy_classification"] = _verdict_to_classification(
                self.verdict.value
            ).value
            result["taxonomy_operational_status"] = _operational_from_verdict(
                self.verdict.value
            ).value
            result["taxonomy_alignment"] = "core.release_governance_taxonomy::PR8"
        return result

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemAcceptanceReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        checklist: Dict[str, AcceptanceChecklistItem] = {}
        for dim_key, item_data in data.get("checklist", {}).items():
            checklist[dim_key] = AcceptanceChecklistItem.from_dict(item_data)
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            verdict=SystemAcceptanceVerdict.from_string(
                data.get("verdict", "")
            ),
            checklist=checklist,
            unresolved_risk_summary=data.get("unresolved_risk_summary", []),
            evidence_linkage=data.get("evidence_linkage", {}),
            summary=data.get("summary", ""),
            is_fully_operational=data.get("is_fully_operational", False),
            evaluator_version=data.get("evaluator_version", "1.0"),
            generated_at=data.get("generated_at", time.time()),
        )

    def get_checklist_item(
        self, dim: AcceptanceDimensionId
    ) -> Optional[AcceptanceChecklistItem]:
        """Return the :class:`AcceptanceChecklistItem` for *dim*, or ``None``."""
        return self.checklist.get(dim.value)


# ---------------------------------------------------------------------------
# Optional integration imports — all guarded to keep the module self-contained
# ---------------------------------------------------------------------------

# DelegatedFlowReadinessGate (PR-9V2) — runtime_readiness dimension
try:
    from core.delegated_flow_readiness_gate import (  # type: ignore[import]
        get_readiness_gate as _get_readiness_gate,
        DelegatedFlowReadinessVerdict as _ReadinessVerdict,
    )
    _READINESS_GATE_AVAILABLE = True
except Exception:
    _READINESS_GATE_AVAILABLE = False
    _get_readiness_gate = None  # type: ignore[assignment]
    _ReadinessVerdict = None  # type: ignore[assignment]

# DelegatedFlowAcceptanceGate (PR-10V2) — delegated_flow dimension
try:
    from core.delegated_flow_acceptance_gate import (  # type: ignore[import]
        get_acceptance_gate as _get_acceptance_gate,
        DelegatedFlowAcceptanceVerdict as _AcceptanceVerdict,
    )
    _ACCEPTANCE_GATE_AVAILABLE = True
except Exception:
    _ACCEPTANCE_GATE_AVAILABLE = False
    _get_acceptance_gate = None  # type: ignore[assignment]
    _AcceptanceVerdict = None  # type: ignore[assignment]

# DelegatedFlowPostGraduationGovernance (PR-11V2) — governance dimension
try:
    from core.delegated_flow_post_graduation_governance import (  # type: ignore[import]
        get_governance_evaluator as _get_governance_evaluator,
        GovernanceVerdict as _GovernanceVerdict,
    )
    _GOVERNANCE_AVAILABLE = True
except Exception:
    _GOVERNANCE_AVAILABLE = False
    _get_governance_evaluator = None  # type: ignore[assignment]
    _GovernanceVerdict = None  # type: ignore[assignment]

# AttachedRuntimeRecoveryReadiness — multi_device_recovery dimension
try:
    from core.attached_runtime_recovery_readiness import (  # type: ignore[import]
        build_recovery_readiness_snapshot as _build_recovery_snapshot,
    )
    _RECOVERY_AVAILABLE = True
except Exception:
    _RECOVERY_AVAILABLE = False
    _build_recovery_snapshot = None  # type: ignore[assignment]

# AndroidParticipantEvidenceIngress — android_participant dimension
# Uses a structured file-based evidence contract rather than a direct import
# of the Android-side audit module, allowing evidence to be ingested from
# JSON artifacts produced by the Android participant.
try:
    from core.android_participant_evidence_ingress import (  # type: ignore[import]
        ingest_android_participant_evidence as _ingest_android_evidence,
        AndroidParticipantStatus as _AndroidParticipantStatus,
    )
    _ANDROID_EVIDENCE_INGRESS_AVAILABLE = True
except Exception:
    _ANDROID_EVIDENCE_INGRESS_AVAILABLE = False
    _ingest_android_evidence = None  # type: ignore[assignment]
    _AndroidParticipantStatus = None  # type: ignore[assignment]

# Also try the legacy direct audit recorder import (for backward compat when
# available in the same process — e.g. when running with the full dual-repo
# environment).  Not required; the evidence ingress layer is authoritative.
try:
    from core.android_delegated_runtime_audit import (  # type: ignore[import]
        get_android_delegated_audit_recorder as _get_android_delegated_audit_recorder,
    )
    _ANDROID_AUDIT_AVAILABLE = True
except Exception:
    _ANDROID_AUDIT_AVAILABLE = False
    _get_android_delegated_audit_recorder = None  # type: ignore[assignment]

# DelegatedFlowDecisionHistory (PR-V2-4DH) — layered history evidence for
# the delegated_flow dimension.  Enables fine-grained distinction between
# "structure present" and "runtime closure established".
try:
    from core.delegated_flow_decision_history import (  # type: ignore[import]
        get_decision_history as _get_decision_history,
        HistoryEvidenceStatus as _HistoryEvidenceStatus,
    )
    _DECISION_HISTORY_AVAILABLE = True
except Exception:
    _DECISION_HISTORY_AVAILABLE = False
    _get_decision_history = None  # type: ignore[assignment]
    _HistoryEvidenceStatus = None  # type: ignore[assignment]

# RecoveryTruthSurface (PR-5-TRUTH) — structured multi-layer recovery truth
# surface for the recovery_truth_surface dimension.
try:
    from core.recovery_truth_surface import (  # type: ignore[import]
        build_recovery_truth_report as _build_recovery_truth_report,
        RecoveryTruthStatus as _RecoveryTruthStatus,
    )
    _RECOVERY_TRUTH_SURFACE_AVAILABLE = True
except Exception:
    _RECOVERY_TRUTH_SURFACE_AVAILABLE = False
    _build_recovery_truth_report = None  # type: ignore[assignment]
    _RecoveryTruthStatus = None  # type: ignore[assignment]

# CanonicalCrossRepoEvidencePipeline (PR-05) — unified canonical cross-repo
# evidence ingestion pipeline for the cross_repo_evidence_pipeline dimension.
try:
    from core.canonical_cross_repo_evidence_pipeline import (  # type: ignore[import]
        build_canonical_cross_repo_evidence_report as _build_cross_repo_report,
        PipelineVerdict as _PipelineVerdict,
        CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY as _CROSS_REPO_AUTHORITY,
    )
    _CROSS_REPO_PIPELINE_AVAILABLE = True
except Exception:
    _CROSS_REPO_PIPELINE_AVAILABLE = False
    _build_cross_repo_report = None  # type: ignore[assignment]
    _PipelineVerdict = None  # type: ignore[assignment]
    _CROSS_REPO_AUTHORITY = ""

# MultiDeviceCanonicalGovernance (PR-09) — multi-device canonical governance
# dimension.  Probes whether multi-device / delegated runtime has been
# formally classified with correct tiers and evidence-honest verdicts.
try:
    from core.multi_device_canonical_governance import (  # type: ignore[import]
        build_multi_device_governance_report as _build_md_governance_report,
        MultiDeviceGovernanceVerdict as _MDGovernanceVerdict,
    )
    _MD_GOVERNANCE_AVAILABLE = True
except Exception:
    _MD_GOVERNANCE_AVAILABLE = False
    _build_md_governance_report = None  # type: ignore[assignment]
    _MDGovernanceVerdict = None  # type: ignore[assignment]

# ConversationContinuityTruth (PR-12) — conversation continuity truth
# dimension.  Probes whether post-crash / post-restart conversation continuity
# has been formally evaluated and classified rather than optimistically assumed.
try:
    from core.conversation_continuity_truth import (  # type: ignore[import]
        build_conversation_continuity_verdict as _build_conversation_continuity_verdict,
        ConversationContinuityClass as _ConversationContinuityClass,
        ConversationContinuityEvidence as _ConversationContinuityEvidence,
        CONVERSATION_CONTINUITY_TRUTH_AUTHORITY as _CONV_CONTINUITY_AUTHORITY,
    )
    _CONVERSATION_CONTINUITY_AVAILABLE = True
except Exception:
    _CONVERSATION_CONTINUITY_AVAILABLE = False
    _build_conversation_continuity_verdict = None  # type: ignore[assignment]
    _ConversationContinuityClass = None  # type: ignore[assignment]
    _ConversationContinuityEvidence = None  # type: ignore[assignment]
    _CONV_CONTINUITY_AUTHORITY = ""

# InFlightTaskContinuityTaxonomy (PR-06) — in-flight task continuity taxonomy
# dimension.  Probes whether post-restart / post-bounce in-flight task
# continuity has been formally evaluated and classified rather than
# optimistically assumed from snapshot/state presence.
try:
    from core.inflight_task_continuity_taxonomy import (  # type: ignore[import]
        build_task_continuity_verdict as _build_task_continuity_verdict,
        InFlightTaskContinuityClass as _InFlightTaskContinuityClass,
        InFlightTaskContinuityEvidence as _InFlightTaskContinuityEvidence,
        INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY as _TASK_CONTINUITY_AUTHORITY,
    )
    _TASK_CONTINUITY_TAXONOMY_AVAILABLE = True
except Exception:
    _TASK_CONTINUITY_TAXONOMY_AVAILABLE = False
    _build_task_continuity_verdict = None  # type: ignore[assignment]
    _InFlightTaskContinuityClass = None  # type: ignore[assignment]
    _InFlightTaskContinuityEvidence = None  # type: ignore[assignment]
    _TASK_CONTINUITY_AUTHORITY = ""

# HumanInterventionTaxonomy (PR-08) — human escalation / operator takeover /
# manual intervention taxonomy dimension.  Probes whether the formal
# intervention taxonomy is available and correctly produces conservative
# (non-autonomous) verdicts when no explicit autonomous evidence is present.
try:
    from core.human_intervention_taxonomy import (  # type: ignore[import]
        build_human_intervention_verdict as _build_human_intervention_verdict,
        HumanInterventionClass as _HumanInterventionClass,
        HumanInterventionEvidence as _HumanInterventionEvidence,
        HUMAN_INTERVENTION_TAXONOMY_AUTHORITY as _HUMAN_INTERVENTION_AUTHORITY,
    )
    _HUMAN_INTERVENTION_TAXONOMY_AVAILABLE = True
except Exception:
    _HUMAN_INTERVENTION_TAXONOMY_AVAILABLE = False
    _build_human_intervention_verdict = None  # type: ignore[assignment]
    _HumanInterventionClass = None  # type: ignore[assignment]
    _HumanInterventionEvidence = None  # type: ignore[assignment]
    _HUMAN_INTERVENTION_AUTHORITY = ""


# ---------------------------------------------------------------------------
# SystemFinalAcceptanceEvaluator
# ---------------------------------------------------------------------------


class SystemFinalAcceptanceEvaluator:
    """Top-level system acceptance evaluator for the Galaxy V2 platform.

    Aggregates five canonical acceptance dimension signals into a
    :class:`SystemAcceptanceReport` with a dual-format (machine-readable
    JSON + human-readable summary) output.

    Use :func:`get_system_acceptance_evaluator` to obtain the
    process-global singleton.
    Use :func:`reset_system_acceptance_evaluator` for test isolation.

    Usage
    -----
    ::

        from core.system_final_acceptance_verdict import (
            get_system_acceptance_evaluator,
            SystemAcceptanceVerdict,
        )

        report = get_system_acceptance_evaluator().evaluate()
        if report.verdict.is_fully_operational:
            # proceed: platform is formally accepted as fully-operational
            ...
        else:
            for risk in report.unresolved_risk_summary:
                print(f"[{risk['dimension']}] {risk['risk_description']}")
    """

    EVALUATOR_VERSION: str = "1.0"

    def evaluate(self) -> SystemAcceptanceReport:
        """Evaluate all nine acceptance dimensions and produce a report.

        Returns
        -------
        SystemAcceptanceReport
            Full system acceptance report with overall verdict, checklist,
            unresolved risk summary, evidence linkage, and dual-format
            (machine-readable + human-readable) output.
        """
        checklist: Dict[str, AcceptanceChecklistItem] = {}

        item_runtime = self._evaluate_runtime_readiness()
        item_delegated = self._evaluate_delegated_flow()
        item_governance = self._evaluate_governance()
        item_recovery = self._evaluate_multi_device_recovery()
        item_android = self._evaluate_android_participant()
        item_recovery_truth = self._evaluate_recovery_truth_surface()
        item_cross_repo = self._evaluate_cross_repo_evidence_pipeline()
        item_md_governance = self._evaluate_multi_device_canonical_governance()
        item_conv_continuity = self._evaluate_conversation_continuity()
        item_task_continuity = self._evaluate_task_continuity()
        item_human_intervention = self._evaluate_human_intervention()

        for item in (
            item_runtime,
            item_delegated,
            item_governance,
            item_recovery,
            item_android,
            item_recovery_truth,
            item_cross_repo,
            item_md_governance,
            item_conv_continuity,
            item_task_continuity,
            item_human_intervention,
        ):
            checklist[item.dimension.value] = item

        verdict = self._compute_verdict(checklist)
        unresolved_risks = self._collect_unresolved_risks(checklist)
        evidence_linkage = self._build_evidence_linkage(checklist)
        summary = self._build_summary(verdict, checklist, unresolved_risks)
        is_fully_op = verdict == SystemAcceptanceVerdict.fully_operational

        report = SystemAcceptanceReport(
            verdict=verdict,
            checklist=checklist,
            unresolved_risk_summary=unresolved_risks,
            evidence_linkage=evidence_linkage,
            summary=summary,
            is_fully_operational=is_fully_op,
            evaluator_version=self.EVALUATOR_VERSION,
        )
        logger.debug(
            "SystemFinalAcceptanceEvaluator.evaluate() → verdict=%s risks=%d",
            verdict.value,
            len(unresolved_risks),
        )
        return report

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _evaluate_runtime_readiness(self) -> AcceptanceChecklistItem:
        """Probe the DelegatedFlowReadinessGate (PR-9V2)."""
        dimension = AcceptanceDimensionId.runtime_readiness
        signal_source = "core.delegated_flow_readiness_gate"

        if not _READINESS_GATE_AVAILABLE or _get_readiness_gate is None:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary="DelegatedFlowReadinessGate (PR-9V2) unavailable.",
                gap_description=(
                    "core.delegated_flow_readiness_gate is not importable.  "
                    "Cannot assess runtime readiness.  Ensure PR-9V2 is "
                    "deployed and the module is on the Python path."
                ),
                signal_source=signal_source,
            )

        try:
            gate = _get_readiness_gate()
            report = gate.evaluate()
            verdict_value = report.verdict.value if hasattr(report, "verdict") else ""
            is_ready = getattr(report, "is_ready_for_release", False)
            gaps = getattr(report, "gaps", [])

            if is_ready:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary=(
                        f"DelegatedFlowReadinessGate verdict: {verdict_value}.  "
                        f"All five flow-level readiness dimensions passed."
                    ),
                    evidence_linkage={
                        "readiness_gate_verdict": verdict_value,
                        "gap_count": 0,
                    },
                    gap_description="",
                    signal_source=signal_source,
                )
            elif gaps:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.pending,
                    evidence_summary=(
                        f"DelegatedFlowReadinessGate verdict: {verdict_value}.  "
                        f"{len(gaps)} readiness gap(s) remain."
                    ),
                    evidence_linkage={
                        "readiness_gate_verdict": verdict_value,
                        "gap_count": len(gaps),
                        "gaps": gaps,
                    },
                    gap_description=(
                        f"Runtime readiness gate produced {len(gaps)} gap(s): "
                        + "; ".join(
                            g.get("gap_description", str(g)) for g in gaps[:3]
                        )
                    ),
                    signal_source=signal_source,
                )
            else:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        f"DelegatedFlowReadinessGate verdict: {verdict_value}.  "
                        "Not ready and no gap list available."
                    ),
                    evidence_linkage={"readiness_gate_verdict": verdict_value},
                    gap_description=(
                        f"Runtime readiness gate verdict '{verdict_value}' is "
                        "not ready_for_release and provided no gap details.  "
                        "Treat as unresolved."
                    ),
                    signal_source=signal_source,
                )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary="DelegatedFlowReadinessGate probe raised an exception.",
                gap_description=(
                    f"DelegatedFlowReadinessGate raised: {exc!r}.  "
                    "Cannot assess runtime readiness."
                ),
                signal_source=signal_source,
            )

    def _evaluate_delegated_flow(self) -> AcceptanceChecklistItem:
        """Probe the DelegatedFlowAcceptanceGate (PR-10V2) and augment the
        verdict with decision history evidence (PR-V2-4DH).

        This evaluator operates in two layers:

        Layer 1 — Acceptance gate (structural + evidence dimensions)
            Queries DelegatedFlowAcceptanceGate.evaluate() which probes six
            evidence dimensions.  An ``accepted_for_graduation`` result
            immediately yields ``DimensionStatus.accepted``.

        Layer 2 — Decision history (runtime closure evidence)
            Queries DelegatedFlowDecisionHistory.evaluate() to obtain the
            five-tier history evidence status.  This distinguishes between:

            * ``no_history_yet``           → ``unresolved`` (no runs ever)
            * ``insufficient_evidence``    → ``unresolved`` (too few events)
            * ``observed_but_incomplete``  → ``pending``    (some branches)
            * ``observed_and_closed``      → promotes partial gate gaps to
                                             ``pending`` with gate context
            * ``historical_evidence_stale``→ ``unresolved`` (stale history)

        The ``evidence_linkage`` always surfaces both ``structure_present``
        and ``runtime_closure_established`` so audit consumers can
        distinguish structural existence from runtime proof.
        """
        dimension = AcceptanceDimensionId.delegated_flow
        signal_source = "core.delegated_flow_acceptance_gate"

        if not _ACCEPTANCE_GATE_AVAILABLE or _get_acceptance_gate is None:
            # Acceptance gate unavailable — still surface history context.
            h_status_value = "unavailable"
            structure_present = False
            runtime_closure = False
            if _DECISION_HISTORY_AVAILABLE and _get_decision_history is not None:
                try:
                    h_report = _get_decision_history().evaluate()
                    h_status_value = h_report.evidence_status.value
                    structure_present = h_report.structure_present
                    runtime_closure = h_report.runtime_closure_established
                except Exception:
                    pass
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary="DelegatedFlowAcceptanceGate (PR-10V2) unavailable.",
                evidence_linkage={
                    "acceptance_gate_verdict": "unavailable",
                    "history_evidence_status": h_status_value,
                    "structure_present": structure_present,
                    "runtime_closure_established": runtime_closure,
                },
                gap_description=(
                    "core.delegated_flow_acceptance_gate is not importable.  "
                    "Cannot assess delegated-flow acceptance.  Ensure PR-10V2 "
                    "is deployed and the module is on the Python path."
                ),
                signal_source=signal_source,
            )

        try:
            gate = _get_acceptance_gate()
            report = gate.evaluate()
            verdict_value = report.verdict.value if hasattr(report, "verdict") else ""
            is_accepted = getattr(report, "is_accepted_for_graduation", False)
            gaps = getattr(report, "evidence_gaps", [])

            # ------------------------------------------------------------------
            # Layer 2: Collect decision history status (always; used for
            # evidence linkage and fine-grained gap descriptions).
            # ------------------------------------------------------------------
            h_status_value = "unavailable"
            structure_present = False
            runtime_closure = False
            h_gap_description = ""
            if _DECISION_HISTORY_AVAILABLE and _get_decision_history is not None:
                try:
                    h_report = _get_decision_history().evaluate()
                    h_status_value = h_report.evidence_status.value
                    structure_present = h_report.structure_present
                    runtime_closure = h_report.runtime_closure_established
                    h_gap_description = h_report.gap_description
                except Exception:
                    pass

            base_linkage: Dict[str, Any] = {
                "acceptance_gate_verdict": verdict_value,
                "history_evidence_status": h_status_value,
                "structure_present": structure_present,
                "runtime_closure_established": runtime_closure,
            }

            # ------------------------------------------------------------------
            # Fast path: acceptance gate passed → full acceptance
            # ------------------------------------------------------------------
            if is_accepted:
                base_linkage["evidence_gap_count"] = 0
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary=(
                        f"DelegatedFlowAcceptanceGate verdict: {verdict_value}.  "
                        "Delegated canonical path accepted for graduation."
                    ),
                    evidence_linkage=base_linkage,
                    gap_description="",
                    signal_source=signal_source,
                )

            # ------------------------------------------------------------------
            # Non-accepted: history status drives the DimensionStatus so
            # callers can distinguish idle-env gaps from partial/stale/gate gaps.
            # ------------------------------------------------------------------
            base_linkage["evidence_gap_count"] = len(gaps)

            if h_status_value == "no_history_yet":
                dim_status = DimensionStatus.unresolved
                combined_gap = (
                    f"Delegated flow acceptance gate is non-accepted "
                    f"(verdict: {verdict_value!r}) AND no delegated flow has "
                    "ever been triggered in this process.  "
                    "This is an idle-environment evidence gap, not a code failure.  "
                    "History: " + (h_gap_description or "no_history_yet")
                )
            elif h_status_value == "historical_evidence_stale":
                dim_status = DimensionStatus.unresolved
                combined_gap = (
                    f"Delegated flow acceptance gate is non-accepted "
                    f"(verdict: {verdict_value!r}) AND the decision history is "
                    "stale.  Prior run evidence is too old to establish current "
                    "runtime closure.  "
                    "History: " + (h_gap_description or "historical_evidence_stale")
                )
            elif h_status_value == "insufficient_evidence":
                dim_status = DimensionStatus.unresolved
                combined_gap = (
                    f"Delegated flow acceptance gate is non-accepted "
                    f"(verdict: {verdict_value!r}) AND the decision history has "
                    "insufficient events to confirm end-to-end closure.  "
                    "History: " + (h_gap_description or "insufficient_evidence")
                )
            elif h_status_value == "observed_but_incomplete":
                dim_status = DimensionStatus.pending
                combined_gap = (
                    f"Delegated flow acceptance gate is non-accepted "
                    f"(verdict: {verdict_value!r}) AND the decision history shows "
                    "partial run coverage — some branches witnessed but not all.  "
                    "History: " + (h_gap_description or "observed_but_incomplete")
                )
            elif h_status_value == "observed_and_closed":
                # History is closed but gate still non-accepted → gate content
                # gaps are the blocker (not run-history absence).
                if gaps:
                    dim_status = DimensionStatus.pending
                    combined_gap = (
                        f"DelegatedFlowAcceptanceGate produced {len(gaps)} "
                        "evidence gap(s) despite a closed decision history.  "
                        "Gate verdict: " + verdict_value
                    )
                else:
                    dim_status = DimensionStatus.pending
                    combined_gap = (
                        f"Delegated-flow acceptance gate verdict "
                        f"'{verdict_value}' is not accepted_for_graduation.  "
                        "Decision history is closed but gate dimensions "
                        "have not all passed."
                    )
            else:
                # History module unavailable — fall back to gate-only logic.
                if gaps:
                    dim_status = DimensionStatus.pending
                    combined_gap = (
                        f"Delegated-flow acceptance gate produced {len(gaps)} "
                        "evidence gap(s).  "
                        "(Decision history module unavailable.)"
                    )
                else:
                    dim_status = DimensionStatus.unresolved
                    combined_gap = (
                        f"Delegated-flow acceptance gate verdict "
                        f"'{verdict_value}' is not accepted_for_graduation "
                        "and provided no evidence gap details.  "
                        "Treat as unresolved."
                    )

            return AcceptanceChecklistItem(
                dimension=dimension,
                status=dim_status,
                evidence_summary=(
                    f"DelegatedFlowAcceptanceGate verdict: {verdict_value}.  "
                    f"History status: {h_status_value}.  "
                    f"Structure present: {structure_present}.  "
                    f"Runtime closure: {runtime_closure}."
                ),
                evidence_linkage=base_linkage,
                gap_description=combined_gap,
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary="DelegatedFlowAcceptanceGate probe raised an exception.",
                gap_description=(
                    f"DelegatedFlowAcceptanceGate raised: {exc!r}.  "
                    "Cannot assess delegated-flow acceptance."
                ),
                signal_source=signal_source,
            )

    def _evaluate_governance(self) -> AcceptanceChecklistItem:
        """Probe the DelegatedFlowPostGraduationGovernance (PR-11V2)."""
        dimension = AcceptanceDimensionId.governance
        signal_source = "core.delegated_flow_post_graduation_governance"

        if not _GOVERNANCE_AVAILABLE or _get_governance_evaluator is None:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "DelegatedFlowPostGraduationGovernance (PR-11V2) unavailable."
                ),
                gap_description=(
                    "core.delegated_flow_post_graduation_governance is not "
                    "importable.  Cannot assess post-graduation governance.  "
                    "Ensure PR-11V2 is deployed."
                ),
                signal_source=signal_source,
            )

        try:
            evaluator = _get_governance_evaluator()
            report = evaluator.evaluate()
            verdict_value = report.verdict.value if hasattr(report, "verdict") else ""
            is_compliant = getattr(report, "is_governance_compliant", False)
            violations = getattr(report, "violations", [])

            if is_compliant:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary=(
                        f"GovernanceEvaluator verdict: {verdict_value}.  "
                        "Post-graduation governance compliant."
                    ),
                    evidence_linkage={
                        "governance_verdict": verdict_value,
                        "violation_count": 0,
                    },
                    gap_description="",
                    signal_source=signal_source,
                )
            elif violations:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.pending,
                    evidence_summary=(
                        f"GovernanceEvaluator verdict: {verdict_value}.  "
                        f"{len(violations)} violation(s) recorded."
                    ),
                    evidence_linkage={
                        "governance_verdict": verdict_value,
                        "violation_count": len(violations),
                    },
                    gap_description=(
                        f"Governance evaluator recorded {len(violations)} "
                        "violation(s) that must be resolved for acceptance."
                    ),
                    signal_source=signal_source,
                )
            else:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        f"GovernanceEvaluator verdict: {verdict_value}."
                    ),
                    evidence_linkage={"governance_verdict": verdict_value},
                    gap_description=(
                        f"Governance verdict '{verdict_value}' is not "
                        "governance_compliant and provided no violation "
                        "details.  Treat as unresolved."
                    ),
                    signal_source=signal_source,
                )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary="GovernanceEvaluator probe raised an exception.",
                gap_description=(
                    f"GovernanceEvaluator raised: {exc!r}.  "
                    "Cannot assess post-graduation governance."
                ),
                signal_source=signal_source,
            )

    def _evaluate_multi_device_recovery(self) -> AcceptanceChecklistItem:
        """Probe the AttachedRuntimeRecoveryReadiness module."""
        dimension = AcceptanceDimensionId.multi_device_recovery
        signal_source = "core.attached_runtime_recovery_readiness"

        if not _RECOVERY_AVAILABLE or _build_recovery_snapshot is None:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "AttachedRuntimeRecoveryReadiness module unavailable."
                ),
                gap_description=(
                    "core.attached_runtime_recovery_readiness is not importable.  "
                    "Cannot assess multi-device recovery readiness.  "
                    "Ensure the recovery readiness module is deployed."
                ),
                signal_source=signal_source,
            )

        try:
            snapshot = _build_recovery_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            is_ready = evidence.get("is_recovery_ready", False)
            gap_count = evidence.get("gap_count", 0)

            if is_ready:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary="Multi-device recovery readiness: ready.",
                    evidence_linkage=evidence,
                    gap_description="",
                    signal_source=signal_source,
                )
            elif gap_count:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.pending,
                    evidence_summary=(
                        f"Multi-device recovery readiness: {gap_count} gap(s)."
                    ),
                    evidence_linkage=evidence,
                    gap_description=(
                        f"Recovery readiness snapshot reports {gap_count} "
                        "gap(s) that must be resolved before full acceptance."
                    ),
                    signal_source=signal_source,
                )
            else:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        "Multi-device recovery readiness snapshot produced "
                        "inconclusive evidence."
                    ),
                    evidence_linkage=evidence,
                    gap_description=(
                        "Recovery readiness snapshot does not indicate ready "
                        "state and reports no gaps.  Evidence is inconclusive; "
                        "treat as unresolved."
                    ),
                    signal_source=signal_source,
                )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "AttachedRuntimeRecoveryReadiness probe raised an exception."
                ),
                gap_description=(
                    f"AttachedRuntimeRecoveryReadiness raised: {exc!r}.  "
                    "Cannot assess multi-device recovery readiness."
                ),
                signal_source=signal_source,
            )

    def _evaluate_android_participant(self) -> AcceptanceChecklistItem:
        """Evaluate the Android participant dimension via the evidence ingress layer.

        Uses :func:`~core.android_participant_evidence_ingress.ingest_android_participant_evidence`
        to load, validate, and normalize a JSON evidence artifact produced by
        the Android participant.  Falls back to the legacy in-process audit
        recorder if available and the evidence ingress module is not installed.

        Status mapping
        --------------
        ready / recovered          → ``accepted``
        degraded                   → ``pending``
        unavailable                → ``unresolved``
        stale_evidence             → ``unresolved`` (with stale_evidence reason)
        malformed_evidence         → ``unresolved`` (with malformed_evidence reason)
        missing_evidence           → ``unresolved`` (with missing_evidence reason)
        unverified                 → ``pending``
        """
        dimension = AcceptanceDimensionId.android_participant
        signal_source = "core.android_participant_evidence_ingress"

        # ------------------------------------------------------------------
        # Primary path: structured evidence ingress layer
        # ------------------------------------------------------------------
        if _ANDROID_EVIDENCE_INGRESS_AVAILABLE and _ingest_android_evidence is not None:
            try:
                result = _ingest_android_evidence()
                evidence_dict = result.to_dict()

                if result.status.value in ("ready", "recovered"):
                    return AcceptanceChecklistItem(
                        dimension=dimension,
                        status=DimensionStatus.accepted,
                        evidence_summary=result.evidence_summary,
                        evidence_linkage=evidence_dict,
                        gap_description="",
                        signal_source=signal_source,
                    )
                elif result.status.value in ("degraded", "unverified"):
                    return AcceptanceChecklistItem(
                        dimension=dimension,
                        status=DimensionStatus.pending,
                        evidence_summary=result.evidence_summary,
                        evidence_linkage=evidence_dict,
                        gap_description=result.gap_description,
                        signal_source=signal_source,
                    )
                else:
                    # missing_evidence, malformed_evidence, stale_evidence,
                    # unavailable — all map to unresolved
                    return AcceptanceChecklistItem(
                        dimension=dimension,
                        status=DimensionStatus.unresolved,
                        evidence_summary=result.evidence_summary,
                        evidence_linkage=evidence_dict,
                        gap_description=result.gap_description,
                        signal_source=signal_source,
                    )
            except Exception as exc:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        "Android participant evidence ingress raised an exception."
                    ),
                    gap_description=(
                        f"android_participant_evidence_ingress raised: {exc!r}.  "
                        "Cannot assess Android participant operational evidence."
                    ),
                    signal_source=signal_source,
                )

        # ------------------------------------------------------------------
        # Fallback path: legacy in-process audit recorder (dual-repo env)
        # ------------------------------------------------------------------
        if _ANDROID_AUDIT_AVAILABLE and _get_android_delegated_audit_recorder is not None:
            signal_source_fallback = "core.android_delegated_runtime_audit"
            try:
                recorder = _get_android_delegated_audit_recorder()
                evidence: Dict[str, Any] = {}
                # Support both snapshot() (current API) and build_snapshot() (alt)
                if hasattr(recorder, "snapshot"):
                    snap = recorder.snapshot()
                    if hasattr(snap, "to_dict"):
                        evidence = snap.to_dict()
                    elif isinstance(snap, dict):
                        evidence = snap
                elif hasattr(recorder, "build_snapshot"):
                    snap = recorder.build_snapshot()
                    if hasattr(snap, "to_dict"):
                        evidence = snap.to_dict()
                    elif isinstance(snap, dict):
                        evidence = snap
                elif hasattr(recorder, "to_dict"):
                    evidence = recorder.to_dict()

                # AndroidDelegatedAuditSnapshot.to_dict() uses "event_count"
                audit_event_count = (
                    evidence.get("event_count")
                    or evidence.get("audit_event_count")
                    or 0
                )

                if audit_event_count > 0:
                    return AcceptanceChecklistItem(
                        dimension=dimension,
                        status=DimensionStatus.accepted,
                        evidence_summary=(
                            f"Android participant operational (in-process audit): "
                            f"{audit_event_count} audit events recorded."
                        ),
                        evidence_linkage=evidence,
                        gap_description="",
                        signal_source=signal_source_fallback,
                    )
                else:
                    return AcceptanceChecklistItem(
                        dimension=dimension,
                        status=DimensionStatus.unresolved,
                        evidence_summary=(
                            "Android participant: no audit events in in-process recorder."
                        ),
                        evidence_linkage=evidence,
                        gap_description=(
                            "AndroidDelegatedRuntimeAuditRecorder has no audit events.  "
                            "Android participant has not been exercised or its audit trail "
                            "is absent.  Treat as unresolved."
                        ),
                        signal_source=signal_source_fallback,
                    )
            except Exception as exc:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        "AndroidDelegatedRuntimeAuditRecorder probe raised an exception."
                    ),
                    gap_description=(
                        f"AndroidDelegatedRuntimeAuditRecorder raised: {exc!r}.  "
                        "Cannot assess Android participant operational evidence."
                    ),
                    signal_source=signal_source_fallback,
                )

        # ------------------------------------------------------------------
        # Both paths unavailable — neither ingress layer nor audit recorder
        # ------------------------------------------------------------------
        return AcceptanceChecklistItem(
            dimension=dimension,
            status=DimensionStatus.unresolved,
            evidence_summary=(
                "Android participant evidence ingress layer unavailable."
            ),
            gap_description=(
                "core.android_participant_evidence_ingress is not importable and "
                "core.android_delegated_runtime_audit is also unavailable.  "
                "Cannot assess Android participant operational evidence.  "
                "Ensure core/android_participant_evidence_ingress.py is present "
                "in the repository and ANDROID_PARTICIPANT_EVIDENCE_PATH points "
                "to a valid evidence artifact."
            ),
            signal_source=signal_source,
        )

    def _evaluate_recovery_truth_surface(self) -> AcceptanceChecklistItem:
        """Evaluate the structured recovery truth surface dimension.

        Consumes :func:`~core.recovery_truth_surface.build_recovery_truth_report`
        to produce a structured, multi-layer view of recovery evidence across
        six truth dimensions and four recovery levels.

        This dimension is distinct from ``multi_device_recovery``:
        ``multi_device_recovery`` asks "is the platform recovery-ready?";
        ``recovery_truth_surface`` asks "what is the structured evidence
        for each recovery truth atom, and which boundaries are deferred?"

        Status mapping
        --------------
        All six dimensions have ``observed`` or ``not_applicable`` status
        AND all four recovery levels are successful
            → ``accepted``
        Some dimensions are ``partial`` but none are ``unknown`` or
        ``deferred`` that would indicate structural absence
            → ``pending``
        Module unavailable or probe raised
            → ``unresolved``
        """
        dimension = AcceptanceDimensionId.recovery_truth_surface
        signal_source = "core.recovery_truth_surface"

        if not _RECOVERY_TRUTH_SURFACE_AVAILABLE or _build_recovery_truth_report is None:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "RecoveryTruthSurface module unavailable."
                ),
                gap_description=(
                    "core.recovery_truth_surface is not importable.  "
                    "Cannot assess structured recovery truth surface.  "
                    "Ensure core/recovery_truth_surface.py is deployed."
                ),
                signal_source=signal_source,
            )

        try:
            report = _build_recovery_truth_report()
            report_dict = report.to_dict()

            open_dims = report_dict.get("open_dimensions", [])
            closed_dims = report_dict.get("closed_dimensions", [])
            deferred_dims = report_dict.get("deferred_dimensions", [])
            v2_ok = report_dict.get("v2_internal_success", False)
            p_ok = report_dict.get("participant_reconnect_success", False)
            tc_ok = report_dict.get("task_continuity_success", False)
            aa_ok = report_dict.get("authority_alignment_success", False)

            total_entries = len(report_dict.get("entries", []))
            all_levels_ok = v2_ok and p_ok and tc_ok and aa_ok

            if all_levels_ok and not open_dims:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary=(
                        "RecoveryTruthSurface: all six dimensions closed; "
                        "all four recovery levels successful."
                    ),
                    evidence_linkage=report_dict,
                    gap_description="",
                    signal_source=signal_source,
                )

            # Build a gap description that accurately separates the four layers
            layer_notes: List[str] = []
            if not v2_ok:
                layer_notes.append("v2_internal: not fully closed")
            if not p_ok:
                layer_notes.append("participant_reconnect: not fully closed")
            if not tc_ok:
                layer_notes.append("task_continuity: not fully closed")
            if not aa_ok:
                layer_notes.append("authority_state_alignment: not fully closed")

            dim_notes: List[str] = []
            if open_dims:
                dim_notes.append(f"open dimensions: {open_dims!r}")
            if deferred_dims:
                dim_notes.append(f"deferred dimensions: {deferred_dims!r}")

            all_notes = layer_notes + dim_notes
            gap_desc = (
                "RecoveryTruthSurface has open or deferred dimensions: "
                + "; ".join(all_notes)
                + ".  "
                "Note: 'partial' status indicates structural wiring is present "
                "but no live event was recorded in this process instance.  "
                "Deferred boundaries (offline queue replay ordering, ephemeral "
                "transport binding) are explicitly documented as deferred."
            )

            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.pending,
                evidence_summary=(
                    f"RecoveryTruthSurface: {len(closed_dims)}/6 closed, "
                    f"{len(open_dims)}/6 open, {len(deferred_dims)} deferred; "
                    f"{total_entries} entries evaluated."
                ),
                evidence_linkage=report_dict,
                gap_description=gap_desc,
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "RecoveryTruthSurface probe raised an exception."
                ),
                gap_description=(
                    f"build_recovery_truth_report raised: {exc!r}.  "
                    "Cannot assess structured recovery truth surface."
                ),
                signal_source=signal_source,
            )

    def _evaluate_cross_repo_evidence_pipeline(self) -> AcceptanceChecklistItem:
        """Evaluate the canonical cross-repo evidence pipeline dimension (PR-05).

        Consumes :func:`~core.canonical_cross_repo_evidence_pipeline.build_canonical_cross_repo_evidence_report`
        to produce a unified view of whether all five cross-repo evidence
        source families have been ingested into a canonical, freshness-checked,
        authority-ranked pipeline.

        Status mapping
        --------------
        PipelineVerdict.complete
            → ``accepted``  (all PRIMARY sources present, fresh, consistent)
        PipelineVerdict.partial
            → ``pending``  (some PRIMARY sources missing; partial evidence)
        PipelineVerdict.stale
            → ``unresolved``  (PRIMARY source evidence exceeds freshness window)
        PipelineVerdict.missing
            → ``unresolved``  (all PRIMARY sources missing)
        PipelineVerdict.conflicting
            → ``unresolved``  (PRIMARY sources conflict; cannot optimistically accept)
        PipelineVerdict.authority_unclear
            → ``unresolved``  (authority cannot be confirmed; blocked per policy)
        PipelineVerdict.insufficient
            → ``unresolved``  (insufficient evidence to conclude)
        Module unavailable or probe raised
            → ``unresolved``
        """
        dimension = AcceptanceDimensionId.cross_repo_evidence_pipeline
        signal_source = "core.canonical_cross_repo_evidence_pipeline"

        if not _CROSS_REPO_PIPELINE_AVAILABLE or _build_cross_repo_report is None:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "CanonicalCrossRepoEvidencePipeline (PR-05) unavailable."
                ),
                gap_description=(
                    "core.canonical_cross_repo_evidence_pipeline is not importable.  "
                    "Cannot assess canonical cross-repo evidence closure.  "
                    "Ensure core/canonical_cross_repo_evidence_pipeline.py is "
                    "present and on the Python path."
                ),
                signal_source=signal_source,
            )

        try:
            report = _build_cross_repo_report()
            report_dict = report.to_dict()
            verdict_val = report.pipeline_verdict.value

            if report.pipeline_verdict.is_complete:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary=(
                        "CanonicalCrossRepoEvidencePipeline: verdict=complete.  "
                        "All PRIMARY cross-repo evidence sources present and fresh.  "
                        "Cross-repo evidence chain is canonically closed."
                    ),
                    evidence_linkage=report_dict,
                    gap_description="",
                    signal_source=signal_source,
                )

            # partial → pending (some evidence present, chain not fully closed)
            if _PipelineVerdict is not None and report.pipeline_verdict == _PipelineVerdict.partial:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.pending,
                    evidence_summary=(
                        f"CanonicalCrossRepoEvidencePipeline: verdict={verdict_val}.  "
                        "Some PRIMARY cross-repo evidence sources are missing.  "
                        "Evidence chain is partially established but not fully closed."
                    ),
                    evidence_linkage=report_dict,
                    gap_description=(
                        "Cross-repo evidence chain is partial.  "
                        "Missing sources: "
                        + str(report.missing_sources)
                        + ".  "
                        "Downgrade reasons: "
                        + "; ".join(report.downgrade_reasons or ["none"])
                        + ".  "
                        "MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY applied."
                    ),
                    signal_source=signal_source,
                )

            # stale, missing (all), conflicting, authority_unclear, insufficient
            # → all map to unresolved per fail-conservative policy
            downgrade_notes = "; ".join(report.downgrade_reasons or ["none"])
            conflict_notes = "; ".join(report.conflict_notes or [])

            gap_parts: List[str] = [
                f"CanonicalCrossRepoEvidencePipeline verdict: {verdict_val}.  ",
                f"Downgrade reasons: {downgrade_notes}.  ",
            ]
            if conflict_notes:
                gap_parts.append(f"Conflict notes: {conflict_notes}.  ")
            if report.stale_sources:
                gap_parts.append(
                    f"Stale sources: {report.stale_sources}.  "
                    "STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY applied.  "
                )
            if report.authority_unclear_sources:
                gap_parts.append(
                    f"Authority unclear: {report.authority_unclear_sources}.  "
                    "AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY applied.  "
                )

            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    f"CanonicalCrossRepoEvidencePipeline: verdict={verdict_val}.  "
                    "Cross-repo evidence chain is not canonically closed."
                ),
                evidence_linkage=report_dict,
                gap_description="".join(gap_parts),
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "CanonicalCrossRepoEvidencePipeline probe raised an exception."
                ),
                gap_description=(
                    f"build_canonical_cross_repo_evidence_report raised: {exc!r}.  "
                    "Cannot assess canonical cross-repo evidence pipeline."
                ),
                signal_source=signal_source,
            )

    def _evaluate_multi_device_canonical_governance(self) -> AcceptanceChecklistItem:
        """Evaluate the multi-device canonical governance dimension (PR-09).

        Consumes :func:`~core.multi_device_canonical_governance.build_multi_device_governance_report`
        to produce a structured view of whether multi-device / delegated
        runtime has been formally classified into the correct governance
        tier and whether the verdict is evidence-honest.

        Status mapping
        --------------
        MultiDeviceGovernanceVerdict.default_mainline_active
            → ``accepted``  (delegated participant evidence present and
              complete; no blocking guarded capabilities)
        MultiDeviceGovernanceVerdict.conditional_active
            → ``pending``  (delegated participant present but evidence
              partial, or guarded capabilities block default-mainline)
        MultiDeviceGovernanceVerdict.single_device_baseline
            → ``pending``  (single-device mode; infrastructure wired but
              no delegated participant present — honest operational state,
              not a blocking failure)
        MultiDeviceGovernanceVerdict.guarded_baseline
            → ``pending``  (guarded sub-surfaces prevent operational tier)
        MultiDeviceGovernanceVerdict.partial_evidence
            → ``unresolved``  (insufficient evidence to classify)
        MultiDeviceGovernanceVerdict.no_evidence
            → ``unresolved``  (no evidence obtained)
        Module unavailable or probe raised
            → ``unresolved``
        """
        dimension = AcceptanceDimensionId.multi_device_canonical_governance
        signal_source = "core.multi_device_canonical_governance"

        if not _MD_GOVERNANCE_AVAILABLE or _build_md_governance_report is None:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "MultiDeviceCanonicalGovernance (PR-09) unavailable."
                ),
                gap_description=(
                    "core.multi_device_canonical_governance is not importable.  "
                    "Cannot assess multi-device canonical governance tier.  "
                    "Ensure core/multi_device_canonical_governance.py is "
                    "present and on the Python path."
                ),
                signal_source=signal_source,
            )

        try:
            report = _build_md_governance_report()
            verdict_val = report.verdict.value
            report_dict = report.to_dict()

            if report.verdict == _MDGovernanceVerdict.default_mainline_active:
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.accepted,
                    evidence_summary=(
                        "MultiDeviceCanonicalGovernance: verdict=default_mainline_active.  "
                        "Delegated participant evidence present.  "
                        f"Default-mainline capabilities: "
                        f"{len(report.default_mainline_capabilities)}.  "
                        "Multi-device / delegated runtime formally classified as "
                        "default-mainline system surface."
                    ),
                    evidence_linkage=report_dict,
                    gap_description="",
                    signal_source=signal_source,
                )

            if report.verdict in (
                _MDGovernanceVerdict.conditional_active,
                _MDGovernanceVerdict.guarded_baseline,
                _MDGovernanceVerdict.single_device_baseline,
            ):
                downgrade_note = (
                    "; ".join(report.downgrade_reasons[:3])
                    if report.downgrade_reasons
                    else "see report for details"
                )
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.pending,
                    evidence_summary=(
                        f"MultiDeviceCanonicalGovernance: verdict={verdict_val}.  "
                        f"Delegated participants: {report.delegated_participant_count}.  "
                        f"Guarded capabilities: {len(report.guarded_capabilities)}.  "
                        f"Default-mainline capabilities: "
                        f"{len(report.default_mainline_capabilities)}."
                    ),
                    evidence_linkage=report_dict,
                    gap_description=(
                        f"Multi-device governance verdict is {verdict_val!r} — "
                        "not yet default-mainline.  "
                        f"Downgrade reasons: {downgrade_note}.  "
                        "EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY and "
                        "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY applied."
                    ),
                    signal_source=signal_source,
                )

            # partial_evidence or no_evidence → unresolved
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    f"MultiDeviceCanonicalGovernance: verdict={verdict_val}.  "
                    "Insufficient evidence to classify multi-device governance tier."
                ),
                evidence_linkage=report_dict,
                gap_description=(
                    f"Multi-device governance verdict is {verdict_val!r}.  "
                    "Cannot classify system tier without evidence.  "
                    "Downgrade reasons: "
                    + ("; ".join(report.downgrade_reasons) or "none")
                    + ".  "
                    "NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY applied."
                ),
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "MultiDeviceCanonicalGovernance probe raised an exception."
                ),
                gap_description=(
                    f"build_multi_device_governance_report raised: {exc!r}.  "
                    "Cannot assess multi-device canonical governance."
                ),
                signal_source=signal_source,
            )

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    def _evaluate_conversation_continuity(self) -> AcceptanceChecklistItem:
        """Evaluate the conversation continuity truth dimension (PR-12).

        Consumes :func:`~core.conversation_continuity_truth.build_conversation_continuity_verdict`
        to determine whether crash / restart / process death scenarios have a
        formally evaluated and classified conversation continuity state rather
        than an optimistically assumed one.

        This probe evaluates the *structural availability* of the contract
        module and runs a default evidence evaluation to confirm the contract
        is wired.  Production deployments should feed actual recovery evidence
        via the contract directly; this acceptance probe verifies that the
        taxonomy is available and that the evaluator correctly produces a
        non-optimistic verdict when no active recovery evidence is present.

        Status mapping
        --------------
        Module present and contract produces a valid ConversationContinuityVerdict
        with class != ``continuity_lost`` under real evidence
            → ``accepted``
        Module present, contract available, but no active session evidence
        (expected in baseline / non-recovery contexts)
            → ``pending`` (structure present, live evidence not yet collected)
        Module unavailable or probe raised
            → ``unresolved``
        """
        dimension = AcceptanceDimensionId.conversation_continuity
        signal_source = "core.conversation_continuity_truth"

        if (
            not _CONVERSATION_CONTINUITY_AVAILABLE
            or _build_conversation_continuity_verdict is None
            or _ConversationContinuityEvidence is None
        ):
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "ConversationContinuityTruth (PR-12) module unavailable."
                ),
                gap_description=(
                    "core.conversation_continuity_truth is not importable.  "
                    "Cannot assess conversation continuity truth contract.  "
                    "Ensure core/conversation_continuity_truth.py is deployed."
                ),
                signal_source=signal_source,
            )

        try:
            # Probe with a minimal (no-evidence) input to confirm the contract
            # is wired and produces a conservative verdict (continuity_lost)
            # rather than an optimistic one.
            probe_evidence = _ConversationContinuityEvidence()
            verdict = _build_conversation_continuity_verdict(probe_evidence)
            verdict_dict = verdict.to_dict()
            continuity_class = verdict.continuity_class.value

            # The baseline probe (no evidence) MUST NOT produce
            # authoritative_continuity_restored.  If it does, the contract is
            # misconfigured.
            if continuity_class == "authoritative_continuity_restored":
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        "ConversationContinuityTruth baseline probe returned "
                        "authoritative_continuity_restored with no evidence — "
                        "contract misconfiguration detected."
                    ),
                    evidence_linkage=verdict_dict,
                    gap_description=(
                        "The conversation continuity contract produced "
                        "authoritative_continuity_restored with all evidence "
                        "dimensions False.  This violates "
                        "EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY.  "
                        "The contract module must be corrected."
                    ),
                    signal_source=signal_source,
                )

            # Contract is wired and conservative.  This dimension is
            # structurally present.  Whether live recovery evidence has been
            # ingested is a runtime concern; the acceptance dimension confirms
            # the formal taxonomy is available and correctly wired.
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.pending,
                evidence_summary=(
                    "ConversationContinuityTruth (PR-12) contract is wired and "
                    "correctly produces conservative verdicts.  "
                    f"Baseline probe class: {continuity_class}.  "
                    "Live recovery evidence has not been ingested in this "
                    "process instance (expected in non-recovery baseline context)."
                ),
                evidence_linkage={
                    "module": signal_source,
                    "contract_sentinel": _CONV_CONTINUITY_AUTHORITY,
                    "baseline_probe_class": continuity_class,
                    "baseline_probe_is_authoritative": verdict.is_authoritative,
                    "baseline_probe_requires_rebind": verdict.requires_rebind,
                },
                gap_description=(
                    "Conversation continuity taxonomy is formally available "
                    "(PR-12), but no active live recovery session evidence has "
                    "been fed to the contract in this process instance.  "
                    "This is expected in non-recovery baseline contexts.  "
                    "Production recovery paths should feed evidence from the "
                    "session manager and rebind layer."
                ),
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "ConversationContinuityTruth probe raised an exception."
                ),
                gap_description=(
                    f"build_conversation_continuity_verdict raised: {exc!r}.  "
                    "Cannot assess conversation continuity truth dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_task_continuity(self) -> AcceptanceChecklistItem:
        """Evaluate the in-flight task continuity taxonomy dimension (PR-06).

        Consumes :func:`~core.inflight_task_continuity_taxonomy
        .build_task_continuity_verdict` to determine whether restart /
        process bounce / recovery scenarios have a formally evaluated and
        classified in-flight task continuity state rather than an optimistically
        assumed one.

        This probe evaluates the *structural availability* of the taxonomy
        module and runs a default (no-evidence) evaluation to confirm the
        contract is wired and correctly produces a conservative verdict
        (``task_continuity_lost``) rather than an optimistic one.
        Production deployments should feed actual recovery evidence via
        :func:`~core.inflight_task_continuity_taxonomy
        .build_task_continuity_verdict_from_report`; this acceptance probe
        verifies that the taxonomy is available and conservatively wired.

        Status mapping
        --------------
        Module present and contract produces a valid verdict with class
        != ``task_continuity_lost`` under real restart recovery evidence
            → ``accepted``
        Module present, contract available, but no recovery evidence in
        this process instance (expected in baseline / non-recovery contexts)
            → ``pending`` (structure present, live evidence not yet collected)
        Baseline probe returns ``authoritative_task_continuity_restored``
        with no evidence (contract misconfiguration)
            → ``unresolved``
        Module unavailable or probe raised
            → ``unresolved``
        """
        dimension = AcceptanceDimensionId.task_continuity
        signal_source = "core.inflight_task_continuity_taxonomy"

        if (
            not _TASK_CONTINUITY_TAXONOMY_AVAILABLE
            or _build_task_continuity_verdict is None
            or _InFlightTaskContinuityEvidence is None
        ):
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "InFlightTaskContinuityTaxonomy (PR-06) module unavailable."
                ),
                gap_description=(
                    "core.inflight_task_continuity_taxonomy is not importable.  "
                    "Cannot assess in-flight task continuity taxonomy contract.  "
                    "Ensure core/inflight_task_continuity_taxonomy.py is deployed."
                ),
                signal_source=signal_source,
            )

        try:
            # Probe with a minimal (no-evidence) input to confirm the contract
            # is wired and produces a conservative verdict (task_continuity_lost)
            # rather than an optimistic one.
            probe_evidence = _InFlightTaskContinuityEvidence()
            verdict = _build_task_continuity_verdict(probe_evidence)
            verdict_dict = verdict.to_dict()
            continuity_class = verdict.continuity_class.value

            # The baseline probe (no evidence) MUST NOT produce
            # authoritative_task_continuity_restored.  If it does, the
            # taxonomy contract is misconfigured.
            if (
                _InFlightTaskContinuityClass is not None
                and verdict.continuity_class
                == _InFlightTaskContinuityClass.authoritative_task_continuity_restored
            ):
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        "InFlightTaskContinuityTaxonomy baseline probe returned "
                        "authoritative_task_continuity_restored with no evidence — "
                        "taxonomy contract misconfiguration detected."
                    ),
                    evidence_linkage=verdict_dict,
                    gap_description=(
                        "The in-flight task continuity taxonomy contract produced "
                        "authoritative_task_continuity_restored with all evidence "
                        "dimensions at zero/False.  This violates "
                        "EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY and "
                        "SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY.  "
                        "The taxonomy module must be corrected."
                    ),
                    signal_source=signal_source,
                )

            # Taxonomy is wired and conservative.  This dimension is
            # structurally present.  Whether live recovery evidence has been
            # ingested is a runtime concern; the acceptance dimension confirms
            # the formal taxonomy is available and correctly wired.
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.pending,
                evidence_summary=(
                    "InFlightTaskContinuityTaxonomy (PR-06) contract is wired and "
                    "correctly produces conservative verdicts.  "
                    f"Baseline probe class: {continuity_class}.  "
                    "Live recovery evidence has not been ingested in this "
                    "process instance (expected in non-recovery baseline context)."
                ),
                evidence_linkage={
                    "module": signal_source,
                    "taxonomy_sentinel": _TASK_CONTINUITY_AUTHORITY,
                    "baseline_probe_class": continuity_class,
                    "baseline_probe_is_authoritative": verdict.is_authoritative,
                    "baseline_probe_continuity_lost": verdict.continuity_lost,
                },
                gap_description=(
                    "In-flight task continuity taxonomy is formally available "
                    "(PR-06), but no active live recovery evidence has been fed "
                    "to the contract in this process instance.  "
                    "This is expected in non-recovery baseline contexts.  "
                    "Production recovery paths should feed evidence from the "
                    "RuntimeRestartRecoveryCoordinator and InFlightTaskContinuityContract "
                    "via build_task_continuity_verdict_from_report()."
                ),
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "InFlightTaskContinuityTaxonomy probe raised an exception."
                ),
                gap_description=(
                    f"build_task_continuity_verdict raised: {exc!r}.  "
                    "Cannot assess in-flight task continuity taxonomy dimension."
                ),
                signal_source=signal_source,
            )

    def _evaluate_human_intervention(self) -> AcceptanceChecklistItem:
        """Evaluate the human intervention taxonomy dimension (PR-08).

        Consumes :func:`~core.human_intervention_taxonomy
        .build_human_intervention_verdict` to determine whether the formal
        human intervention taxonomy is available and correctly produces a
        conservative (non-autonomous) verdict when no explicit autonomous
        evidence is present.

        This probe evaluates the *structural availability* of the taxonomy
        module and runs a zero-evidence evaluation to confirm the contract
        is wired and correctly defaults to ``escalation_required`` rather
        than optimistically claiming ``autonomous_closure``.  Production
        deployments should feed actual intervention evidence (operator
        actions, manual overrides, confirmation events, escalation state)
        via the contract directly; this acceptance probe verifies that the
        taxonomy is available and conservatively wired.

        Status mapping
        --------------
        Module present and zero-evidence probe correctly returns a
        non-autonomous class (``escalation_required``)
            → ``pending`` (structure present; live evidence not yet collected)
        Zero-evidence probe returns ``autonomous_closure``
        (contract misconfiguration)
            → ``unresolved``
        Module unavailable or probe raised
            → ``unresolved``
        """
        dimension = AcceptanceDimensionId.human_intervention
        signal_source = "core.human_intervention_taxonomy"

        if (
            not _HUMAN_INTERVENTION_TAXONOMY_AVAILABLE
            or _build_human_intervention_verdict is None
            or _HumanInterventionEvidence is None
        ):
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "HumanInterventionTaxonomy (PR-08) module unavailable."
                ),
                gap_description=(
                    "core.human_intervention_taxonomy is not importable.  "
                    "Cannot assess human intervention taxonomy contract.  "
                    "Ensure core/human_intervention_taxonomy.py is deployed."
                ),
                signal_source=signal_source,
            )

        try:
            # Probe with a zero-evidence input to confirm the contract is
            # wired and produces a conservative verdict (escalation_required)
            # rather than an optimistic autonomous_closure.
            probe_evidence = _HumanInterventionEvidence()
            verdict = _build_human_intervention_verdict(probe_evidence)
            verdict_dict = verdict.to_dict()
            intervention_class = verdict.intervention_class.value

            # The zero-evidence probe MUST NOT produce autonomous_closure.
            # If it does, the contract is misconfigured.
            if (
                _HumanInterventionClass is not None
                and verdict.intervention_class
                == _HumanInterventionClass.autonomous_closure
            ):
                return AcceptanceChecklistItem(
                    dimension=dimension,
                    status=DimensionStatus.unresolved,
                    evidence_summary=(
                        "HumanInterventionTaxonomy zero-evidence probe returned "
                        "autonomous_closure with no evidence — "
                        "taxonomy contract misconfiguration detected."
                    ),
                    evidence_linkage=verdict_dict,
                    gap_description=(
                        "The human intervention taxonomy contract produced "
                        "autonomous_closure with all evidence dimensions False.  "
                        "This violates "
                        "EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY "
                        "and AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY.  "
                        "The taxonomy module must be corrected."
                    ),
                    signal_source=signal_source,
                )

            # Taxonomy is wired and conservative.  This dimension is
            # structurally present.  Whether live intervention evidence has
            # been ingested is a runtime concern; the acceptance dimension
            # confirms the formal taxonomy is available and correctly wired.
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.pending,
                evidence_summary=(
                    "HumanInterventionTaxonomy (PR-08) contract is wired and "
                    "correctly produces conservative verdicts.  "
                    f"Zero-evidence probe class: {intervention_class}.  "
                    "Live intervention evidence has not been ingested in this "
                    "process instance (expected in non-intervention baseline "
                    "context)."
                ),
                evidence_linkage={
                    "module": signal_source,
                    "taxonomy_sentinel": _HUMAN_INTERVENTION_AUTHORITY,
                    "zero_evidence_probe_class": intervention_class,
                    "zero_evidence_probe_is_autonomous": verdict.is_autonomous,
                    "zero_evidence_probe_is_positive_closure": (
                        verdict.is_positive_closure
                    ),
                },
                gap_description=(
                    "Human intervention taxonomy is formally available (PR-08), "
                    "but no live intervention evidence has been fed to the "
                    "contract in this process instance.  "
                    "This is expected in non-intervention baseline contexts.  "
                    "Production paths should feed evidence from operator action "
                    "signals, manual override events, escalation state, and "
                    "human confirmation events via "
                    "build_human_intervention_verdict()."
                ),
                signal_source=signal_source,
            )

        except Exception as exc:
            return AcceptanceChecklistItem(
                dimension=dimension,
                status=DimensionStatus.unresolved,
                evidence_summary=(
                    "HumanInterventionTaxonomy probe raised an exception."
                ),
                gap_description=(
                    f"build_human_intervention_verdict raised: {exc!r}.  "
                    "Cannot assess human intervention taxonomy dimension."
                ),
                signal_source=signal_source,
            )

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(
        checklist: Dict[str, AcceptanceChecklistItem],
    ) -> SystemAcceptanceVerdict:
        """Derive the system-level verdict from the eleven dimension items.

        Policy:
        - All eleven dimensions must be ``accepted`` → ``fully_operational``
        - Any ``unresolved`` dimension → ``not_fully_operational_critical_risk``
        - Any ``pending`` dimension (no ``unresolved``) →
          ``not_fully_operational_pending_dimensions``
        - Checklist does not contain all eleven dimensions →
          ``acceptance_unknown_insufficient_evidence``
        """
        all_dims = AcceptanceDimensionId.all_dimensions()
        if not all(d.value in checklist for d in all_dims):
            return SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence

        statuses = [checklist[d.value].status for d in all_dims]

        if any(s == DimensionStatus.unresolved for s in statuses):
            return SystemAcceptanceVerdict.not_fully_operational_critical_risk

        if any(s == DimensionStatus.pending for s in statuses):
            return SystemAcceptanceVerdict.not_fully_operational_pending_dimensions

        if all(s == DimensionStatus.accepted for s in statuses):
            return SystemAcceptanceVerdict.fully_operational

        return SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence

    @staticmethod
    def _collect_unresolved_risks(
        checklist: Dict[str, AcceptanceChecklistItem],
    ) -> List[Dict[str, str]]:
        """Return a list of risk dicts for every non-accepted dimension."""
        risks: List[Dict[str, str]] = []
        for dim_id in AcceptanceDimensionId.all_dimensions():
            item = checklist.get(dim_id.value)
            if item is None:
                risks.append(
                    {
                        "dimension": dim_id.value,
                        "risk_description": (
                            f"Dimension '{dim_id.value}' is missing from the "
                            "checklist.  Evidence was not collected."
                        ),
                    }
                )
            elif item.status != DimensionStatus.accepted:
                risks.append(
                    {
                        "dimension": dim_id.value,
                        "risk_description": item.gap_description
                        or f"Dimension '{dim_id.value}' is {item.status.value}.",
                    }
                )
        return risks

    @staticmethod
    def _build_evidence_linkage(
        checklist: Dict[str, AcceptanceChecklistItem],
    ) -> Dict[str, Any]:
        """Aggregate per-dimension evidence linkage into a top-level dict."""
        linkage: Dict[str, Any] = {}
        for dim_id in AcceptanceDimensionId.all_dimensions():
            item = checklist.get(dim_id.value)
            if item is not None:
                linkage[dim_id.value] = item.evidence_linkage
        return linkage

    @staticmethod
    def _build_summary(
        verdict: SystemAcceptanceVerdict,
        checklist: Dict[str, AcceptanceChecklistItem],
        unresolved_risks: List[Dict[str, str]],
    ) -> str:
        """Build a human-readable multi-line summary."""
        lines: List[str] = []
        lines.append("=" * 68)
        lines.append("GALAXY V2 — SYSTEM FINAL ACCEPTANCE VERDICT")
        lines.append("=" * 68)

        verdict_label = verdict.value.upper().replace("_", " ")
        lines.append(f"VERDICT : {verdict_label}")
        lines.append("")

        lines.append("SYSTEM ACCEPTANCE CHECKLIST")
        lines.append("-" * 40)
        for dim_id in AcceptanceDimensionId.all_dimensions():
            item = checklist.get(dim_id.value)
            if item is None:
                status_str = "MISSING"
            else:
                status_str = item.status.value.upper()
            lines.append(f"  [{status_str:10s}] {dim_id.value}")
        lines.append("")

        if unresolved_risks:
            lines.append("UNRESOLVED RISKS")
            lines.append("-" * 40)
            for risk in unresolved_risks:
                dim = risk.get("dimension", "unknown")
                desc = risk.get("risk_description", "")
                lines.append(f"  [{dim}]")
                lines.append(f"    {desc}")
            lines.append("")

        if verdict.is_fully_operational:
            lines.append(
                "CONCLUSION: Galaxy V2 platform is FORMALLY ACCEPTED as "
                "fully-operational."
            )
            lines.append(
                "All five system acceptance dimensions are ACCEPTED.  "
                "Release and external integration (e.g. HA/Matter) may "
                "proceed on this platform baseline."
            )
        elif verdict.is_pending:
            lines.append(
                "CONCLUSION: Galaxy V2 platform is NOT YET fully-operational.  "
                "One or more dimensions are pending."
            )
        else:
            lines.append(
                "CONCLUSION: Galaxy V2 platform is NOT fully-operational.  "
                "One or more critical dimensions are unresolved."
            )

        lines.append("=" * 68)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process-global singleton and helpers
# ---------------------------------------------------------------------------

_evaluator_singleton: Optional[SystemFinalAcceptanceEvaluator] = None


def get_system_acceptance_evaluator() -> SystemFinalAcceptanceEvaluator:
    """Return the process-global :class:`SystemFinalAcceptanceEvaluator` singleton.

    Creates the singleton on first call.  Use
    :func:`reset_system_acceptance_evaluator` for test isolation.
    """
    global _evaluator_singleton
    if _evaluator_singleton is None:
        _evaluator_singleton = SystemFinalAcceptanceEvaluator()
    return _evaluator_singleton


def reset_system_acceptance_evaluator() -> None:
    """Reset the process-global singleton.

    Intended for test isolation only.  Do not call from production code.
    """
    global _evaluator_singleton
    _evaluator_singleton = None


def evaluate_system_acceptance() -> SystemAcceptanceReport:
    """Convenience wrapper: evaluate and return a :class:`SystemAcceptanceReport`.

    Equivalent to ``get_system_acceptance_evaluator().evaluate()``.
    """
    return get_system_acceptance_evaluator().evaluate()
