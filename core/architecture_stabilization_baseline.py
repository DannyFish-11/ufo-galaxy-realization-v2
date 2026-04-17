#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/architecture_stabilization_baseline.py
=============================================
PR-10 (realization-v2 convergence plan): Architecture Stabilization Baseline.

This module is the **canonical authority** for the explicit stabilization
baseline declaration after the current governance/dispatch/truth/compatibility
work (PR-6 through PR-9 of the realization-v2 convergence plan).

Background
----------
After PRs #6–#9 of the realization-v2 convergence plan:

* **PR-6** (``core.authority_boundary_classification``) — explicit authority
  role taxonomy for every surface in the Galaxy/OpenClawd runtime.
* **PR-7** (``core.truth_projection_boundary``) — explicit truth vs.
  projection/read-model boundary across all authority planes.
* **PR-8** (``core.long_tail_compat_surface``) — identification and
  classification of long-tail capability/message-family compat paths.
* **PR-9** (``core.runtime_truth_output_chain``) — explicit ordered chain
  from internal runtime-truth compilation to outward-truth assembly and
  projection output.

…there is still no single explicit module that declares **what the system
is now considered safe to build on**.  Different surfaces have been
classified, catalogued, and governed, but contributors still need a
synthesized answer to:

* Which surfaces are now canonical enough to be stable extension points?
* Which surfaces remain transitional and must converge, not grow?
* What categories of future work should prefer canonical-only paths?
* Where should extension happen, and where should convergence continue?

This module provides that synthesized answer.

Stabilization tiers
--------------------
:attr:`StabilizationTier.CANONICAL_STABLE`
    The surface is governed, canonical, and stable enough to be a first-class
    extension point.  New features **should** build on these surfaces.

:attr:`StabilizationTier.TRANSITIONAL_CONVERGING`
    The surface is classified as transitional/compat-only.  It is preserved for
    migration continuity, but **must not** be extended with new canonical logic.
    Its purpose is fulfilled once downstream consumers migrate to the canonical
    replacement.

:attr:`StabilizationTier.EXTENSION_SURFACE`
    The surface is the designated extension point for a specific domain (e.g.
    the projection routes router, the node invocation path, the dispatch
    orchestrator).  New feature surface area for that domain **belongs here**.

:attr:`StabilizationTier.COMPATIBILITY_BRIDGE`
    The surface exists solely to preserve backward compatibility.  It holds no
    canonical authority and must not grow.  Removal is the eventual goal once
    its migration continuity purpose is fulfilled.

Future-work guidance
---------------------
+---------------------------------------------+-------------------------------+
| Category of future work                     | Preferred path                |
+=============================================+===============================+
| New node capabilities / node lifecycle      | NodeFabricRegistry +          |
|                                             | node_invocation_governance    |
+---------------------------------------------+-------------------------------+
| New outward truth fields / projections      | compile_outward_truth() →     |
|                                             | projection routes             |
+---------------------------------------------+-------------------------------+
| New dispatch modes / orchestration signals  | source_dispatch_orchestrator  |
|                                             | (canonical)                   |
+---------------------------------------------+-------------------------------+
| New session semantics                       | attached_runtime_session +    |
|                                             | canonical_session_truth       |
+---------------------------------------------+-------------------------------+
| New capability tier / scheduling rules      | canonical_capability_         |
|                                             | scheduling_basis              |
+---------------------------------------------+-------------------------------+
| New UI / dashboard surfaces                 | Consume projection output     |
|                                             | only; do not add new truth    |
+---------------------------------------------+-------------------------------+
| Long-tail compat path retirement            | Migrate to stateful canonical |
|                                             | handler; remove generic-fwd   |
+---------------------------------------------+-------------------------------+
| Governance policy additions                 | authority_boundary_           |
|                                             | classification matrix only    |
+---------------------------------------------+-------------------------------+

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY`
:data:`ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL`
:data:`CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY`
:data:`TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY`
:data:`EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY`
:data:`COMPAT_BRIDGES_MUST_NOT_GROW_POLICY`

Enums
~~~~~
:class:`StabilizationTier`
:class:`SurfaceCategory`

Data classes
~~~~~~~~~~~~
:class:`StabilizationSurfaceRecord`
:class:`StabilizationBaselineSnapshot`

Functions
~~~~~~~~~
:func:`get_baseline_catalog`
:func:`get_canonical_stable_surfaces`
:func:`get_transitional_surfaces`
:func:`get_extension_surfaces`
:func:`get_compat_bridge_surfaces`
:func:`classify_surface_tier`
:func:`build_stabilization_baseline_snapshot`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY: str = (
    "ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY_V1: "
    "core.architecture_stabilization_baseline is the canonical authority for "
    "the explicit architecture stabilization baseline declaration after the "
    "realization-v2 convergence plan PR-6 through PR-9.  It identifies which "
    "surfaces are canonical-stable extension points, which are transitional, "
    "and provides future-work guidance for canonical-path compliance."
)

ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL: str = (
    "ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL_V1: "
    "PR-10 (realization-v2 convergence plan) — architecture stabilization "
    "baseline is explicitly declared.  Canonical vs. transitional surfaces are "
    "summarized at a system level.  Future contributors can determine where to "
    "extend versus where to converge."
)

ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL: str = (
    "ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL_V1: "
    "PR-11 (realization-v2 convergence plan) — architecture stabilization "
    "baseline is extended with session-axis, session-truth, and session-registry "
    "canonical surfaces.  The canonical session axis, canonical session truth, "
    "and attached-runtime session registry are explicitly declared as "
    "CANONICAL_STABLE extension points.  Future session-semantics work must "
    "route through these canonical surfaces and must not introduce parallel "
    "session authority."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY: str = (
    "CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY_V1: "
    "Surfaces classified as CANONICAL_STABLE or EXTENSION_SURFACE are the "
    "designated first-class extension points.  New features, new capability "
    "integrations, and new truth surfaces MUST build on these and MUST NOT "
    "introduce parallel authority surfaces."
)

TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY: str = (
    "TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY_V1: "
    "Surfaces classified as TRANSITIONAL_CONVERGING MUST NOT be extended with "
    "new canonical logic.  Contributors encountering a transitional surface "
    "should prefer the documented canonical_replacement and schedule migration "
    "if the replacement is not yet wired."
)

EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY: str = (
    "EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY_V1: "
    "All future-work categories (node capabilities, outward truth fields, "
    "dispatch modes, session semantics, capability tiers, UI surfaces, "
    "compat-path retirement, governance policy additions) MUST route through "
    "the canonical surfaces identified in this stabilization baseline.  "
    "New parallel authority surfaces are explicitly prohibited."
)

COMPAT_BRIDGES_MUST_NOT_GROW_POLICY: str = (
    "COMPAT_BRIDGES_MUST_NOT_GROW_POLICY_V1: "
    "Surfaces classified as COMPATIBILITY_BRIDGE exist solely to preserve "
    "backward compatibility during migration.  They MUST NOT be extended "
    "with new logic.  When downstream consumers have fully migrated to the "
    "canonical replacement, the compat bridge SHOULD be removed."
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY",
    "ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL",
    "ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL",
    "CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY",
    "TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY",
    "EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY",
    "COMPAT_BRIDGES_MUST_NOT_GROW_POLICY",
    # Enums
    "StabilizationTier",
    "SurfaceCategory",
    # Data classes
    "StabilizationSurfaceRecord",
    "StabilizationBaselineSnapshot",
    # Functions
    "get_baseline_catalog",
    "get_canonical_stable_surfaces",
    "get_transitional_surfaces",
    "get_extension_surfaces",
    "get_compat_bridge_surfaces",
    "classify_surface_tier",
    "build_stabilization_baseline_snapshot",
]


class StabilizationTier(str, Enum):
    """Stabilization classification for an architecture surface.

    Attributes
    ----------
    CANONICAL_STABLE:
        Governed and canonical; stable enough to be a first-class extension
        point.  New features should build on these surfaces.
    TRANSITIONAL_CONVERGING:
        Classified as transitional or compat-only.  Must not be extended with
        new canonical logic.  The surface should migrate toward its canonical
        replacement.
    EXTENSION_SURFACE:
        The designated extension point for a specific domain.  New feature
        surface area for that domain belongs here.
    COMPATIBILITY_BRIDGE:
        Exists solely to preserve backward compatibility.  Holds no canonical
        authority, must not grow, and should eventually be removed.
    """

    CANONICAL_STABLE = "canonical_stable"
    TRANSITIONAL_CONVERGING = "transitional_converging"
    EXTENSION_SURFACE = "extension_surface"
    COMPATIBILITY_BRIDGE = "compatibility_bridge"

    @classmethod
    def from_string(cls, value: str) -> "StabilizationTier":
        """Return the enum member matching *value*, or raise ``ValueError``."""
        try:
            return cls(value)
        except ValueError:
            raise ValueError(
                f"Unknown StabilizationTier: {value!r}.  "
                f"Valid values: {[t.value for t in cls]}"
            )


class SurfaceCategory(str, Enum):
    """Broad category of an architecture surface.

    Used to group related surfaces and to guide future-work routing.
    """

    GOVERNANCE_AUTHORITY = "governance_authority"
    """Surfaces that define or enforce authority, boundary, or governance rules."""

    TRUTH_OWNER = "truth_owner"
    """Surfaces that own canonical write authority (SSOT, registries)."""

    TRUTH_COMPILATION = "truth_compilation"
    """Surfaces that compile or assemble truth snapshots from SSOT sources."""

    PROJECTION_OUTPUT = "projection_output"
    """Read-only projection and output surfaces consumed by UI/dashboard."""

    DISPATCH_ORCHESTRATION = "dispatch_orchestration"
    """Surfaces that orchestrate or govern execution dispatch."""

    SESSION_LIFECYCLE = "session_lifecycle"
    """Surfaces that own or govern session attachment/lifecycle semantics."""

    CAPABILITY_SCHEDULING = "capability_scheduling"
    """Surfaces that define device/execution capability and scheduling basis."""

    NODE_REGISTRY = "node_registry"
    """Surfaces that register, index, or govern node participation."""

    NODE_INVOCATION = "node_invocation"
    """Surfaces that govern or perform node invocation."""

    LONG_TAIL_COMPAT = "long_tail_compat"
    """Catalog or governance surfaces for long-tail compat/transitional paths."""

    COMPATIBILITY_LAYER = "compatibility_layer"
    """Compat facades, legacy aliases, and migration-continuity bridges."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StabilizationSurfaceRecord:
    """Classification of one architecture surface in the stabilization baseline.

    Attributes
    ----------
    surface_id:
        Short, unique identifier for the surface (used for lookup).
    surface_name:
        Human-readable surface name.
    module_path:
        Canonical Python module path for the surface.
    tier:
        Stabilization tier for this surface.
    category:
        Broad category of this surface.
    is_extension_ready:
        ``True`` if this surface is safe to extend with new canonical logic.
        Only ``CANONICAL_STABLE`` and ``EXTENSION_SURFACE`` surfaces are
        extension-ready.
    canonical_replacement:
        If this surface is transitional or a compat bridge, the module path
        of the canonical replacement that consumers should migrate to.
        ``None`` for canonical-stable and extension surfaces.
    pr_introduced:
        The PR tag that introduced this surface (e.g. ``"PR-7"``).
    rationale:
        Explanation of the tier classification and any migration guidance.
    """

    surface_id: str
    surface_name: str
    module_path: str
    tier: StabilizationTier
    category: SurfaceCategory
    is_extension_ready: bool
    pr_introduced: str
    rationale: str
    canonical_replacement: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "surface_name": self.surface_name,
            "module_path": self.module_path,
            "tier": self.tier.value,
            "category": self.category.value,
            "is_extension_ready": self.is_extension_ready,
            "pr_introduced": self.pr_introduced,
            "rationale": self.rationale,
            "canonical_replacement": self.canonical_replacement,
        }


@dataclass
class StabilizationBaselineSnapshot:
    """Point-in-time snapshot of the full architecture stabilization baseline.

    Attributes
    ----------
    snapshotted_at:
        Unix timestamp at which the snapshot was built.
    total_surface_count:
        Total number of classified surfaces.
    canonical_stable_count:
        Count of surfaces with tier ``CANONICAL_STABLE``.
    transitional_converging_count:
        Count of surfaces with tier ``TRANSITIONAL_CONVERGING``.
    extension_surface_count:
        Count of surfaces with tier ``EXTENSION_SURFACE``.
    compat_bridge_count:
        Count of surfaces with tier ``COMPATIBILITY_BRIDGE``.
    extension_ready_count:
        Count of surfaces where ``is_extension_ready`` is ``True``.
    policy_sentinels:
        List of all four policy sentinel strings for machine verification.
    surfaces:
        Full catalog of surface records.
    """

    snapshotted_at: float = field(default_factory=time.time)
    total_surface_count: int = 0
    canonical_stable_count: int = 0
    transitional_converging_count: int = 0
    extension_surface_count: int = 0
    compat_bridge_count: int = 0
    extension_ready_count: int = 0
    policy_sentinels: List[str] = field(default_factory=list)
    surfaces: List[StabilizationSurfaceRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "snapshotted_at": self.snapshotted_at,
            "total_surface_count": self.total_surface_count,
            "canonical_stable_count": self.canonical_stable_count,
            "transitional_converging_count": self.transitional_converging_count,
            "extension_surface_count": self.extension_surface_count,
            "compat_bridge_count": self.compat_bridge_count,
            "extension_ready_count": self.extension_ready_count,
            "policy_sentinels": self.policy_sentinels,
            "surfaces": [s.to_dict() for s in self.surfaces],
        }


# ---------------------------------------------------------------------------
# Surface catalog
# ---------------------------------------------------------------------------
#
# Entries are organized by tier, then by category.  Each entry has:
#   - surface_id  (short key used for lookup)
#   - surface_name
#   - module_path
#   - tier
#   - category
#   - is_extension_ready
#   - pr_introduced  (the convergence-plan PR that introduced or governed it)
#   - rationale
#   - canonical_replacement  (only for transitional/compat surfaces)
# ---------------------------------------------------------------------------

_BASELINE_CATALOG: List[StabilizationSurfaceRecord] = [
    # =========================================================================
    # CANONICAL_STABLE — governance / authority surfaces
    # =========================================================================
    StabilizationSurfaceRecord(
        surface_id="authority_boundary_classification",
        surface_name="Authority Boundary Classification",
        module_path="core.authority_boundary_classification",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.GOVERNANCE_AUTHORITY,
        is_extension_ready=True,
        pr_introduced="PR-6 (UGCP)",
        rationale=(
            "Explicit authority role taxonomy and machine-checkable matrix "
            "covering every major surface.  This is the governing reference "
            "for all authority-boundary decisions; new authority entries should "
            "be added here rather than inventing parallel classification."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="truth_projection_boundary",
        surface_name="Truth vs. Projection Boundary",
        module_path="core.truth_projection_boundary",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.GOVERNANCE_AUTHORITY,
        is_extension_ready=True,
        pr_introduced="PR-7 (UGCP)",
        rationale=(
            "Canonical classification of every cross-plane surface into "
            "truth-owner, projection/read-model, synchronization-mapping, or "
            "compatibility-only roles.  New cross-plane surfaces should be "
            "classified here before being wired."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="runtime_truth_output_chain",
        surface_name="Runtime Truth Output Chain",
        module_path="core.runtime_truth_output_chain",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.GOVERNANCE_AUTHORITY,
        is_extension_ready=True,
        pr_introduced="PR-9 (UGCP)",
        rationale=(
            "Ordered three-stage chain (internal compiler → outward assembler → "
            "projection output) with explicit governance invariants.  New truth "
            "output surfaces must respect this chain ordering."
        ),
    ),
    # =========================================================================
    # CANONICAL_STABLE — truth compilation surfaces
    # =========================================================================
    StabilizationSurfaceRecord(
        surface_id="runtime_truth_compiler",
        surface_name="Runtime Truth Compiler",
        module_path="core.projection.runtime_truth_compiler",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.TRUTH_COMPILATION,
        is_extension_ready=True,
        pr_introduced="PR-9 (UGCP, Stage 1)",
        rationale=(
            "Canonical internal-only stage-1 compiler that gathers state from "
            "all canonical subsystems once per request.  New internal truth "
            "fields belong here.  Stage-3 projection surfaces must not call "
            "this directly when stage-2 outward truth is available."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="outward_runtime_truth",
        surface_name="Outward Runtime Truth Assembler",
        module_path="core.outward_runtime_truth",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.TRUTH_COMPILATION,
        is_extension_ready=True,
        pr_introduced="PR-9 (UGCP, Stage 2)",
        rationale=(
            "Canonical outward-facing stage-2 assembler.  The single "
            "compile_outward_truth() call point for outward consumers.  New "
            "outward truth enrichment (operator context, bridge context, etc.) "
            "belongs in this layer."
        ),
    ),
    # =========================================================================
    # CANONICAL_STABLE — node registry / invocation surfaces
    # =========================================================================
    StabilizationSurfaceRecord(
        surface_id="node_fabric_registry",
        surface_name="NodeFabricRegistry (Canonical Node Registry)",
        module_path="core.nodes.node_fabric_registry",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.NODE_REGISTRY,
        is_extension_ready=True,
        pr_introduced="PR-3 (node track)",
        rationale=(
            "The canonical runtime node registry.  New node registration, "
            "capability indexing, and discovery surfaces must use this registry "
            "as the authoritative source.  NodeRegistry (core.node_registry) "
            "is the compat facade."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="node_invocation_governance",
        surface_name="Node Invocation Governance",
        module_path="core.node_invocation_governance",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.NODE_INVOCATION,
        is_extension_ready=True,
        pr_introduced="PR-11 (node track)",
        rationale=(
            "Canonical governance eligibility enforcement at node invocation "
            "time.  New invocation policies (e.g. new exclusion conditions) "
            "must be added here, not in ad hoc per-callsite checks."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="node_cognition_activation",
        surface_name="Node Cognition Activation",
        module_path="core.node_cognition_activation",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.NODE_INVOCATION,
        is_extension_ready=True,
        pr_introduced="PR-14 (node track)",
        rationale=(
            "Canonical activation-state machine and eligibility evaluation for "
            "cognition-oriented node activation.  New activation states or "
            "transition rules must follow the VALID_ACTIVATION_TRANSITIONS table."
        ),
    ),
    # =========================================================================
    # CANONICAL_STABLE — dispatch / session / capability surfaces
    # =========================================================================
    StabilizationSurfaceRecord(
        surface_id="source_dispatch_orchestrator",
        surface_name="Source Runtime Dispatch Orchestrator",
        module_path="core.runtime.source_dispatch_orchestrator",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.DISPATCH_ORCHESTRATION,
        is_extension_ready=True,
        pr_introduced="PR-35 (post-533)",
        rationale=(
            "Canonical orchestration surface for source-side runtime dispatch, "
            "covering local/remote/fallback/staged-mesh modes with explicit "
            "selection, readiness, and result-merge semantics.  New dispatch "
            "modes must be added to this orchestrator."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="attached_runtime_session",
        surface_name="Canonical Attached-Runtime Session",
        module_path="core.attached_runtime_session",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.SESSION_LIFECYCLE,
        is_extension_ready=True,
        pr_introduced="PR-7 (post-533)",
        rationale=(
            "Canonical persistent attached-runtime session semantics.  Session "
            "attachment, detachment, reconnect, and reattach must go through "
            "this surface.  New session lifecycle signals belong here."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="canonical_capability_scheduling_basis",
        surface_name="Canonical Capability and Scheduling Basis",
        module_path="core.canonical_capability_scheduling_basis",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.CAPABILITY_SCHEDULING,
        is_extension_ready=True,
        pr_introduced="PR-6 (post-533)",
        rationale=(
            "Canonical surface for device/host capability representation and "
            "scheduling-basis normalization.  New capability tiers or execution "
            "surface eligibility rules belong here."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="delegated_runtime_dispatch_intent",
        surface_name="Delegated Runtime Dispatch Intent",
        module_path="core.delegated_runtime_dispatch_intent",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.DISPATCH_ORCHESTRATION,
        is_extension_ready=True,
        pr_introduced="PR-8 (post-533)",
        rationale=(
            "Canonical authority for delegated-runtime dispatch intent and "
            "handoff-preparation state.  New delegated-dispatch intent states "
            "or preparation signals belong here."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="delegated_runtime_handoff_contract",
        surface_name="Delegated Runtime Handoff Contract",
        module_path="core.delegated_runtime_handoff_contract",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.DISPATCH_ORCHESTRATION,
        is_extension_ready=True,
        pr_introduced="PR-9 (post-533)",
        rationale=(
            "Canonical authority for the host-side delegated handoff contract "
            "record transmitted when delegated work is handed off to a remote "
            "cross-device runtime.  New contract fields must be added here with "
            "version-schema coordination with the receiving Android side."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="canonical_session_axis",
        surface_name="Canonical Session Axis",
        module_path="core.canonical_session_axis",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.GOVERNANCE_AUTHORITY,
        is_extension_ready=True,
        pr_introduced="PR-3 (canonical session axis, PR-11 UGCP stabilization)",
        rationale=(
            "Canonical authority for the cross-layer, cross-repository session "
            "axis model: the five session families, canonical identifier "
            "resolution order, Android-to-center session mapping, and continuity "
            "semantics.  New session-family definitions or identifier resolution "
            "rules must be catalogued here."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="canonical_session_truth",
        surface_name="Canonical Session Truth",
        module_path="core.canonical_session_truth",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.SESSION_LIFECYCLE,
        is_extension_ready=True,
        pr_introduced="PR-4 (post-533, PR-11 UGCP stabilization)",
        rationale=(
            "Canonical authority for posture-aware result-merge truth and "
            "session-truth recording.  Determines the single authoritative "
            "execution truth for a session given local, remote/takeover, and "
            "partial/multi-device contributions.  New session-truth fields or "
            "merge policies must be added here."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="attached_runtime_session_registry",
        surface_name="Attached Runtime Session Registry",
        module_path="core.attached_runtime_session_registry",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.SESSION_LIFECYCLE,
        is_extension_ready=True,
        pr_introduced="PR-19 (post-533, PR-11 UGCP stabilization)",
        rationale=(
            "Canonical single-source-of-truth registry for attached runtime "
            "sessions.  Dispatch, reuse, and reconciliation layers MUST consult "
            "this registry to resolve session identity.  New session-state "
            "transitions (register, reconnect, reattach, detach, invalidate) "
            "must flow through this registry."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="long_tail_compat_surface",
        surface_name="Long-Tail Compat Surface Catalog",
        module_path="core.long_tail_compat_surface",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.LONG_TAIL_COMPAT,
        is_extension_ready=True,
        pr_introduced="PR-8 (UGCP)",
        rationale=(
            "Canonical catalog of all long-tail compat and generic-forward "
            "paths with explicit transition status.  New compat surface "
            "identifications must be catalogued here rather than in ad hoc "
            "per-module comments."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="projection_routes",
        surface_name="Projection Routes (GET endpoints)",
        module_path="core.routes.projection",
        tier=StabilizationTier.EXTENSION_SURFACE,
        category=SurfaceCategory.PROJECTION_OUTPUT,
        is_extension_ready=True,
        pr_introduced="PR-3 (core routes)",
        rationale=(
            "Designated extension point for read-only projection endpoints.  "
            "New read-model surfaces for dashboard/operator consumers belong "
            "here.  This module must remain read-only; it must never write "
            "state, send commands, or act as a truth source."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="node_boundary_runtime",
        surface_name="Node Boundary Runtime",
        module_path="core.node_boundary_runtime",
        tier=StabilizationTier.EXTENSION_SURFACE,
        category=SurfaceCategory.NODE_REGISTRY,
        is_extension_ready=True,
        pr_introduced="PR-8 (node track)",
        rationale=(
            "Canonical authority for Galaxy node boundary definitions and "
            "invocation pathway classification.  New node boundary categories "
            "or legacy surface registrations belong here."
        ),
    ),
    # =========================================================================
    # TRANSITIONAL_CONVERGING — surfaces that must converge, not grow
    # =========================================================================
    StabilizationSurfaceRecord(
        surface_id="node_registry_compat_facade",
        surface_name="NodeRegistry (Legacy Compat Facade)",
        module_path="core.node_registry",
        tier=StabilizationTier.TRANSITIONAL_CONVERGING,
        category=SurfaceCategory.COMPATIBILITY_LAYER,
        is_extension_ready=False,
        pr_introduced="PR-3 (node track)",
        canonical_replacement="core.nodes.node_fabric_registry",
        rationale=(
            "Legacy NodeRegistry is an explicit compat facade.  All new node "
            "registration and registry queries must target NodeFabricRegistry.  "
            "This facade should be removed once all callers have migrated."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="node_discovery_startup_health_closure",
        surface_name="Node Discovery Startup Health Closure",
        module_path="core.node_discovery_startup_health_closure",
        tier=StabilizationTier.TRANSITIONAL_CONVERGING,
        category=SurfaceCategory.NODE_REGISTRY,
        is_extension_ready=False,
        pr_introduced="PR-12 (node track)",
        canonical_replacement="core.nodes.node_fabric_registry",
        rationale=(
            "This module closed startup-seeding and health-surface gaps in "
            "NodeDiscoveryService.  Its surface is stable but the underlying "
            "NodeDiscoveryService pattern is transitional; the longer-term goal "
            "is full participation through NodeFabricRegistry."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="generic_forward_handlers",
        surface_name="Generic Forward / Minimal-Compat ACK Handlers",
        module_path="galaxy_gateway.android.handlers.generic",
        tier=StabilizationTier.TRANSITIONAL_CONVERGING,
        category=SurfaceCategory.LONG_TAIL_COMPAT,
        is_extension_ready=False,
        pr_introduced="PR-8 (UGCP, long-tail)",
        canonical_replacement="core.long_tail_compat_surface (stateful canonical handler per family)",
        rationale=(
            "handle_generic_forward and _handle_forward_ack are minimal-compat "
            "ACK handlers that return bare acknowledgements with no stateful "
            "semantics.  They must not be extended.  Each affected message "
            "family must migrate to the stateful canonical handler as documented "
            "in the long_tail_compat_surface catalog."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="dashboard_backend_main",
        surface_name="Dashboard Backend (dashboard.backend.main)",
        module_path="dashboard.backend.main",
        tier=StabilizationTier.TRANSITIONAL_CONVERGING,
        category=SurfaceCategory.PROJECTION_OUTPUT,
        is_extension_ready=False,
        pr_introduced="pre-PR-6",
        canonical_replacement="core.routes.projection",
        rationale=(
            "dashboard.backend.main assembles and serves dashboard state.  "
            "It should be a thin consumer of projection output rather than an "
            "independent truth-assembler.  New dashboard state fields must come "
            "from projection output, not from parallel state assembly in this "
            "module."
        ),
    ),
    # =========================================================================
    # COMPATIBILITY_BRIDGE — must not grow; eventual removal target
    # =========================================================================
    StabilizationSurfaceRecord(
        surface_id="node_status_cache",
        surface_name="node_status_cache (Legacy Status Cache)",
        module_path="core.node_status_cache",
        tier=StabilizationTier.COMPATIBILITY_BRIDGE,
        category=SurfaceCategory.COMPATIBILITY_LAYER,
        is_extension_ready=False,
        pr_introduced="pre-PR-6",
        canonical_replacement="core.nodes.node_fabric_registry",
        rationale=(
            "node_status_cache is a stale-tolerant compat-only status cache "
            "classified explicitly as COMPAT_ONLY in PR-13 node boundary "
            "enforcement.  Must not be used as a canonical status source.  "
            "All new status queries must use NodeFabricRegistry."
        ),
    ),
    StabilizationSurfaceRecord(
        surface_id="node_registry_json_scan",
        surface_name="node_registry.json / fusion_entry.py legacy scan",
        module_path="core.openclawd_canonical_node_tool_exposure (legacy Layer 3)",
        tier=StabilizationTier.COMPATIBILITY_BRIDGE,
        category=SurfaceCategory.COMPATIBILITY_LAYER,
        is_extension_ready=False,
        pr_introduced="PR-10 (node track)",
        canonical_replacement="core.nodes.node_fabric_registry",
        rationale=(
            "Legacy node_registry.json and fusion_entry.py scan (Layer 3) is "
            "disabled by default in OpenClawd._collect_tools().  It may be "
            "re-enabled only by OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED=true "
            "for backward compatibility.  Must not be extended."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_baseline_catalog() -> Sequence[StabilizationSurfaceRecord]:
    """Return the full stabilization baseline surface catalog.

    Returns
    -------
    Sequence[StabilizationSurfaceRecord]
        All classified surfaces in definition order.
    """
    return list(_BASELINE_CATALOG)


def get_canonical_stable_surfaces() -> List[StabilizationSurfaceRecord]:
    """Return all surfaces with tier ``CANONICAL_STABLE``.

    These are the governed, canonical surfaces that are safe and
    recommended as extension points.

    Returns
    -------
    List[StabilizationSurfaceRecord]
        Surfaces with :attr:`StabilizationTier.CANONICAL_STABLE`.
    """
    return [s for s in _BASELINE_CATALOG if s.tier == StabilizationTier.CANONICAL_STABLE]


def get_transitional_surfaces() -> List[StabilizationSurfaceRecord]:
    """Return all surfaces with tier ``TRANSITIONAL_CONVERGING``.

    These surfaces must converge toward their canonical replacement
    rather than accepting new canonical logic.

    Returns
    -------
    List[StabilizationSurfaceRecord]
        Surfaces with :attr:`StabilizationTier.TRANSITIONAL_CONVERGING`.
    """
    return [s for s in _BASELINE_CATALOG if s.tier == StabilizationTier.TRANSITIONAL_CONVERGING]


def get_extension_surfaces() -> List[StabilizationSurfaceRecord]:
    """Return all surfaces with tier ``EXTENSION_SURFACE``.

    These are the designated extension points for specific domains.

    Returns
    -------
    List[StabilizationSurfaceRecord]
        Surfaces with :attr:`StabilizationTier.EXTENSION_SURFACE`.
    """
    return [s for s in _BASELINE_CATALOG if s.tier == StabilizationTier.EXTENSION_SURFACE]


def get_compat_bridge_surfaces() -> List[StabilizationSurfaceRecord]:
    """Return all surfaces with tier ``COMPATIBILITY_BRIDGE``.

    These surfaces hold no canonical authority, must not grow, and
    should be removed once their migration-continuity purpose is fulfilled.

    Returns
    -------
    List[StabilizationSurfaceRecord]
        Surfaces with :attr:`StabilizationTier.COMPATIBILITY_BRIDGE`.
    """
    return [s for s in _BASELINE_CATALOG if s.tier == StabilizationTier.COMPATIBILITY_BRIDGE]


def classify_surface_tier(surface_id: str) -> Optional[StabilizationTier]:
    """Return the :class:`StabilizationTier` for *surface_id*, or ``None``.

    Parameters
    ----------
    surface_id:
        The ``surface_id`` to look up in the catalog.

    Returns
    -------
    StabilizationTier or None
        The tier for the surface, or ``None`` if the surface is not
        present in the catalog.
    """
    for record in _BASELINE_CATALOG:
        if record.surface_id == surface_id:
            return record.tier
    return None


def build_stabilization_baseline_snapshot() -> StabilizationBaselineSnapshot:
    """Build a full :class:`StabilizationBaselineSnapshot` from the catalog.

    Computes all tier counts, assembles the policy sentinel list, and
    returns a serialisable snapshot that can be surfaced via diagnostics
    endpoints or CI gates.

    Returns
    -------
    StabilizationBaselineSnapshot
        A point-in-time snapshot of the stabilization baseline state.
    """
    catalog = list(_BASELINE_CATALOG)

    canonical_stable = [s for s in catalog if s.tier == StabilizationTier.CANONICAL_STABLE]
    transitional = [s for s in catalog if s.tier == StabilizationTier.TRANSITIONAL_CONVERGING]
    extension = [s for s in catalog if s.tier == StabilizationTier.EXTENSION_SURFACE]
    compat_bridge = [s for s in catalog if s.tier == StabilizationTier.COMPATIBILITY_BRIDGE]
    extension_ready = [s for s in catalog if s.is_extension_ready]

    policy_sentinels = [
        CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY,
        TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY,
        EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY,
        COMPAT_BRIDGES_MUST_NOT_GROW_POLICY,
    ]

    return StabilizationBaselineSnapshot(
        snapshotted_at=time.time(),
        total_surface_count=len(catalog),
        canonical_stable_count=len(canonical_stable),
        transitional_converging_count=len(transitional),
        extension_surface_count=len(extension),
        compat_bridge_count=len(compat_bridge),
        extension_ready_count=len(extension_ready),
        policy_sentinels=policy_sentinels,
        surfaces=catalog,
    )
