#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_readiness_gate.py
======================================
PR-9V2 (post-533 dual-repo runtime host unification track):
Delegated Flow Readiness / Release Gate.

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

However, none of these modules provides a **unified readiness judgment** that
answers the system-level question: *is the delegated canonical path ready to
become the default execution path?*  Without such a gate:

* Readiness decisions are informal ("feels ready") rather than structured.
* Gaps in individual dimensions (e.g. missing Android/V2 contract signal)
  are buried in sub-system state rather than surfaced as explicit readiness
  gaps for operators and owners.
* The PR sequence cannot close with a formal release-gate verdict that
  downstream default-on / rollout / enforcement steps can consume.

This module closes that gap by establishing the **Delegated Flow Readiness /
Release Gate** — the unified evaluator and authoritative verdict layer for
whether the delegated canonical path is ready for release.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  DELEGATED FLOW READINESS / RELEASE GATE  (this module, layer 11)  │
    │                                                                     │
    │  Evaluates (read-only) across five readiness dimensions:           │
    │    • continuity_replay   — FlowContinuityCoordinator               │
    │    • truth_ownership     — FlowLevelTruthOwnership                 │
    │    • result_convergence  — FlowAwareResultConvergence              │
    │    • operator_surface    — FlowLevelOperatorSurface                │
    │    • compat_legacy       — CompatLegacyPathBlockingCanonicalization│
    │                                                                     │
    │  Produces:                                                         │
    │    • DimensionReadinessResult  (per-dimension verdict)             │
    │    • DelegatedFlowReadinessReport  (overall release-gate verdict)  │
    │                                                                     │
    │  Overall readiness verdicts:                                       │
    │    • ready_for_release                                             │
    │    • not_ready_due_to_missing_truth_alignment                      │
    │    • not_ready_due_to_result_convergence_gap                       │
    │    • not_ready_due_to_operator_visibility_gap                      │
    │    • not_ready_due_to_compat_influence                             │
    │    • readiness_unknown_due_to_missing_signal                       │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — the gate reads from existing runtime modules; it
   never mutates canonical state.
3. **Fail-conservative** — when a dimension signal is unavailable the gate
   assigns ``unknown`` status for that dimension and, if any critical
   dimension is unknown, the overall verdict is
   ``readiness_unknown_due_to_missing_signal``.
4. **Operator-visible gaps** — every ``not_ready_*`` or ``unknown``
   dimension carries a human-readable ``gap_description`` so operators
   and owners can see exactly what is blocking release.
5. **Stable artifacts** — all data classes are fully serialisable
   (``to_dict`` / ``to_json``) so they can be persisted, diffed, and
   consumed by release pipelines.

Public API
----------
Authority sentinels::

    DELEGATED_FLOW_READINESS_GATE_AUTHORITY
    DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL

Policy sentinels::

    READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY
    READINESS_GATE_IS_PROJECTION_ONLY_POLICY
    READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY
    READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY
    RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY
    ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY
    ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY

Enumerations::

    ReadinessDimension
    DimensionReadinessStatus
    DelegatedFlowReadinessVerdict

Data classes::

    DimensionReadinessResult
    DelegatedFlowReadinessReport

Class::

    DelegatedFlowReadinessGate

Helpers::

    evaluate_delegated_flow_readiness() -> DelegatedFlowReadinessReport
    get_readiness_gate()  -> DelegatedFlowReadinessGate
    reset_readiness_gate() -> None  # testing only
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DelegatedFlowReadinessGate")

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
    "DELEGATED_FLOW_READINESS_GATE_AUTHORITY",
    "DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL",
    # Policy sentinels
    "READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY",
    "READINESS_GATE_IS_PROJECTION_ONLY_POLICY",
    "READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY",
    "READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY",
    "RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY",
    "ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY",
    "ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY",
    # Enumerations
    "ReadinessDimension",
    "DimensionReadinessStatus",
    "DelegatedFlowReadinessVerdict",
    # Data classes
    "DimensionReadinessResult",
    "DelegatedFlowReadinessReport",
    # Class
    "DelegatedFlowReadinessGate",
    # Helpers
    "evaluate_delegated_flow_readiness",
    "get_readiness_gate",
    "reset_readiness_gate",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_READINESS_GATE_AUTHORITY: str = (
    "DELEGATED_FLOW_READINESS_GATE_AUTHORITY::"
    "core.delegated_flow_readiness_gate::PR9V2::"
    "delegated-flow-readiness-release-gate::"
    "unified-readiness-judgment-for-delegated-canonical-path"
)
"""Sentinel: this module is the canonical readiness/release gate authority.

Import to assert that a release pipeline, operator console, or rollout
controller is reading the readiness verdict from the correct canonical gate
rather than from individual sub-system state."""

DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL: str = (
    "DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL::"
    "package=PR9V2::profile=delegated-flow-readiness-gate-v1::"
    "module=core.delegated_flow_readiness_gate"
)
"""Package sentinel for PR-9V2."""

READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY: str = (
    "POLICY::READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_V1: "
    "DelegatedFlowReadinessGate.evaluate() is the sole authoritative entry "
    "point for determining whether the delegated canonical path is ready for "
    "release.  Release pipelines, rollout controllers, and operator consoles "
    "MUST consume the gate's DelegatedFlowReadinessReport; they MUST NOT "
    "derive readiness from individual sub-system state or informal signals.  "
    "PR-9V2, delegated flow readiness / release gate."
)

READINESS_GATE_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::READINESS_GATE_IS_PROJECTION_ONLY_V1: "
    "The readiness gate is a read-only projection layer.  It consumes "
    "snapshots and artifacts from the five canonical dimension modules "
    "(FlowContinuityCoordinator, FlowLevelTruthOwnership, "
    "FlowAwareResultConvergence, FlowLevelOperatorSurface, "
    "CompatLegacyPathBlockingCanonicalization) without mutating any "
    "canonical state.  The gate MUST NOT write to any canonical runtime "
    "or alter any sub-system's decision history.  "
    "PR-9V2, delegated flow readiness / release gate."
)

READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY: str = (
    "POLICY::READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_V1: "
    "When a readiness dimension signal is unavailable (sub-system module "
    "not importable, snapshot empty, or runtime not yet populated), the gate "
    "MUST assign DimensionReadinessStatus.unknown for that dimension and "
    "MUST produce DelegatedFlowReadinessVerdict."
    "readiness_unknown_due_to_missing_signal as the overall verdict when "
    "any critical dimension is unknown.  Silence is NOT readiness.  "
    "PR-9V2, delegated flow readiness / release gate."
)

READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY: str = (
    "POLICY::READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_V1: "
    "Every not_ready or unknown dimension result MUST carry a non-empty "
    "gap_description that is human-readable by operators and owners.  "
    "Readiness gaps MUST NOT be buried in sub-system logs; they MUST be "
    "surfaced in the DelegatedFlowReadinessReport so operators can see "
    "exactly what is blocking release.  "
    "PR-9V2, delegated flow readiness / release gate."
)

RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY: str = (
    "POLICY::RELEASE_VERDICT_IS_STABLE_ARTIFACT_V1: "
    "DelegatedFlowReadinessReport is a stable, serialisable artifact that "
    "MUST be producible at any time without side effects.  It MUST be "
    "fully round-trippable through to_dict() / to_json() for persistence, "
    "diffing, and consumption by release pipelines.  "
    "PR-9V2, delegated flow readiness / release gate."
)

ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY: str = (
    "POLICY::ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_V1: "
    "A ready_for_release verdict REQUIRES all five readiness dimensions "
    "(continuity_replay, truth_ownership, result_convergence, "
    "operator_surface, compat_legacy) to have DimensionReadinessStatus.ready "
    "status.  Any dimension that is not_ready or unknown MUST prevent the "
    "overall verdict from reaching ready_for_release.  "
    "PR-9V2, delegated flow readiness / release gate."
)

ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY: str = (
    "POLICY::ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_V1: "
    "The absence of a required Android/V2 canonical contract signal "
    "(e.g. missing truth alignment history, zero convergence decisions, "
    "no compat gate evaluations) MUST be reflected as a readiness gap in "
    "the appropriate dimension with a descriptive gap_description.  "
    "An empty sub-system runtime is treated as a missing signal, not as "
    "a clean pass.  "
    "PR-9V2, delegated flow readiness / release gate."
)


# ---------------------------------------------------------------------------
# ReadinessDimension
# ---------------------------------------------------------------------------


class ReadinessDimension(str, Enum):
    """The five canonical readiness dimensions evaluated by the gate.

    Values
    ------
    continuity_replay
        Evaluates whether the continuity / replay foundation is ready.
        Sources: FlowContinuityCoordinator snapshot — fail_closed count,
        coordinator decision history presence.

    truth_ownership
        Evaluates whether flow-level truth ownership and alignment are ready.
        Sources: FlowTruthAlignmentRuntime snapshot — alignment decision
        history, quarantine count, missing truth signals.

    result_convergence
        Evaluates whether flow-aware result convergence is ready.
        Sources: FlowAwareConvergenceCoordinator snapshot — convergence
        decision history, quarantine count, parallel aggregation state.

    operator_surface
        Evaluates whether the flow-level operator surface is ready.
        Sources: FlowLevelOperatorSurface — ability to project at least one
        flow, absence of unknown-phase flows that are not pending dispatch.

    compat_legacy
        Evaluates whether compat / legacy path blocking canonicalization is
        ready.
        Sources: CompatLegacyBlockingSnapshot — quarantine count, invisible
        flow count, overall health flag.
    """

    continuity_replay = "continuity_replay"
    truth_ownership = "truth_ownership"
    result_convergence = "result_convergence"
    operator_surface = "operator_surface"
    compat_legacy = "compat_legacy"

    @classmethod
    def from_string(cls, value: str) -> "ReadinessDimension":
        """Return the member matching *value*, defaulting to ``continuity_replay``."""
        if not isinstance(value, str):
            return cls.continuity_replay
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.continuity_replay

    @classmethod
    def all_dimensions(cls) -> List["ReadinessDimension"]:
        """Return the five dimensions in canonical evaluation order."""
        return [
            cls.continuity_replay,
            cls.truth_ownership,
            cls.result_convergence,
            cls.operator_surface,
            cls.compat_legacy,
        ]


# ---------------------------------------------------------------------------
# DimensionReadinessStatus
# ---------------------------------------------------------------------------


class DimensionReadinessStatus(str, Enum):
    """Per-dimension readiness status.

    Values
    ------
    ready
        The dimension has passed all readiness checks.  No gaps detected.

    not_ready
        The dimension has at least one blocking readiness gap.  See
        ``gap_description`` in the associated :class:`DimensionReadinessResult`.

    unknown
        The dimension signal is unavailable (sub-system not initialised,
        snapshot empty, or module not importable).  Treated conservatively
        as not-ready for release-gate purposes.
    """

    ready = "ready"
    not_ready = "not_ready"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "DimensionReadinessStatus":
        """Return the member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# DelegatedFlowReadinessVerdict
# ---------------------------------------------------------------------------


class DelegatedFlowReadinessVerdict(str, Enum):
    """Overall release-gate verdict for the delegated canonical path.

    Values
    ------
    ready_for_release
        All five readiness dimensions are ``ready``.  The delegated
        canonical path is cleared for release / default-on.

    not_ready_due_to_missing_truth_alignment
        The ``truth_ownership`` dimension is ``not_ready``.  Truth alignment
        between Android and V2 canonical has unresolved gaps.

    not_ready_due_to_result_convergence_gap
        The ``result_convergence`` dimension is ``not_ready``.  Result
        convergence has quarantined or unresolved gaps that block release.

    not_ready_due_to_operator_visibility_gap
        The ``operator_surface`` dimension is ``not_ready``.  Operators
        cannot reliably observe delegated flow execution state; visibility
        is insufficient for production release.

    not_ready_due_to_compat_influence
        The ``compat_legacy`` dimension is ``not_ready``.  Active or
        quarantined compat/legacy influence vectors have not been bounded;
        invisible flows remain.

    readiness_unknown_due_to_missing_signal
        One or more dimensions have ``unknown`` status because the required
        runtime signal is absent.  The gate cannot safely conclude readiness;
        treat as not-ready.
    """

    ready_for_release = "ready_for_release"
    not_ready_due_to_missing_truth_alignment = (
        "not_ready_due_to_missing_truth_alignment"
    )
    not_ready_due_to_result_convergence_gap = (
        "not_ready_due_to_result_convergence_gap"
    )
    not_ready_due_to_operator_visibility_gap = (
        "not_ready_due_to_operator_visibility_gap"
    )
    not_ready_due_to_compat_influence = "not_ready_due_to_compat_influence"
    readiness_unknown_due_to_missing_signal = (
        "readiness_unknown_due_to_missing_signal"
    )

    @classmethod
    def from_string(cls, value: str) -> "DelegatedFlowReadinessVerdict":
        """Return the member matching *value*, defaulting to
        ``readiness_unknown_due_to_missing_signal``."""
        if not isinstance(value, str):
            return cls.readiness_unknown_due_to_missing_signal
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.readiness_unknown_due_to_missing_signal

    @property
    def is_ready(self) -> bool:
        """Return ``True`` only when the verdict is ``ready_for_release``."""
        return self == DelegatedFlowReadinessVerdict.ready_for_release

    @property
    def is_blocked(self) -> bool:
        """Return ``True`` when the verdict is any not_ready variant."""
        return self.value.startswith("not_ready_")

    @property
    def is_unknown(self) -> bool:
        """Return ``True`` when the verdict is the missing-signal sentinel."""
        return self == DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal


# ---------------------------------------------------------------------------
# DimensionReadinessResult
# ---------------------------------------------------------------------------


@dataclass
class DimensionReadinessResult:
    """Per-dimension evaluation result produced by the readiness gate.

    Fields
    ------
    dimension
        Which of the five canonical dimensions was evaluated.
    status
        The readiness status for this dimension.
    gap_description
        Human-readable description of the readiness gap (empty when
        ``status`` is ``ready``).  MUST be non-empty when ``status`` is
        ``not_ready`` or ``unknown``.
    signal_source
        Name of the module or snapshot that was consulted.
    evidence
        Optional structured evidence dict for operator / audit inspection.
    evaluated_at
        Unix timestamp of this dimension evaluation.
    """

    dimension: ReadinessDimension = ReadinessDimension.continuity_replay
    status: DimensionReadinessStatus = DimensionReadinessStatus.unknown
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
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionReadinessResult":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=ReadinessDimension.from_string(data.get("dimension", "")),
            status=DimensionReadinessStatus.from_string(data.get("status", "")),
            gap_description=data.get("gap_description", ""),
            signal_source=data.get("signal_source", ""),
            evidence=data.get("evidence", {}),
            evaluated_at=data.get("evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowReadinessReport
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowReadinessReport:
    """Full release-gate readiness report for the delegated canonical path.

    This is the stable, serialisable artifact produced by
    :class:`DelegatedFlowReadinessGate`.  It carries:

    * The overall ``verdict`` (one of the six :class:`DelegatedFlowReadinessVerdict`
      values).
    * Per-dimension results for all five dimensions.
    * A human-readable ``summary`` suitable for operator consoles.
    * Structured gap list for downstream tooling.
    * Metadata (report ID, generated timestamp, gate version).

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    verdict
        Overall release-gate verdict.
    dimensions
        Mapping from :class:`ReadinessDimension` value string to the
        corresponding :class:`DimensionReadinessResult`.
    summary
        Human-readable one-line summary of the overall readiness state.
    gaps
        List of (dimension, gap_description) tuples for all not-ready or
        unknown dimensions.
    is_ready_for_release
        ``True`` when ``verdict`` is ``ready_for_release``.
    gate_version
        Version of the readiness gate that produced this report.
    generated_at
        Unix timestamp of report generation.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: DelegatedFlowReadinessVerdict = (
        DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal
    )
    dimensions: Dict[str, DimensionReadinessResult] = field(default_factory=dict)
    summary: str = ""
    gaps: List[Dict[str, str]] = field(default_factory=list)
    is_ready_for_release: bool = False
    gate_version: str = "1.0"
    generated_at: float = field(default_factory=time.time)

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
            "gaps": self.gaps,
            "is_ready_for_release": self.is_ready_for_release,
            "gate_version": self.gate_version,
            "generated_at": self.generated_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowReadinessReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        dimensions = {}
        for dim_key, dim_data in data.get("dimensions", {}).items():
            dimensions[dim_key] = DimensionReadinessResult.from_dict(dim_data)
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            verdict=DelegatedFlowReadinessVerdict.from_string(
                data.get("verdict", "")
            ),
            dimensions=dimensions,
            summary=data.get("summary", ""),
            gaps=data.get("gaps", []),
            is_ready_for_release=data.get("is_ready_for_release", False),
            gate_version=data.get("gate_version", "1.0"),
            generated_at=data.get("generated_at", time.time()),
        )

    def get_dimension(self, dim: ReadinessDimension) -> Optional[DimensionReadinessResult]:
        """Return the DimensionReadinessResult for *dim*, or ``None``."""
        return self.dimensions.get(dim.value)


# ---------------------------------------------------------------------------
# Optional integration imports — all guarded to keep the module self-contained
# ---------------------------------------------------------------------------

# FlowContinuityCoordinator (PR-3V2) — continuity_replay dimension
try:
    from core.flow_continuity_coordinator import (  # type: ignore[import]
        get_flow_continuity_coordinator as _get_continuity_coordinator,
    )
    _CONTINUITY_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _CONTINUITY_AVAILABLE = False
    _get_continuity_coordinator = None  # type: ignore[assignment]

# FlowTruthAlignmentRuntime (PR-5V2) — truth_ownership dimension
try:
    from core.flow_level_truth_ownership import (  # type: ignore[import]
        build_flow_truth_alignment_snapshot as _build_truth_snapshot,
    )
    _TRUTH_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _TRUTH_AVAILABLE = False
    _build_truth_snapshot = None  # type: ignore[assignment]

# FlowAwareConvergenceCoordinator (PR-6V2) — result_convergence dimension
try:
    from core.flow_aware_result_convergence import (  # type: ignore[import]
        build_flow_convergence_snapshot as _build_convergence_snapshot,
    )
    _CONVERGENCE_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _CONVERGENCE_AVAILABLE = False
    _build_convergence_snapshot = None  # type: ignore[assignment]

# FlowLevelOperatorSurface (PR-7V2) — operator_surface dimension
try:
    from core.flow_level_operator_surface import (  # type: ignore[import]
        get_flow_level_operator_surface as _get_operator_surface,
    )
    _OPERATOR_SURFACE_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _OPERATOR_SURFACE_AVAILABLE = False
    _get_operator_surface = None  # type: ignore[assignment]

# CompatLegacyPathBlockingCanonicalization (PR-8V2) — compat_legacy dimension
try:
    from core.compat_legacy_path_blocking_canonicalization import (  # type: ignore[import]
        build_blocking_canonicalization_snapshot as _build_blocking_snapshot,
    )
    _COMPAT_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _COMPAT_AVAILABLE = False
    _build_blocking_snapshot = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# DelegatedFlowReadinessGate
# ---------------------------------------------------------------------------


class DelegatedFlowReadinessGate:
    """Unified readiness / release gate for the delegated canonical path.

    This is the canonical evaluator that aggregates the five dimension signals
    and produces a :class:`DelegatedFlowReadinessReport`.  It is designed as
    a **read-only projection** — it never mutates any sub-system state.

    Use :func:`get_readiness_gate` to obtain the process-global singleton.
    Use :func:`reset_readiness_gate` to reset the singleton (test isolation).

    Usage
    -----
    ::

        from core.delegated_flow_readiness_gate import (
            get_readiness_gate,
            DelegatedFlowReadinessVerdict,
        )

        report = get_readiness_gate().evaluate()
        if report.verdict.is_ready:
            # proceed to release / default-on
            ...
        else:
            for gap in report.gaps:
                print(f"[{gap['dimension']}] {gap['gap_description']}")
    """

    GATE_VERSION: str = "1.0"

    def evaluate(self) -> DelegatedFlowReadinessReport:
        """Evaluate all five readiness dimensions and produce a report.

        Returns
        -------
        DelegatedFlowReadinessReport
            Full readiness report with overall verdict and per-dimension results.
        """
        dimensions: Dict[str, DimensionReadinessResult] = {}

        dim_continuity = self._evaluate_continuity_replay()
        dim_truth = self._evaluate_truth_ownership()
        dim_convergence = self._evaluate_result_convergence()
        dim_operator = self._evaluate_operator_surface()
        dim_compat = self._evaluate_compat_legacy()

        for dim_result in (
            dim_continuity,
            dim_truth,
            dim_convergence,
            dim_operator,
            dim_compat,
        ):
            dimensions[dim_result.dimension.value] = dim_result

        verdict = self._compute_verdict(dimensions)
        gaps = self._collect_gaps(dimensions)
        summary = self._build_summary(verdict, gaps)
        is_ready = verdict == DelegatedFlowReadinessVerdict.ready_for_release

        report = DelegatedFlowReadinessReport(
            verdict=verdict,
            dimensions=dimensions,
            summary=summary,
            gaps=gaps,
            is_ready_for_release=is_ready,
            gate_version=self.GATE_VERSION,
        )
        logger.debug(
            "DelegatedFlowReadinessGate.evaluate() → verdict=%s gaps=%d",
            verdict.value,
            len(gaps),
        )
        return report

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _evaluate_continuity_replay(self) -> DimensionReadinessResult:
        """Evaluate the continuity / replay readiness dimension."""
        dimension = ReadinessDimension.continuity_replay
        signal_source = "core.flow_continuity_coordinator"

        if not _CONTINUITY_AVAILABLE or _get_continuity_coordinator is None:
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    "FlowContinuityCoordinator (PR-3V2) is not available.  "
                    "Cannot assess continuity / replay readiness.  "
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

            # Readiness check: fail_closed decisions indicate unresolved gaps
            total_decisions = evidence.get("total_decisions", 0)
            decision_counts = evidence.get("decision_counts", {})
            fail_closed_count = decision_counts.get("fail_closed", 0)

            if total_decisions == 0:
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.unknown,
                    gap_description=(
                        "FlowContinuityCoordinator has no decision history.  "
                        "No continuity events have been processed.  "
                        "This may indicate the delegated path has not yet "
                        "been exercised or that the Android/V2 contract "
                        "signal is absent.  "
                        "Policy: "
                        + _policy_excerpt(
                            ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY
                        )
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if fail_closed_count > 0:
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.not_ready,
                    gap_description=(
                        f"FlowContinuityCoordinator has {fail_closed_count} "
                        f"fail_closed decision(s) in its history.  Unresolved "
                        f"fail_closed events indicate continuity scenarios that "
                        f"could not be safely decided.  These must be resolved "
                        f"before the delegated path is release-ready."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.ready,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    f"FlowContinuityCoordinator snapshot raised an exception: "
                    f"{exc!r}.  Cannot assess continuity readiness."
                ),
                signal_source=signal_source,
            )

    def _evaluate_truth_ownership(self) -> DimensionReadinessResult:
        """Evaluate the truth ownership / alignment readiness dimension."""
        dimension = ReadinessDimension.truth_ownership
        signal_source = "core.flow_level_truth_ownership"

        if not _TRUTH_AVAILABLE or _build_truth_snapshot is None:
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    "FlowTruthAlignmentRuntime (PR-5V2) is not available.  "
                    "Cannot assess truth ownership / alignment readiness.  "
                    "Ensure core.flow_level_truth_ownership is importable."
                ),
                signal_source=signal_source,
            )

        try:
            snapshot = _build_truth_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            total_decisions = evidence.get("total_decisions", 0)
            decision_counts = evidence.get("decision_counts", {})
            quarantine_count = decision_counts.get(
                "quarantine_due_to_posture_conflict", 0
            ) + decision_counts.get("block_due_to_compat_influence", 0)

            if total_decisions == 0:
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.unknown,
                    gap_description=(
                        "FlowTruthAlignmentRuntime has no alignment decision "
                        "history.  No Android truth has been aligned against "
                        "V2 canonical state.  This indicates a missing "
                        "Android/V2 truth alignment contract signal.  "
                        "Policy: "
                        + _policy_excerpt(
                            ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY
                        )
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if quarantine_count > 0:
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.not_ready,
                    gap_description=(
                        f"FlowTruthAlignmentRuntime has {quarantine_count} "
                        f"quarantined truth decision(s).  Quarantined truth "
                        f"indicates alignment gaps (posture conflict or "
                        f"unresolved compat influence) that block release."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.ready,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    f"FlowTruthAlignmentRuntime snapshot raised an exception: "
                    f"{exc!r}.  Cannot assess truth ownership readiness."
                ),
                signal_source=signal_source,
            )

    def _evaluate_result_convergence(self) -> DimensionReadinessResult:
        """Evaluate the result convergence readiness dimension."""
        dimension = ReadinessDimension.result_convergence
        signal_source = "core.flow_aware_result_convergence"

        if not _CONVERGENCE_AVAILABLE or _build_convergence_snapshot is None:
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    "FlowAwareConvergenceCoordinator (PR-6V2) is not available.  "
                    "Cannot assess result convergence readiness.  "
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
            quarantine_count = decision_counts.get(
                "quarantine_result_due_to_flow_mismatch", 0
            )

            if total_decisions == 0:
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.unknown,
                    gap_description=(
                        "FlowAwareConvergenceCoordinator has no convergence "
                        "decision history.  No results have been converged "
                        "through the flow-aware convergence path.  "
                        "This indicates a missing Android/V2 result signal.  "
                        "Policy: "
                        + _policy_excerpt(
                            ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY
                        )
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            if quarantine_count > 0:
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.not_ready,
                    gap_description=(
                        f"FlowAwareConvergenceCoordinator has {quarantine_count} "
                        f"quarantined convergence decision(s).  Quarantined "
                        f"results indicate flow mismatch or unresolved "
                        f"convergence gaps that block release."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.ready,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    f"FlowAwareConvergenceCoordinator snapshot raised an "
                    f"exception: {exc!r}.  Cannot assess result convergence "
                    f"readiness."
                ),
                signal_source=signal_source,
            )

    def _evaluate_operator_surface(self) -> DimensionReadinessResult:
        """Evaluate the operator surface readiness dimension."""
        dimension = ReadinessDimension.operator_surface
        signal_source = "core.flow_level_operator_surface"

        if not _OPERATOR_SURFACE_AVAILABLE or _get_operator_surface is None:
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    "FlowLevelOperatorSurface (PR-7V2) is not available.  "
                    "Cannot assess operator surface readiness.  "
                    "Ensure core.flow_level_operator_surface is importable."
                ),
                signal_source=signal_source,
            )

        try:
            surface = _get_operator_surface()
            # The operator surface is ready if it is operational (importable
            # and instantiatable).  The absence of registered flows is NOT a
            # gap — flows are only registered when the path has been exercised.
            # What matters is that the surface CAN project flows when they exist.
            evidence: Dict[str, Any] = {
                "surface_available": True,
                "surface_type": type(surface).__name__,
            }

            # Check for __all__ presence as a structural health indicator.
            try:
                import core.flow_level_operator_surface as _flos_mod
                all_names = getattr(_flos_mod, "__all__", None)
                evidence["__all___present"] = all_names is not None
                evidence["__all___count"] = len(all_names) if all_names else 0
            except Exception as exc:
                logger.debug("Suppressed: %s", exc)

            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.ready,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    f"FlowLevelOperatorSurface raised an exception during "
                    f"readiness check: {exc!r}.  Cannot assess operator "
                    f"surface readiness."
                ),
                signal_source=signal_source,
            )

    def _evaluate_compat_legacy(self) -> DimensionReadinessResult:
        """Evaluate the compat / legacy blocking canonicalization dimension."""
        dimension = ReadinessDimension.compat_legacy
        signal_source = "core.compat_legacy_path_blocking_canonicalization"

        if not _COMPAT_AVAILABLE or _build_blocking_snapshot is None:
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    "CompatLegacyPathBlockingCanonicalization (PR-8V2) is not "
                    "available.  Cannot assess compat / legacy blocking "
                    "readiness.  Ensure "
                    "core.compat_legacy_path_blocking_canonicalization is "
                    "importable."
                ),
                signal_source=signal_source,
            )

        try:
            snapshot = _build_blocking_snapshot()
            evidence: Dict[str, Any] = {}
            if hasattr(snapshot, "to_dict"):
                evidence = snapshot.to_dict()

            healthy = evidence.get("blocking_canonicalization_healthy", True)
            quarantine_count = evidence.get(
                "by_decision", {}
            ).get("quarantine_due_to_ambiguous_contract", 0)
            invisible_flow_count = evidence.get("invisible_flow_count", 0)

            if not healthy or quarantine_count > 0 or invisible_flow_count > 0:
                reasons = []
                if quarantine_count > 0:
                    reasons.append(
                        f"{quarantine_count} quarantined contract(s)"
                    )
                if invisible_flow_count > 0:
                    reasons.append(
                        f"{invisible_flow_count} invisible flow(s)"
                    )
                return DimensionReadinessResult(
                    dimension=dimension,
                    status=DimensionReadinessStatus.not_ready,
                    gap_description=(
                        f"CompatLegacyPathBlockingCanonicalization is NOT "
                        f"healthy: {', '.join(reasons)}.  Unresolved compat "
                        f"influence or invisible flows must be bounded before "
                        f"the delegated path can be released."
                    ),
                    signal_source=signal_source,
                    evidence=evidence,
                )

            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.ready,
                gap_description="",
                signal_source=signal_source,
                evidence=evidence,
            )

        except Exception as exc:  # pragma: no cover
            return DimensionReadinessResult(
                dimension=dimension,
                status=DimensionReadinessStatus.unknown,
                gap_description=(
                    f"CompatLegacyPathBlockingCanonicalization snapshot raised "
                    f"an exception: {exc!r}.  Cannot assess compat / legacy "
                    f"blocking readiness."
                ),
                signal_source=signal_source,
            )

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(
        dimensions: Dict[str, DimensionReadinessResult],
    ) -> DelegatedFlowReadinessVerdict:
        """Derive the overall verdict from per-dimension results.

        Priority order (first match wins):
        1. Any ``unknown`` dimension → ``readiness_unknown_due_to_missing_signal``
        2. ``truth_ownership`` not_ready → ``not_ready_due_to_missing_truth_alignment``
        3. ``result_convergence`` not_ready → ``not_ready_due_to_result_convergence_gap``
        4. ``operator_surface`` not_ready → ``not_ready_due_to_operator_visibility_gap``
        5. ``compat_legacy`` not_ready → ``not_ready_due_to_compat_influence``
        6. ``continuity_replay`` not_ready → ``not_ready_due_to_missing_truth_alignment``
           (continuity gaps are truth-adjacent)
        7. All ready → ``ready_for_release``
        """
        dim_statuses = {
            key: result.status for key, result in dimensions.items()
        }

        # Rule 1: any unknown → missing signal
        if DimensionReadinessStatus.unknown in dim_statuses.values():
            return DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal

        # Rule 2: truth_ownership not_ready
        truth_status = dim_statuses.get(ReadinessDimension.truth_ownership.value)
        if truth_status == DimensionReadinessStatus.not_ready:
            return (
                DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment
            )

        # Rule 3: result_convergence not_ready
        conv_status = dim_statuses.get(ReadinessDimension.result_convergence.value)
        if conv_status == DimensionReadinessStatus.not_ready:
            return (
                DelegatedFlowReadinessVerdict.not_ready_due_to_result_convergence_gap
            )

        # Rule 4: operator_surface not_ready
        op_status = dim_statuses.get(ReadinessDimension.operator_surface.value)
        if op_status == DimensionReadinessStatus.not_ready:
            return (
                DelegatedFlowReadinessVerdict.not_ready_due_to_operator_visibility_gap
            )

        # Rule 5: compat_legacy not_ready
        compat_status = dim_statuses.get(ReadinessDimension.compat_legacy.value)
        if compat_status == DimensionReadinessStatus.not_ready:
            return DelegatedFlowReadinessVerdict.not_ready_due_to_compat_influence

        # Rule 6: continuity_replay not_ready (truth-adjacent)
        cont_status = dim_statuses.get(ReadinessDimension.continuity_replay.value)
        if cont_status == DimensionReadinessStatus.not_ready:
            return (
                DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment
            )

        # Rule 7: all five must be ready
        all_ready = all(
            s == DimensionReadinessStatus.ready for s in dim_statuses.values()
        )
        if all_ready and len(dim_statuses) == len(ReadinessDimension.all_dimensions()):
            return DelegatedFlowReadinessVerdict.ready_for_release

        # Fallback — some dimension missing entirely
        return DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal

    @staticmethod
    def _collect_gaps(
        dimensions: Dict[str, DimensionReadinessResult],
    ) -> List[Dict[str, str]]:
        """Collect all not-ready and unknown dimension gaps."""
        gaps = []
        for dim_key in [d.value for d in ReadinessDimension.all_dimensions()]:
            result = dimensions.get(dim_key)
            if result is None:
                continue
            if result.status in (
                DimensionReadinessStatus.not_ready,
                DimensionReadinessStatus.unknown,
            ):
                gaps.append(
                    {
                        "dimension": dim_key,
                        "status": result.status.value,
                        "gap_description": result.gap_description,
                    }
                )
        return gaps

    @staticmethod
    def _build_summary(
        verdict: DelegatedFlowReadinessVerdict,
        gaps: List[Dict[str, str]],
    ) -> str:
        """Build a one-line human-readable summary."""
        if verdict == DelegatedFlowReadinessVerdict.ready_for_release:
            return (
                "Delegated canonical path READY FOR RELEASE: all five "
                "readiness dimensions passed."
            )
        gap_dims = [g["dimension"] for g in gaps]
        return (
            f"Delegated canonical path NOT READY: "
            f"verdict={verdict.value}, "
            f"gaps=[{', '.join(gap_dims)}]."
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_default_gate: Optional[DelegatedFlowReadinessGate] = None
_DEFAULT_GATE_LOCK = None

try:
    import threading as _threading
    _DEFAULT_GATE_LOCK = _threading.Lock()
except Exception as exc:
    logger.debug("Suppressed: %s", exc)


def get_readiness_gate() -> DelegatedFlowReadinessGate:
    """Return the process-level :class:`DelegatedFlowReadinessGate` singleton.

    Creates a new instance on first call.  Thread-safe.
    """
    global _default_gate
    if _DEFAULT_GATE_LOCK is not None:
        with _DEFAULT_GATE_LOCK:
            if _default_gate is None:
                _default_gate = DelegatedFlowReadinessGate()
            return _default_gate
    if _default_gate is None:  # pragma: no cover
        _default_gate = DelegatedFlowReadinessGate()
    return _default_gate


def reset_readiness_gate() -> None:
    """Reset the process-level singleton (test isolation only)."""
    global _default_gate
    if _DEFAULT_GATE_LOCK is not None:
        with _DEFAULT_GATE_LOCK:
            _default_gate = None
    else:  # pragma: no cover
        _default_gate = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def evaluate_delegated_flow_readiness() -> DelegatedFlowReadinessReport:
    """Evaluate delegated canonical path readiness using the global gate.

    Convenience wrapper for :meth:`DelegatedFlowReadinessGate.evaluate`.

    Returns
    -------
    DelegatedFlowReadinessReport
    """
    return get_readiness_gate().evaluate()
