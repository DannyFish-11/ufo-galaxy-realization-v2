#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.architecture_completion — Architecture Completion Evaluation Framework
============================================================================

PR-9 — Formalize architecture completion evaluation dimensions and scorecard.

This module provides the **canonical evaluation framework** for assessing the
completion and maturity of the Galaxy architecture migration.  It defines the
dimensions used to measure project completion and supplies a structured
scorecard / diagnostic surface so that current completion state can be
reported, updated, and compared consistently across PRs.

## Why this module exists

After a sequence of architecture-normalization PRs (canonical dispatcher,
capability catalog, node classification, GitHub-installable MCP/Skill
contracts, execution authority tightening, cross-device chain
canonicalization, and projection-only UI demotion) there is still no single
explicit framework for evaluating *project completion / architecture
completion* across these dimensions.

This module fills that gap.  Contributors can:

- Read the current scorecard to see which dimensions are complete vs
  in-progress vs have legacy ambiguity.
- Update individual dimension scores after major architecture PRs.
- Understand *why* a dimension is at a given maturity level.
- Surface the scorecard as JSON from a diagnostic route.

## Evaluation dimensions

Ten canonical dimensions are defined:

1. **authority_clarity** — Are decision/execution/projection authority
   boundaries explicit and enforced?
2. **canonical_path_coverage** — Does each subsystem have a single canonical
   path?  Are bypasses demoted or removed?
3. **legacy_surface_demotion** — Are historical/compatibility components
   clearly marked as non-primary?
4. **contract_schema_normalization** — Are inputs/outputs described by
   canonical contracts and validated?
5. **capability_integration_completeness** — Are MCP/Skill/Node/Gateway
   capabilities integrated through the canonical catalog?
6. **projection_outward_truth_alignment** — Is outward system status driven
   by projection rather than parallel UI/state surfaces?
7. **cross_device_execution_consistency** — Does cross-device behaviour follow
   the canonical execution chain?
8. **installability_ecosystem_readiness** — Are GitHub-installable MCP/Skill
   addon contracts stable and documented?
9. **diagnostics_observability_maturity** — Can the system explain its current
   architecture state, legacy zones, and canonical paths?
10. **test_coverage_architecture_invariants** — Are major architectural
    guarantees covered by tests?

## Main API

:func:`build_architecture_completion_scorecard`
    Build a full :class:`ArchitectureCompletionScorecard` from a dimension
    evidence dict (or use built-in defaults reflecting PR-1 through PR-9
    history).

:func:`get_architecture_completion_scorecard`
    Convenience entry point returning the built-in scorecard.

:class:`ArchitectureCompletionScorecard`
    The top-level scorecard container — JSON-serialisable, printable.

:class:`DimensionScorecard`
    Per-dimension score record with maturity level, rationale, flags, and
    recommended next steps.

:class:`MaturityLevel`
    Five-tier maturity enum: LEGACY_AMBIGUITY → IN_PROGRESS → PARTIAL →
    CANONICALIZED → COMPLETE.

Usage::

    from core.architecture_completion import (
        get_architecture_completion_scorecard,
        build_architecture_completion_scorecard,
        MaturityLevel,
        CompletionDimension,
    )

    scorecard = get_architecture_completion_scorecard()
    print(scorecard.overall_completion_pct)

    for dim_sc in scorecard.dimensions:
        if dim_sc.legacy_ambiguity_remains:
            print(f"Legacy ambiguity: {dim_sc.dimension}")
"""

from __future__ import annotations

import dataclasses
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ArchCompletion")

__all__ = [
    # Enums
    "MaturityLevel",
    "CompletionDimension",
    # Data types
    "DimensionScorecard",
    "ArchitectureCompletionScorecard",
    # Builders
    "build_dimension_scorecard",
    "build_architecture_completion_scorecard",
    # Entry point
    "get_architecture_completion_scorecard",
    # Constants
    "ALL_DIMENSIONS",
    "DIMENSION_DESCRIPTIONS",
]


# ---------------------------------------------------------------------------
# MaturityLevel enum
# ---------------------------------------------------------------------------


class MaturityLevel(str, Enum):
    """Five-tier maturity classification for a single completion dimension.

    Tiers are ordered from lowest to highest maturity:

    ``LEGACY_AMBIGUITY``
        Parallel authority paths exist; the canonical path is not the only
        operative path; legacy components still define or influence system
        structure.

    ``IN_PROGRESS``
        Migration has started but the canonical path is not yet fully
        established.  Legacy components may still be actively invoked.

    ``PARTIAL``
        The canonical path exists and is the primary path.  Some bypass or
        compatibility surfaces remain but are marked as non-primary.

    ``CANONICALIZED``
        The canonical path is the sole operative path.  Legacy surfaces are
        demoted, guardrailed, or removed.  No parallel authority paths remain.
        Contracts are defined.

    ``COMPLETE``
        Canonical path established, contracts stable, invariants covered by
        tests, documentation in place, and the dimension is considered fully
        closed.
    """

    LEGACY_AMBIGUITY = "legacy_ambiguity"
    IN_PROGRESS = "in_progress"
    PARTIAL = "partial"
    CANONICALIZED = "canonicalized"
    COMPLETE = "complete"

    def ordinal(self) -> int:
        """Return a numeric ordinal (0 = lowest, 4 = highest) for comparisons."""
        _order = {
            MaturityLevel.LEGACY_AMBIGUITY: 0,
            MaturityLevel.IN_PROGRESS: 1,
            MaturityLevel.PARTIAL: 2,
            MaturityLevel.CANONICALIZED: 3,
            MaturityLevel.COMPLETE: 4,
        }
        return _order[self]

    def is_blocking(self) -> bool:
        """Return True when this level represents a blocking / legacy state."""
        return self in (MaturityLevel.LEGACY_AMBIGUITY, MaturityLevel.IN_PROGRESS)


# ---------------------------------------------------------------------------
# CompletionDimension enum
# ---------------------------------------------------------------------------


class CompletionDimension(str, Enum):
    """Canonical evaluation dimensions for architecture completion.

    Each value is the machine-readable identifier used in scorecard records
    and JSON output.
    """

    AUTHORITY_CLARITY = "authority_clarity"
    CANONICAL_PATH_COVERAGE = "canonical_path_coverage"
    LEGACY_SURFACE_DEMOTION = "legacy_surface_demotion"
    CONTRACT_SCHEMA_NORMALIZATION = "contract_schema_normalization"
    CAPABILITY_INTEGRATION_COMPLETENESS = "capability_integration_completeness"
    PROJECTION_OUTWARD_TRUTH_ALIGNMENT = "projection_outward_truth_alignment"
    CROSS_DEVICE_EXECUTION_CONSISTENCY = "cross_device_execution_consistency"
    INSTALLABILITY_ECOSYSTEM_READINESS = "installability_ecosystem_readiness"
    DIAGNOSTICS_OBSERVABILITY_MATURITY = "diagnostics_observability_maturity"
    TEST_COVERAGE_ARCHITECTURE_INVARIANTS = "test_coverage_architecture_invariants"


#: Ordered list of all canonical dimensions used in default scorecard iteration.
ALL_DIMENSIONS: List[CompletionDimension] = list(CompletionDimension)

#: Human-readable description of each dimension.
#:
#: This mapping provides a concise prose description for every
#: :class:`CompletionDimension` value.  It is used in generated documentation,
#: JSON scorecard output, and diagnostic tooling that needs to explain *what* a
#: dimension measures without requiring callers to read the full module docs.
#:
#: Keys are :class:`CompletionDimension` enum members; values are non-empty
#: strings describing the dimension's evaluation intent.
DIMENSION_DESCRIPTIONS: Dict[CompletionDimension, str] = {
    CompletionDimension.AUTHORITY_CLARITY: (
        "Ownership of decision, execution, and projection authority is explicit "
        "and enforced in code and documentation.  No layer claims an authority "
        "role that belongs to another layer."
    ),
    CompletionDimension.CANONICAL_PATH_COVERAGE: (
        "Each subsystem has a single canonical entry-point path.  Bypass paths "
        "are demoted or removed; the canonical path is the only operative route "
        "for new code."
    ),
    CompletionDimension.LEGACY_SURFACE_DEMOTION: (
        "Historical and compatibility components are clearly marked as "
        "non-primary surfaces.  They carry guardrails, deprecation notices, and "
        "pointers to canonical replacements."
    ),
    CompletionDimension.CONTRACT_SCHEMA_NORMALIZATION: (
        "Inputs and outputs across subsystem boundaries are described by "
        "canonical contracts (Pydantic models or dataclasses) and are validated "
        "at runtime or in tests."
    ),
    CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS: (
        "MCP, Skill, Node, and Gateway capabilities are integrated exclusively "
        "through the canonical capability catalog.  No capability is registered "
        "or invoked via a parallel path."
    ),
    CompletionDimension.PROJECTION_OUTWARD_TRUTH_ALIGNMENT: (
        "Outward system status is driven exclusively by the canonical projection "
        "layer.  No parallel UI surface or state maintains its own truth about "
        "system state."
    ),
    CompletionDimension.CROSS_DEVICE_EXECUTION_CONSISTENCY: (
        "Cross-device behaviour follows the canonical execution chain defined "
        "by CrossDeviceChainSnapshot.  Legacy multi-device coordinators are "
        "guardrailed and demoted."
    ),
    CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS: (
        "GitHub-installable MCP and Skill addon contracts are stable, "
        "documented, and validated.  Third-party extensions can be installed "
        "and discovered without modifying core code."
    ),
    CompletionDimension.DIAGNOSTICS_OBSERVABILITY_MATURITY: (
        "The system can explain its current architecture state, canonical paths, "
        "legacy zones, authority chain, and completion status through structured "
        "diagnostic output."
    ),
    CompletionDimension.TEST_COVERAGE_ARCHITECTURE_INVARIANTS: (
        "Major architectural guarantees (authority chain, boundary invariants, "
        "canonical path ownership, legacy surface demotion, projection truth) "
        "are covered by dedicated tests."
    ),
}


# ---------------------------------------------------------------------------
# DimensionScorecard dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DimensionScorecard:
    """Per-dimension completion record.

    Attributes
    ----------
    dimension:
        :class:`CompletionDimension` this record describes.
    maturity_level:
        Current :class:`MaturityLevel` for this dimension.
    canonical_path_established:
        ``True`` when there is a single canonical path for this dimension and
        it is the operative path for new code.
    legacy_ambiguity_remains:
        ``True`` when parallel authority paths or non-guardrailed legacy
        surfaces still exist for this dimension.
    rationale:
        Human-readable explanation of why this dimension is at the current
        maturity level.
    evidence_modules:
        List of dotted module paths or file paths that serve as evidence for
        the current score (e.g. canonical modules and legacy entries).
    blockers:
        Optional list of concrete blockers preventing the next maturity tier.
    recommended_next_actions:
        Optional list of concrete steps to advance this dimension.
    pr_last_updated:
        Identifier of the PR that most recently changed the score for this
        dimension (e.g. ``"PR-8"``).
    """

    dimension: CompletionDimension
    maturity_level: MaturityLevel
    canonical_path_established: bool
    legacy_ambiguity_remains: bool
    rationale: str
    evidence_modules: List[str] = dataclasses.field(default_factory=list)
    blockers: Optional[List[str]] = None
    recommended_next_actions: Optional[List[str]] = None
    pr_last_updated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "dimension": self.dimension.value
            if isinstance(self.dimension, CompletionDimension)
            else self.dimension,
            "maturity_level": self.maturity_level.value
            if isinstance(self.maturity_level, MaturityLevel)
            else self.maturity_level,
            "canonical_path_established": self.canonical_path_established,
            "legacy_ambiguity_remains": self.legacy_ambiguity_remains,
            "rationale": self.rationale,
            "evidence_modules": list(self.evidence_modules),
            "blockers": list(self.blockers) if self.blockers else [],
            "recommended_next_actions": list(self.recommended_next_actions)
            if self.recommended_next_actions
            else [],
            "pr_last_updated": self.pr_last_updated,
        }


# ---------------------------------------------------------------------------
# ArchitectureCompletionScorecard dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ArchitectureCompletionScorecard:
    """Top-level architecture completion scorecard.

    Aggregates per-dimension scores and derives summary statistics.

    Attributes
    ----------
    dimensions:
        Ordered list of :class:`DimensionScorecard` records — one per
        :class:`CompletionDimension`.
    overall_completion_pct:
        Float in [0.0, 100.0] representing the percentage of dimensions at
        :attr:`MaturityLevel.CANONICALIZED` or :attr:`MaturityLevel.COMPLETE`.
    canonical_count:
        Number of dimensions at CANONICALIZED or COMPLETE.
    legacy_ambiguity_count:
        Number of dimensions that still have ``legacy_ambiguity_remains=True``.
    blocking_count:
        Number of dimensions whose maturity level is LEGACY_AMBIGUITY or
        IN_PROGRESS (i.e. :meth:`MaturityLevel.is_blocking` is True).
    total_dimensions:
        Total number of dimensions in the scorecard.
    scorecard_version:
        Monotonic string version for the scorecard format (e.g. ``"1.0"``).
    generated_by_pr:
        PR that last produced this scorecard (e.g. ``"PR-9"``).
    """

    dimensions: List[DimensionScorecard]
    overall_completion_pct: float = 0.0
    canonical_count: int = 0
    legacy_ambiguity_count: int = 0
    blocking_count: int = 0
    total_dimensions: int = 0
    scorecard_version: str = "1.0"
    generated_by_pr: str = "PR-10"

    def __post_init__(self) -> None:
        self._recompute_summary()

    def _recompute_summary(self) -> None:
        """Recompute aggregate fields from the dimensions list."""
        total = len(self.dimensions)
        canonical = sum(
            1
            for d in self.dimensions
            if d.maturity_level in (MaturityLevel.CANONICALIZED, MaturityLevel.COMPLETE)
        )
        ambiguous = sum(1 for d in self.dimensions if d.legacy_ambiguity_remains)
        blocking = sum(
            1 for d in self.dimensions if d.maturity_level.is_blocking()
        )
        self.total_dimensions = total
        self.canonical_count = canonical
        self.legacy_ambiguity_count = ambiguous
        self.blocking_count = blocking
        self.overall_completion_pct = (canonical / total * 100.0) if total > 0 else 0.0

    def dimension_by_name(
        self, dim: CompletionDimension
    ) -> Optional[DimensionScorecard]:
        """Return the :class:`DimensionScorecard` for *dim*, or ``None``."""
        for d in self.dimensions:
            if d.dimension == dim:
                return d
        return None

    def legacy_ambiguity_dimensions(self) -> List[DimensionScorecard]:
        """Return all dimensions that still have legacy ambiguity."""
        return [d for d in self.dimensions if d.legacy_ambiguity_remains]

    def canonicalized_dimensions(self) -> List[DimensionScorecard]:
        """Return all dimensions at CANONICALIZED or COMPLETE maturity."""
        return [
            d
            for d in self.dimensions
            if d.maturity_level in (MaturityLevel.CANONICALIZED, MaturityLevel.COMPLETE)
        ]

    def blocking_dimensions(self) -> List[DimensionScorecard]:
        """Return all dimensions whose maturity is LEGACY_AMBIGUITY or IN_PROGRESS."""
        return [d for d in self.dimensions if d.maturity_level.is_blocking()]

    def summary_lines(self) -> List[str]:
        """Return a compact human-readable summary as a list of lines."""
        lines = [
            f"Architecture Completion Scorecard  (v{self.scorecard_version}, "
            f"generated by {self.generated_by_pr})",
            f"  Overall completion : {self.overall_completion_pct:.1f}% "
            f"({self.canonical_count}/{self.total_dimensions} dimensions canonicalized)",
            f"  Legacy ambiguity   : {self.legacy_ambiguity_count} dimension(s)",
            f"  Blocking           : {self.blocking_count} dimension(s)",
            "",
        ]
        for d in self.dimensions:
            marker = "✓" if d.canonical_path_established else "✗"
            legacy = " [legacy ambiguity]" if d.legacy_ambiguity_remains else ""
            dim_name = (
                d.dimension.value
                if isinstance(d.dimension, CompletionDimension)
                else d.dimension
            )
            level = (
                d.maturity_level.value
                if isinstance(d.maturity_level, MaturityLevel)
                else d.maturity_level
            )
            lines.append(f"  {marker} {dim_name:<50} {level}{legacy}")
        return lines

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "scorecard_version": self.scorecard_version,
            "generated_by_pr": self.generated_by_pr,
            "overall_completion_pct": round(self.overall_completion_pct, 2),
            "canonical_count": self.canonical_count,
            "legacy_ambiguity_count": self.legacy_ambiguity_count,
            "blocking_count": self.blocking_count,
            "total_dimensions": self.total_dimensions,
            "dimensions": [d.to_dict() for d in self.dimensions],
        }

    def to_json(self, **kwargs: Any) -> str:
        """Serialise the scorecard to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def build_dimension_scorecard(
    dimension: CompletionDimension,
    maturity_level: MaturityLevel,
    *,
    canonical_path_established: bool,
    legacy_ambiguity_remains: bool,
    rationale: str,
    evidence_modules: Optional[List[str]] = None,
    blockers: Optional[List[str]] = None,
    recommended_next_actions: Optional[List[str]] = None,
    pr_last_updated: Optional[str] = None,
) -> DimensionScorecard:
    """Construct a :class:`DimensionScorecard` with validated fields.

    Parameters
    ----------
    dimension:
        The :class:`CompletionDimension` being scored.
    maturity_level:
        The current :class:`MaturityLevel` for this dimension.
    canonical_path_established:
        ``True`` when a single canonical path exists and is operative.
    legacy_ambiguity_remains:
        ``True`` when parallel authority or un-guardrailed legacy surfaces
        still exist.
    rationale:
        Human-readable explanation of the current score.
    evidence_modules:
        Optional list of module/file paths that serve as evidence.
    blockers:
        Optional list of blockers preventing the next tier.
    recommended_next_actions:
        Optional list of concrete next steps.
    pr_last_updated:
        Optional PR identifier for when this score was last changed.
    """
    return DimensionScorecard(
        dimension=dimension,
        maturity_level=maturity_level,
        canonical_path_established=canonical_path_established,
        legacy_ambiguity_remains=legacy_ambiguity_remains,
        rationale=rationale,
        evidence_modules=list(evidence_modules) if evidence_modules else [],
        blockers=list(blockers) if blockers else None,
        recommended_next_actions=list(recommended_next_actions)
        if recommended_next_actions
        else None,
        pr_last_updated=pr_last_updated,
    )


# ---------------------------------------------------------------------------
# Built-in scorecard reflecting PR-1 through PR-10 history
# ---------------------------------------------------------------------------


def _build_default_dimensions() -> List[DimensionScorecard]:
    """Build the default dimension scores reflecting the PR-1 through PR-10
    architecture history.

    This is the baseline scorecard updated by PR-10 consolidation.  Future PRs
    should update the relevant dimension(s) by calling
    :func:`build_architecture_completion_scorecard` with an overrides dict.
    """
    dims: List[DimensionScorecard] = []

    # 1. Authority Clarity
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.AUTHORITY_CLARITY,
            MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-1 established the canonical authority chain "
                "(DesktopPresenceRuntime → OpenClawd → AgentKernel → CommandRouter). "
                "PR-6 tightened the OpenClawd–AgentKernel execution contract. "
                "PR-10 added architecture diagnostics to enforce boundary invariants. "
                "PR-28 added hard truth-ownership guards. "
                "Authority roles are explicit and validated."
            ),
            evidence_modules=[
                "core.desktop_presence_runtime",
                "core.openclawd",
                "core.agent.kernel",
                "core.command_router",
                "core.architecture_diagnostics",
                "core.architecture_truth_guards",
            ],
            pr_last_updated="PR-9",
        )
    )

    # 2. Canonical Path Coverage
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.CANONICAL_PATH_COVERAGE,
            MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-1 established the canonical dispatcher (ConstellationRuntime). "
                "PR-9 added orchestration-authority consolidation with a structured "
                "legacy-path registry. Canonical entry paths are defined and legacy "
                "bypasses are guardrailed via orchestration_authority/legacy_paths.py."
            ),
            evidence_modules=[
                "core.constellation_runtime",
                "core.e2e_orchestrator",
                "core.orchestration_authority.legacy_paths",
            ],
            pr_last_updated="PR-9",
        )
    )

    # 3. Legacy Surface Demotion
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.LEGACY_SURFACE_DEMOTION,
            MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-8 formally demoted dashboard/ (LEGACY_UI) and windows_client/ "
                "(LEGACY_SHELL) via UISurfaceAuthorityRegistry. PR-9 added "
                "legacy-path registry entries for orchestration surfaces. "
                "All demoted surfaces carry guardrails and superseded_by pointers."
            ),
            evidence_modules=[
                "core.ui_surface_authority",
                "core.orchestration_authority.legacy_paths",
                "dashboard",
                "enhancements.clients.windows_client",
            ],
            pr_last_updated="PR-8",
        )
    )

    # 4. Contract / Schema Normalization
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.CONTRACT_SCHEMA_NORMALIZATION,
            MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-11 added ExecutionPlan schema. PR-21 added UnifiedExecutionDecision "
                "and FallbackDecisionRecord. PR-22 added DesktopStatusProjection contract. "
                "Key subsystem boundaries are described by Pydantic contracts or frozen "
                "dataclasses. Some peripheral modules still use plain dicts."
            ),
            evidence_modules=[
                "core.schemas.unified_control_plan",
                "core.schemas.execution_plan",
                "contracts.desktop_status_projection",
                "core.orchestration_authority.legacy_paths",
            ],
            recommended_next_actions=[
                "Audit remaining plain-dict boundaries and add Pydantic contracts.",
            ],
            pr_last_updated="PR-22",
        )
    )

    # 5. Capability Integration Completeness
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS,
            MaturityLevel.PARTIAL,
            canonical_path_established=True,
            legacy_ambiguity_remains=True,
            rationale=(
                "PR-2 added the canonical capability catalog. PR-3 added node "
                "classification. PR-4 and PR-5 added GitHub-installable MCP and "
                "Skill addon contracts. However, some nodes/capabilities are still "
                "loaded via legacy loaders rather than exclusively through the "
                "canonical catalog, leaving partial parallel integration paths."
            ),
            evidence_modules=[
                "core.capability_manager",
                "core.mcp_loader",
                "core.skill_loader",
                "core.agent_manifest",
            ],
            blockers=[
                "Some nodes still self-register via legacy loaders outside the canonical catalog.",
            ],
            recommended_next_actions=[
                "Audit all capability registration paths; funnel remaining ones through the canonical catalog.",
                "Add guardrail in legacy loaders pointing to canonical catalog.",
            ],
            pr_last_updated="PR-5",
        )
    )

    # 6. Projection / Outward-Truth Alignment
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.PROJECTION_OUTWARD_TRUTH_ALIGNMENT,
            MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-8 established that windows_client.status_board_v2 is the sole "
                "PROJECTION_DRIVEN surface, consuming GET /api/v1/projection/runtime. "
                "PR-22 added the DesktopStatusProjection contract. "
                "PR-28 guards assert that projection does not reconstruct truth "
                "independently. dashboard/ and windows_client/ are demoted."
            ),
            evidence_modules=[
                "core.ui_surface_authority",
                "contracts.desktop_status_projection",
                "core.architecture_truth_guards",
                "enhancements.clients.windows_client.status_board_v2",
            ],
            pr_last_updated="PR-8",
        )
    )

    # 7. Cross-Device Execution Consistency
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.CROSS_DEVICE_EXECUTION_CONSISTENCY,
            MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-7 added CrossDeviceChainSnapshot with a canonical 7-step chain "
                "(CanonicalChainStep enum). Legacy multi-device coordinators "
                "(GalaxyOrchestrator, DeviceRouter, CrossDeviceCoordinator) received "
                "deprecated docstrings and guardrails. PR-7 entries added to "
                "orchestration_authority/legacy_paths.py."
            ),
            evidence_modules=[
                "core.cross_device_execution_chain",
                "core.orchestration_authority.legacy_paths",
                "galaxy_gateway.orchestrator.galaxy_orchestrator",
            ],
            pr_last_updated="PR-7",
        )
    )

    # 8. Installability / Ecosystem Readiness
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS,
            MaturityLevel.PARTIAL,
            canonical_path_established=True,
            legacy_ambiguity_remains=True,
            rationale=(
                "PR-4 added the MCP addon contract for GitHub installs. "
                "PR-5 added the Skill package contract. "
                "Contracts are defined and documented in core/contract_map/. "
                "However, end-to-end install validation (e.g. pip install from GitHub "
                "for real addon packages) has not been demonstrated in CI, and some "
                "contract fields remain informational rather than enforced."
            ),
            evidence_modules=[
                "core.contract_map",
                "core.mcp_loader",
                "core.skill_loader",
            ],
            blockers=[
                "No CI-level install test validates actual GitHub-installable addon packages.",
                "Some contract fields are informational only, not validated at load time.",
            ],
            recommended_next_actions=[
                "Add a CI job that installs a minimal test addon from a GitHub URL.",
                "Enforce required contract fields at load time with a validation step.",
            ],
            pr_last_updated="PR-5",
        )
    )

    # 9. Diagnostics / Observability Maturity
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.DIAGNOSTICS_OBSERVABILITY_MATURITY,
            MaturityLevel.COMPLETE,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "PR-10 added ArchitectureDiagnostics (8 invariant checks, "
                "DiagnosticsReport). PR-28 added ArchitectureTruthGuards. "
                "PR-34 added DecisionTimeline for explainability. "
                "PR-41 added RoutingObservability. PR-9 adds this "
                "ArchitectureCompletionScorecard. PR-10 (consolidation) added "
                "ArchitectureInvariants central constants and cross-cutting checks "
                "(projection outward-truth, canonical/legacy label consistency, "
                "addon contract metadata uniformity). The system can now explain "
                "authority state, legacy zones, canonical paths, routing decisions, "
                "and completion status in structured JSON."
            ),
            evidence_modules=[
                "core.architecture_diagnostics",
                "core.architecture_truth_guards",
                "core.architecture_completion",
                "core.architecture_invariants",
                "core.architecture_status_report",
                "core.decision_timeline",
                "core.routing_observability",
            ],
            pr_last_updated="PR-10",
        )
    )

    # 10. Test Coverage of Architecture Invariants
    dims.append(
        build_dimension_scorecard(
            CompletionDimension.TEST_COVERAGE_ARCHITECTURE_INVARIANTS,
            MaturityLevel.COMPLETE,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale=(
                "Major architectural guarantees are covered by dedicated test files: "
                "test_pr10_architecture_diagnostics, test_pr42_architecture_truth_guards, "
                "test_pr47_canonical_cross_device_chain, test_pr48_ui_surface_demotions. "
                "PR-9 adds test_pr49_architecture_completion_scorecard. "
                "PR-10 (consolidation) adds test_pr50_architecture_consolidation which "
                "covers cross-cutting invariants: authority label consistency, "
                "canonical/legacy marker uniformity, scorecard/diagnostic alignment, "
                "and projection outward-truth consistency."
            ),
            evidence_modules=[
                "tests.test_pr10_architecture_diagnostics",
                "tests.test_pr42_architecture_truth_guards",
                "tests.test_pr47_canonical_cross_device_chain",
                "tests.test_pr48_ui_surface_demotions",
                "tests.test_pr49_architecture_completion_scorecard",
                "tests.test_pr50_architecture_consolidation",
            ],
            pr_last_updated="PR-10",
        )
    )

    return dims


def build_architecture_completion_scorecard(
    overrides: Optional[Dict[CompletionDimension, DimensionScorecard]] = None,
    *,
    scorecard_version: str = "1.0",
    generated_by_pr: str = "PR-10",
) -> ArchitectureCompletionScorecard:
    """Build a full :class:`ArchitectureCompletionScorecard`.

    Starts from the built-in baseline (PR-1 through PR-9 history) and applies
    any caller-supplied per-dimension overrides.  Future PRs should supply an
    ``overrides`` dict containing only the updated :class:`DimensionScorecard`
    records.

    Parameters
    ----------
    overrides:
        Optional mapping from :class:`CompletionDimension` to a replacement
        :class:`DimensionScorecard`.  Only dimensions present in this dict
        are replaced; the rest use the built-in defaults.
    scorecard_version:
        Version string for the scorecard format.  Increment when the
        dimension set or scoring schema changes.
    generated_by_pr:
        PR identifier for the call site (e.g. ``"PR-10"``).

    Returns
    -------
    ArchitectureCompletionScorecard
        Fully populated scorecard with aggregate statistics.
    """
    base = _build_default_dimensions()

    if overrides:
        final: List[DimensionScorecard] = []
        for d in base:
            if d.dimension in overrides:
                final.append(overrides[d.dimension])
            else:
                final.append(d)
    else:
        final = base

    return ArchitectureCompletionScorecard(
        dimensions=final,
        scorecard_version=scorecard_version,
        generated_by_pr=generated_by_pr,
    )


# ---------------------------------------------------------------------------
# PR-S7 overrides
# ---------------------------------------------------------------------------


def _build_prs7_overrides() -> Dict[CompletionDimension, DimensionScorecard]:
    """Return dimension scorecard overrides reflecting the PR-S7 state.

    PR-S7 adds ``core/canonical_runtime_declaration.py``, which provides a
    machine-readable declaration of the canonical server runtime pipeline, its
    entry surfaces, and all legacy zones.  This resolves the remaining
    ambiguity in CANONICAL_PATH_COVERAGE (pipeline now explicitly declared)
    and LEGACY_SURFACE_DEMOTION (DeviceOrchestrator and fusion.unified_orchestrator
    explicitly classified; fusion deprecation notice corrected).
    """
    overrides: Dict[CompletionDimension, DimensionScorecard] = {}

    # 2. Canonical Path Coverage → COMPLETE (was CANONICALIZED)
    #    The addition of canonical_runtime_declaration.py provides an explicit,
    #    machine-readable declaration of every pipeline step and entry surface.
    overrides[CompletionDimension.CANONICAL_PATH_COVERAGE] = build_dimension_scorecard(
        CompletionDimension.CANONICAL_PATH_COVERAGE,
        MaturityLevel.COMPLETE,
        canonical_path_established=True,
        legacy_ambiguity_remains=False,
        rationale=(
            "PR-S7 adds core/canonical_runtime_declaration.py — a machine-readable "
            "declaration of every canonical pipeline step (DesktopPresenceRuntime → "
            "OpenClawd → AgentKernel → CommandRouter → TaskGraph → DeviceRouter → "
            "ResultEnvelope) and every entry surface (canonical, helper, legacy).  "
            "Any surface not declared canonical in this module can be mechanically "
            "flagged for removal.  Combined with the existing guardrail registry in "
            "orchestration_authority/legacy_paths.py, canonical path coverage is "
            "explicitly declared end-to-end."
        ),
        evidence_modules=[
            "core.canonical_runtime_declaration",
            "core.constellation_runtime",
            "core.e2e_orchestrator",
            "core.orchestration_authority.legacy_paths",
        ],
        pr_last_updated="PR-S7",
    )

    # 3. Legacy Surface Demotion → stays CANONICALIZED; update evidence + notes
    overrides[CompletionDimension.LEGACY_SURFACE_DEMOTION] = build_dimension_scorecard(
        CompletionDimension.LEGACY_SURFACE_DEMOTION,
        MaturityLevel.CANONICALIZED,
        canonical_path_established=True,
        legacy_ambiguity_remains=False,
        rationale=(
            "PR-S6 demoted TaskScheduler, TaskRouter (galaxy_gateway.task_router), "
            "and MessageHandler (legacy chain B) with guardrails and registry entries.  "
            "PR-S7 closes the remaining gaps: DeviceOrchestrator is explicitly "
            "classified as a canonical helper (not a dispatch authority); "
            "fusion.unified_orchestrator's stale deprecation notice (previously "
            "pointing to the already-demoted GalaxyOrchestrator) is corrected to "
            "point to core.e2e_orchestrator.  "
            "All demoted surfaces carry guardrails, registry entries, and "
            "canonical_replacement pointers."
        ),
        evidence_modules=[
            "core.ui_surface_authority",
            "core.orchestration_authority.legacy_paths",
            "core.legacy_purge_registry",
            "core.canonical_runtime_declaration",
            "dashboard",
            "enhancements.clients.windows_client",
        ],
        pr_last_updated="PR-S7",
    )

    return overrides


# ---------------------------------------------------------------------------
# Module-level singleton entry point
# ---------------------------------------------------------------------------

_CACHED_SCORECARD: Optional[ArchitectureCompletionScorecard] = None


def get_architecture_completion_scorecard(
    *,
    force_rebuild: bool = False,
) -> ArchitectureCompletionScorecard:
    """Return the canonical architecture completion scorecard.

    The scorecard is built once and cached for the lifetime of the process.
    Pass ``force_rebuild=True`` to discard the cached copy (useful in tests).

    Returns
    -------
    ArchitectureCompletionScorecard
        The current canonical scorecard reflecting PR-1 through PR-S7.
    """
    global _CACHED_SCORECARD
    if _CACHED_SCORECARD is None or force_rebuild:
        _CACHED_SCORECARD = build_architecture_completion_scorecard(
            overrides=_build_prs7_overrides(),
            generated_by_pr="PR-S7",
        )
    return _CACHED_SCORECARD


def reset_architecture_completion_scorecard() -> None:
    """Clear the cached scorecard singleton.

    Call this in test teardown to avoid cross-test state contamination.
    """
    global _CACHED_SCORECARD
    _CACHED_SCORECARD = None
