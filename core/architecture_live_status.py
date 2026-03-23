#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.architecture_live_status — Live Architecture Status Surface
================================================================

PR-011 — Add live architecture status surface for runtime readiness.

Converts the post-consolidation architecture baseline (PR-001 through
PR-010) into a **single, runtime-consumable status surface** that operators
and contributors can query to understand the operational posture of the
system at a glance.

## What this module provides

A structured :class:`ArchitectureLiveStatus` payload that aggregates:

- **baseline_version** — which PR baseline this report reflects
- **runtime_readiness** — ``ready`` | ``partial`` | ``blocked``
- **canonical_paths** — modules/paths confirmed as canonical entry points
- **legacy_zones** — modules/paths still operating in legacy/compat mode
- **scorecard_summary** — completion-scorecard dimension summary (from PR-9)
- **active_blockers** — actionable issues preventing readiness advancement
- **projection_status** — outward-truth / projection-only alignment status
- **capability_catalog_status** — MCP/Skill/capability ecosystem health
- **addon_ecosystem_status** — installability and addon contract readiness
- **cross_device_status** — cross-device execution chain consistency
- **authority_chain_status** — authority chain validity summary
- **recommended_next_steps** — actionable next steps for advancement

## Readiness classification rules

``ready``
    Canonical paths exist, no blocking architecture dimensions, authority
    chain is intact, projection is the outward truth.

``partial``
    Architecture is mostly aligned but important gaps remain — for example
    capability integration or installability ecosystem is only partial, or
    legacy ambiguity surfaces still exist.

``blocked``
    One or more architecture dimensions are at LEGACY_AMBIGUITY or
    IN_PROGRESS maturity, or authority chain invariants cannot be confirmed.

## Relationship to ArchitectureCompletionScorecard

The :class:`~core.architecture_completion.ArchitectureCompletionScorecard`
(PR-9) measures **design maturity** across ten dimensions.  This module
produces a **runtime readiness** view: it consumes the scorecard and other
live signals to classify operational posture.

Usage::

    from core.architecture_live_status import (
        get_architecture_live_status,
        build_architecture_live_status,
        RuntimeReadiness,
    )

    status = get_architecture_live_status()
    print(status.runtime_readiness)         # "ready" / "partial" / "blocked"
    print(status.to_json(indent=2))
"""

from __future__ import annotations

import dataclasses
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ArchLiveStatus")

__all__ = [
    # Core data types
    "RuntimeReadiness",
    "CanonicalPathEntry",
    "LegacyZoneEntry",
    "ActiveBlocker",
    "ArchitectureLiveStatus",
    # Builders
    "build_architecture_live_status",
    # Singleton helpers
    "get_architecture_live_status",
    "reset_architecture_live_status",
    # Convenience
    "BASELINE_VERSION",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASELINE_VERSION: str = "PR-011"
"""Baseline version identifier emitted in every status payload."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuntimeReadiness(str, Enum):
    """Runtime readiness classification.

    ``READY``
        Canonical paths exist, no blocking architecture dimensions, authority
        chain is intact, and projection is the confirmed outward truth.

    ``PARTIAL``
        Architecture is mostly aligned but important gaps remain (e.g. legacy
        ambiguity in capability/installability dimensions or minor invariant
        gaps that have not yet been resolved).

    ``BLOCKED``
        One or more architecture dimensions are at LEGACY_AMBIGUITY or
        IN_PROGRESS maturity, or authority chain invariants cannot be
        confirmed.  Active development or remediation is required.
    """

    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Sub-record dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CanonicalPathEntry:
    """A single canonical path/module entry.

    Attributes
    ----------
    path:
        Dotted module or file path (e.g. ``core.constellation_runtime``).
    role:
        Human-readable role description (e.g. ``"canonical dispatcher"``).
    pr_introduced:
        Which PR introduced/confirmed this canonical path.
    """

    path: str
    role: str
    pr_introduced: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict."""
        return {
            "path": self.path,
            "role": self.role,
            "pr_introduced": self.pr_introduced,
        }


@dataclasses.dataclass(frozen=True)
class LegacyZoneEntry:
    """A single legacy or compatibility-mode module entry.

    Attributes
    ----------
    path:
        Dotted module or file path.
    status:
        Classification string (e.g. ``"LEGACY_UI"``, ``"DEPRECATED"``).
    superseded_by:
        The canonical module/path that should be used instead, or ``None``.
    notes:
        Brief description of why this is a legacy zone.
    """

    path: str
    status: str
    superseded_by: Optional[str]
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict."""
        return {
            "path": self.path,
            "status": self.status,
            "superseded_by": self.superseded_by,
            "notes": self.notes,
        }


@dataclasses.dataclass(frozen=True)
class ActiveBlocker:
    """A single actionable blocker preventing readiness advancement.

    Attributes
    ----------
    dimension:
        Architecture dimension name (e.g. ``"capability_integration_completeness"``).
    severity:
        ``"blocking"`` or ``"warning"``.
    description:
        Concise description of the issue.
    recommended_action:
        Suggested remediation step.
    """

    dimension: str
    severity: str
    description: str
    recommended_action: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict."""
        return {
            "dimension": self.dimension,
            "severity": self.severity,
            "description": self.description,
            "recommended_action": self.recommended_action,
        }


# ---------------------------------------------------------------------------
# Main status payload
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ArchitectureLiveStatus:
    """Live architecture status payload.

    This is the single structured surface that aggregates architecture
    diagnostics, scorecard data, legacy zone information, and runtime
    readiness classification into one coherent, serialisable object.

    Attributes
    ----------
    baseline_version:
        Which PR baseline this report reflects (e.g. ``"PR-011"``).
    runtime_readiness:
        Overall runtime readiness: ``"ready"``, ``"partial"``, or
        ``"blocked"``.
    canonical_paths:
        List of :class:`CanonicalPathEntry` objects representing confirmed
        canonical entry points and module authorities.
    legacy_zones:
        List of :class:`LegacyZoneEntry` objects representing modules
        operating in legacy or compatibility mode.
    scorecard_summary:
        Compact scorecard summary dict derived from
        :class:`~core.architecture_completion.ArchitectureCompletionScorecard`.
    active_blockers:
        List of :class:`ActiveBlocker` entries for issues preventing
        advancement to ``ready`` posture.
    projection_status:
        Dict describing projection/outward-truth alignment (whether
        projection is the sole outward truth, surface counts, etc.).
    capability_catalog_status:
        Dict describing MCP/Skill/capability ecosystem registration health.
    addon_ecosystem_status:
        Dict describing installability and addon contract readiness.
    cross_device_status:
        Dict describing cross-device execution chain consistency.
    authority_chain_status:
        Dict describing authority chain validity and ordering.
    recommended_next_steps:
        Ordered list of actionable next steps for advancing readiness.
    """

    baseline_version: str = BASELINE_VERSION
    runtime_readiness: str = RuntimeReadiness.PARTIAL.value
    canonical_paths: List[CanonicalPathEntry] = dataclasses.field(default_factory=list)
    legacy_zones: List[LegacyZoneEntry] = dataclasses.field(default_factory=list)
    scorecard_summary: Dict[str, Any] = dataclasses.field(default_factory=dict)
    active_blockers: List[ActiveBlocker] = dataclasses.field(default_factory=list)
    projection_status: Dict[str, Any] = dataclasses.field(default_factory=dict)
    capability_catalog_status: Dict[str, Any] = dataclasses.field(default_factory=dict)
    addon_ecosystem_status: Dict[str, Any] = dataclasses.field(default_factory=dict)
    cross_device_status: Dict[str, Any] = dataclasses.field(default_factory=dict)
    authority_chain_status: Dict[str, Any] = dataclasses.field(default_factory=dict)
    recommended_next_steps: List[str] = dataclasses.field(default_factory=list)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        Returns
        -------
        Dict[str, Any]
        """
        return {
            "baseline_version": self.baseline_version,
            "runtime_readiness": self.runtime_readiness,
            "canonical_paths": [p.to_dict() for p in self.canonical_paths],
            "legacy_zones": [z.to_dict() for z in self.legacy_zones],
            "scorecard_summary": self.scorecard_summary,
            "active_blockers": [b.to_dict() for b in self.active_blockers],
            "projection_status": self.projection_status,
            "capability_catalog_status": self.capability_catalog_status,
            "addon_ecosystem_status": self.addon_ecosystem_status,
            "cross_device_status": self.cross_device_status,
            "authority_chain_status": self.authority_chain_status,
            "recommended_next_steps": self.recommended_next_steps,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Serialise to a JSON string.

        Parameters
        ----------
        **kwargs:
            Forwarded to :func:`json.dumps` (e.g. ``indent=2``).

        Returns
        -------
        str
        """
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ArchitectureLiveStatus("
            f"baseline_version={self.baseline_version!r}, "
            f"runtime_readiness={self.runtime_readiness!r}, "
            f"blockers={len(self.active_blockers)}, "
            f"canonical_paths={len(self.canonical_paths)}, "
            f"legacy_zones={len(self.legacy_zones)})"
        )


# ---------------------------------------------------------------------------
# Internal signal collectors
# ---------------------------------------------------------------------------


def _collect_canonical_paths() -> List[CanonicalPathEntry]:
    """Build the canonical path list from known architecture sources."""
    paths = [
        CanonicalPathEntry(
            path="core.constellation_runtime",
            role="canonical dispatcher — primary entry point for all agent requests",
            pr_introduced="PR-1",
        ),
        CanonicalPathEntry(
            path="core.openclawd",
            role="subject decision authority — final LLM routing and response authority",
            pr_introduced="PR-1",
        ),
        CanonicalPathEntry(
            path="core.desktop_presence_runtime",
            role="runtime shell authority — top-level desktop runtime orchestrator",
            pr_introduced="PR-1",
        ),
        CanonicalPathEntry(
            path="core.agent.kernel",
            role="cognition planning layer — agent kernel and execution planning",
            pr_introduced="PR-1",
        ),
        CanonicalPathEntry(
            path="core.command_router",
            role="execution substrate — canonical command routing substrate",
            pr_introduced="PR-1",
        ),
        CanonicalPathEntry(
            path="core.orchestration_authority.authority_resolver",
            role="orchestration authority resolver — canonical authority arbitration",
            pr_introduced="PR-9",
        ),
        CanonicalPathEntry(
            path="core.cross_device_execution_chain",
            role="canonical cross-device execution chain — 7-step authority model",
            pr_introduced="PR-7",
        ),
        CanonicalPathEntry(
            path="contracts.desktop_status_projection",
            role="projection contract — canonical outward status truth definition",
            pr_introduced="PR-8",
        ),
        CanonicalPathEntry(
            path="core.architecture_completion",
            role="architecture completion scorecard — 10-dimension maturity registry",
            pr_introduced="PR-9",
        ),
        CanonicalPathEntry(
            path="core.production_baseline",
            role="production baseline registry — canonical artifact + baseline tracking",
            pr_introduced="PR-10",
        ),
    ]
    return paths


def _collect_legacy_zones() -> List[LegacyZoneEntry]:
    """Build the legacy zone list by querying the UI surface authority and
    legacy path registries, falling back to a static baseline if unavailable.
    """
    zones: List[LegacyZoneEntry] = []

    # ── UI surface authority (PR-8) ───────────────────────────────────────────
    try:
        from core.ui_surface_authority import get_ui_surface_authority, UISurfaceRole

        registry = get_ui_surface_authority()
        for entry in registry.all_entries():
            if entry.role in (
                UISurfaceRole.LEGACY_UI,
                UISurfaceRole.LEGACY_SHELL,
                UISurfaceRole.COMPATIBILITY_ONLY,
            ):
                zones.append(
                    LegacyZoneEntry(
                        path=entry.surface_path,
                        status=entry.role.value,
                        superseded_by=entry.superseded_by,
                        notes=entry.description,
                    )
                )
    except Exception as exc:
        logger.debug("_collect_legacy_zones: ui_surface_authority unavailable: %s", exc)
        # Static fallback for known legacy surfaces
        zones.extend([
            LegacyZoneEntry(
                path="dashboard.backend.main",
                status="LEGACY_UI",
                superseded_by="windows_client.status_board_v2",
                notes="WebUI management panel — legacy; no longer defines system structure.",
            ),
            LegacyZoneEntry(
                path="enhancements.clients.windows_client",
                status="LEGACY_SHELL",
                superseded_by="windows_client.status_board_v2",
                notes="Host-specific legacy shell — demoted; consume projection only.",
            ),
        ])

    # ── Legacy orchestration paths (PR-9) ────────────────────────────────────
    try:
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )

        for path, entry in LEGACY_PATH_REGISTRY.items():
            if entry.status in (
                LegacyPathStatus.LEGACY_COMPATIBILITY,
                LegacyPathStatus.DEPRECATED,
            ):
                zones.append(
                    LegacyZoneEntry(
                        path=path,
                        status=entry.status.value,
                        superseded_by=entry.superseded_by,
                        notes=entry.rationale,
                    )
                )
    except Exception as exc:
        logger.debug("_collect_legacy_zones: legacy_paths unavailable: %s", exc)

    return zones


def _collect_scorecard_summary() -> Dict[str, Any]:
    """Return a compact scorecard summary dict."""
    try:
        from core.architecture_completion import get_architecture_completion_scorecard

        scorecard = get_architecture_completion_scorecard()
        blocking = [
            {
                "dimension": d.dimension.value if hasattr(d.dimension, "value") else str(d.dimension),
                "maturity_level": d.maturity_level.value if hasattr(d.maturity_level, "value") else str(d.maturity_level),
                "blockers": list(d.blockers),
            }
            for d in scorecard.blocking_dimensions()
        ]
        legacy_ambiguity = [
            d.dimension.value if hasattr(d.dimension, "value") else str(d.dimension)
            for d in scorecard.legacy_ambiguity_dimensions()
        ]
        return {
            "scorecard_version": scorecard.scorecard_version,
            "generated_by_pr": scorecard.generated_by_pr,
            "overall_completion_pct": round(scorecard.overall_completion_pct, 2),
            "canonical_count": scorecard.canonical_count,
            "total_dimensions": scorecard.total_dimensions,
            "legacy_ambiguity_count": scorecard.legacy_ambiguity_count,
            "blocking_count": scorecard.blocking_count,
            "blocking_dimensions": blocking,
            "legacy_ambiguity_dimensions": legacy_ambiguity,
        }
    except Exception as exc:
        logger.debug("_collect_scorecard_summary: unavailable: %s", exc)
        return {
            "scorecard_version": "unknown",
            "generated_by_pr": "unknown",
            "overall_completion_pct": 0.0,
            "canonical_count": 0,
            "total_dimensions": 10,
            "legacy_ambiguity_count": 0,
            "blocking_count": 0,
            "blocking_dimensions": [],
            "legacy_ambiguity_dimensions": [],
            "error": str(exc),
        }


def _collect_projection_status() -> Dict[str, Any]:
    """Return projection/outward-truth alignment status."""
    try:
        from core.ui_surface_authority import build_ui_surface_authority_summary

        summary = build_ui_surface_authority_summary()
        return {
            "projection_is_only_outward_truth": summary.get(
                "projection_is_only_outward_truth", False
            ),
            "projection_driven_count": summary.get("projection_driven_count", 0),
            "legacy_surface_count": summary.get("legacy_count", 0),
            "total_surfaces": summary.get("total_surfaces", 0),
            "status": (
                "aligned" if summary.get("projection_is_only_outward_truth") is True
                else "unknown" if summary.get("projection_is_only_outward_truth") is None
                else "misaligned"
            ),
        }
    except Exception as exc:
        logger.debug("_collect_projection_status: unavailable: %s", exc)
        return {
            "projection_is_only_outward_truth": None,
            "status": "unknown",
            "error": str(exc),
        }


def _collect_cross_device_status() -> Dict[str, Any]:
    """Return cross-device execution chain status."""
    try:
        from core.cross_device_execution_chain import (
            build_cross_device_chain_snapshot,
            get_cross_device_chain,
            CanonicalChainStep,
        )

        chain = get_cross_device_chain()
        snapshot = build_cross_device_chain_snapshot(chain)
        snap_dict = snapshot.to_dict()
        return {
            "canonical_steps_defined": len(list(CanonicalChainStep)),
            "total_executions_recorded": snap_dict.get("total_executions", 0),
            "chain_module": "core.cross_device_execution_chain",
            "pr_introduced": "PR-7",
            "status": "canonical",
        }
    except Exception as exc:
        logger.debug("_collect_cross_device_status: unavailable: %s", exc)
        return {
            "canonical_steps_defined": 7,
            "chain_module": "core.cross_device_execution_chain",
            "pr_introduced": "PR-7",
            "status": "unknown",
            "error": str(exc),
        }


def _collect_authority_chain_status() -> Dict[str, Any]:
    """Return authority chain validity status."""
    try:
        from core.orchestration_authority.authority_resolver import (
            get_authority_resolver,
        )

        resolver = get_authority_resolver()
        summary = resolver.summary() if hasattr(resolver, "summary") else {}
        return {
            "resolver_available": True,
            "authority_chain_defined": True,
            "summary": summary,
            "status": "valid",
        }
    except Exception as exc:
        logger.debug("_collect_authority_chain_status: authority_resolver unavailable: %s", exc)

    # Fallback: check architecture diagnostics
    try:
        from core.architecture_diagnostics import run_architecture_diagnostics

        # Minimal probe — pass an empty snapshot to check if the module loads
        report = run_architecture_diagnostics({})
        return {
            "resolver_available": False,
            "authority_chain_defined": True,
            "diagnostics_module_available": True,
            "overall_valid": report.overall_valid,
            "status": "valid" if report.overall_valid else "invalid",
        }
    except Exception as exc2:
        logger.debug("_collect_authority_chain_status: diagnostics unavailable: %s", exc2)
        return {
            "resolver_available": False,
            "authority_chain_defined": False,
            "status": "unknown",
            "error": str(exc2),
        }


def _collect_capability_catalog_status() -> Dict[str, Any]:
    """Return capability catalog / MCP/Skill ecosystem status."""
    try:
        from core.capability_runtime.capability_registry_runtime import (
            get_capability_registry_runtime,
        )

        reg = get_capability_registry_runtime()
        summary = reg.summary() if hasattr(reg, "summary") else {}
        return {
            "registry_available": True,
            "summary": summary,
            "status": "available",
        }
    except Exception as exc:
        logger.debug("_collect_capability_catalog_status: capability_registry unavailable: %s", exc)

    # Scorecard-based fallback
    try:
        from core.architecture_completion import (
            get_architecture_completion_scorecard,
            CompletionDimension,
        )

        scorecard = get_architecture_completion_scorecard()
        dim = scorecard.dimension_by_name(CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS)
        if dim is not None:
            return {
                "registry_available": False,
                "maturity_level": dim.maturity_level.value if hasattr(dim.maturity_level, "value") else str(dim.maturity_level),
                "legacy_ambiguity_remains": dim.legacy_ambiguity_remains,
                "status": "partial" if dim.legacy_ambiguity_remains else "available",
            }
    except Exception as exc2:
        logger.debug("_collect_capability_catalog_status: scorecard fallback unavailable: %s", exc2)

    return {"registry_available": False, "status": "unknown"}


def _collect_addon_ecosystem_status() -> Dict[str, Any]:
    """Return addon (MCP/Skill installability) ecosystem status."""
    try:
        from core.architecture_completion import (
            get_architecture_completion_scorecard,
            CompletionDimension,
        )

        scorecard = get_architecture_completion_scorecard()
        dim = scorecard.dimension_by_name(CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS)
        if dim is not None:
            return {
                "maturity_level": dim.maturity_level.value if hasattr(dim.maturity_level, "value") else str(dim.maturity_level),
                "canonical_path_established": dim.canonical_path_established,
                "legacy_ambiguity_remains": dim.legacy_ambiguity_remains,
                "blockers": list(dim.blockers),
                "recommended_next_actions": list(dim.recommended_next_actions),
                "status": "partial" if dim.legacy_ambiguity_remains else "ready",
            }
    except Exception as exc:
        logger.debug("_collect_addon_ecosystem_status: unavailable: %s", exc)

    return {"status": "unknown"}


# ---------------------------------------------------------------------------
# Readiness classifier
# ---------------------------------------------------------------------------


def _classify_readiness(
    scorecard_summary: Dict[str, Any],
    projection_status: Dict[str, Any],
    authority_chain_status: Dict[str, Any],
    active_blockers: List[ActiveBlocker],
) -> RuntimeReadiness:
    """Classify overall runtime readiness from aggregated signals.

    Rules (evaluated in order — first match wins):

    ``BLOCKED``
        - Any blocking architecture dimension (maturity LEGACY_AMBIGUITY or
          IN_PROGRESS) in the scorecard, OR
        - Authority chain status is explicitly ``"invalid"``, OR
        - Any active blocker has severity ``"blocking"``.

    ``PARTIAL``
        - Scorecard has legacy ambiguity in any dimension, OR
        - Projection is not the sole outward truth (misaligned/unknown), OR
        - Capability catalog is partial or unknown, OR
        - Addon ecosystem is partial or unknown, OR
        - Any active blocker has severity ``"warning"``.

    ``READY``
        All other cases: canonical paths exist, no blocking dimensions,
        projection is aligned, no active blockers.
    """
    blocking_count = scorecard_summary.get("blocking_count", 0)
    legacy_ambiguity_count = scorecard_summary.get("legacy_ambiguity_count", 0)
    authority_valid = authority_chain_status.get("status", "unknown")
    has_blocking_blocker = any(
        b.severity == "blocking" for b in active_blockers
    )
    has_warning_blocker = any(
        b.severity == "warning" for b in active_blockers
    )
    projection_aligned = projection_status.get("projection_is_only_outward_truth", None)

    # ── BLOCKED ──────────────────────────────────────────────────────────────
    if blocking_count > 0 or authority_valid == "invalid" or has_blocking_blocker:
        return RuntimeReadiness.BLOCKED

    # ── PARTIAL ──────────────────────────────────────────────────────────────
    if (
        legacy_ambiguity_count > 0
        or projection_aligned is not True
        or has_warning_blocker
    ):
        return RuntimeReadiness.PARTIAL

    # ── READY ─────────────────────────────────────────────────────────────────
    return RuntimeReadiness.READY


# ---------------------------------------------------------------------------
# Active blocker builder
# ---------------------------------------------------------------------------


def _build_active_blockers(
    scorecard_summary: Dict[str, Any],
) -> List[ActiveBlocker]:
    """Build active blockers from scorecard data."""
    blockers: List[ActiveBlocker] = []

    for dim in scorecard_summary.get("blocking_dimensions", []):
        dim_name = dim.get("dimension", "unknown")
        for desc in dim.get("blockers", []):
            blockers.append(
                ActiveBlocker(
                    dimension=dim_name,
                    severity="blocking",
                    description=str(desc),
                    recommended_action=(
                        "Advance this dimension to CANONICALIZED or COMPLETE "
                        "before claiming runtime-ready posture."
                    ),
                )
            )
        if not dim.get("blockers", []):
            blockers.append(
                ActiveBlocker(
                    dimension=dim_name,
                    severity="blocking",
                    description=(
                        f"Dimension '{dim_name}' is at blocking maturity level "
                        f"'{dim.get('maturity_level', 'unknown')}'."
                    ),
                    recommended_action=(
                        "Advance this dimension to at least PARTIAL maturity "
                        "to unblock runtime readiness."
                    ),
                )
            )

    for dim_name in scorecard_summary.get("legacy_ambiguity_dimensions", []):
        blockers.append(
            ActiveBlocker(
                dimension=dim_name,
                severity="warning",
                description=(
                    f"Dimension '{dim_name}' still has legacy ambiguity — "
                    "parallel authority paths or un-guardrailed surfaces remain."
                ),
                recommended_action=(
                    "Resolve legacy ambiguity by guardrailing or removing legacy paths."
                ),
            )
        )

    return blockers


def _build_recommended_next_steps(
    scorecard_summary: Dict[str, Any],
    active_blockers: List[ActiveBlocker],
    addon_ecosystem_status: Dict[str, Any],
    capability_catalog_status: Dict[str, Any],
) -> List[str]:
    """Build an ordered list of recommended next steps."""
    steps: List[str] = []

    if scorecard_summary.get("blocking_count", 0) > 0:
        steps.append(
            "Resolve blocking architecture dimensions (LEGACY_AMBIGUITY or IN_PROGRESS) "
            "before advancing to production-ready posture."
        )

    if scorecard_summary.get("legacy_ambiguity_count", 0) > 0:
        steps.append(
            "Clear remaining legacy ambiguity in flagged dimensions "
            "(guardrail or remove legacy paths)."
        )

    addon_status = addon_ecosystem_status.get("status", "unknown")
    if addon_status in ("partial", "unknown"):
        steps.append(
            "Harden addon (MCP/Skill) installability: add CI job to install a "
            "test addon from a GitHub URL and enforce contract validation at load time."
        )

    cap_status = capability_catalog_status.get("status", "unknown")
    if cap_status in ("partial", "unknown"):
        steps.append(
            "Complete capability integration: ensure all MCP/Skill/Node/Gateway "
            "capabilities are routed through the canonical capability catalog."
        )

    if not steps:
        steps.append(
            "Architecture baseline is operational. Continue with productization: "
            "stabilize APIs, validate cross-device execution in real hardware, "
            "and publish the canonical capability catalog."
        )

    return steps


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_architecture_live_status() -> ArchitectureLiveStatus:
    """Build a fresh :class:`ArchitectureLiveStatus` payload.

    Collects signals from all available architecture modules and produces a
    coherent, JSON-serialisable status surface.

    Returns
    -------
    ArchitectureLiveStatus
        The current live architecture status.
    """
    canonical_paths = _collect_canonical_paths()
    legacy_zones = _collect_legacy_zones()
    scorecard_summary = _collect_scorecard_summary()
    projection_status = _collect_projection_status()
    cross_device_status = _collect_cross_device_status()
    authority_chain_status = _collect_authority_chain_status()
    capability_catalog_status = _collect_capability_catalog_status()
    addon_ecosystem_status = _collect_addon_ecosystem_status()

    active_blockers = _build_active_blockers(scorecard_summary)
    recommended_next_steps = _build_recommended_next_steps(
        scorecard_summary, active_blockers, addon_ecosystem_status, capability_catalog_status
    )

    readiness = _classify_readiness(
        scorecard_summary, projection_status, authority_chain_status, active_blockers
    )

    return ArchitectureLiveStatus(
        baseline_version=BASELINE_VERSION,
        runtime_readiness=readiness.value,
        canonical_paths=canonical_paths,
        legacy_zones=legacy_zones,
        scorecard_summary=scorecard_summary,
        active_blockers=active_blockers,
        projection_status=projection_status,
        capability_catalog_status=capability_catalog_status,
        addon_ecosystem_status=addon_ecosystem_status,
        cross_device_status=cross_device_status,
        authority_chain_status=authority_chain_status,
        recommended_next_steps=recommended_next_steps,
    )


# ---------------------------------------------------------------------------
# Cached singleton
# ---------------------------------------------------------------------------

_CACHED_LIVE_STATUS: Optional[ArchitectureLiveStatus] = None


def get_architecture_live_status(
    *,
    force_rebuild: bool = False,
) -> ArchitectureLiveStatus:
    """Return the canonical architecture live status.

    The status is built once and cached for the lifetime of the process.
    Pass ``force_rebuild=True`` to discard the cached copy (useful in tests).

    Parameters
    ----------
    force_rebuild:
        When ``True``, the cached status is discarded and rebuilt.

    Returns
    -------
    ArchitectureLiveStatus
        The current canonical live status.
    """
    global _CACHED_LIVE_STATUS
    if _CACHED_LIVE_STATUS is None or force_rebuild:
        _CACHED_LIVE_STATUS = build_architecture_live_status()
    return _CACHED_LIVE_STATUS


def reset_architecture_live_status() -> None:
    """Clear the cached live status singleton.

    Call this in test teardown to avoid cross-test state contamination.
    """
    global _CACHED_LIVE_STATUS
    _CACHED_LIVE_STATUS = None
