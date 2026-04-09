#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_remaining_boundary_enforcement.py
============================================
PR-13: Finalize Node Boundary Enforcement — Explicit Classification of All
Remaining Node-Related Surfaces.

Problem addressed
-----------------
PRs 5–12 established canonical runtime paths and demoted several legacy
surfaces.  However, a number of node-related modules, routes, and helpers
were never explicitly classified as canonical, compat-only, internal-only,
or deprecated.  This creates ongoing ambiguity:

- Which surfaces are canonical authority for node runtime truth?
- Which ones are compatibility-only bridges to legacy paths?
- Which ones are internal implementation details not exposed externally?
- Which ones are deprecated and must not appear on active canonical paths?
- Which surfaces should dashboards, tools, and orchestration trust?

Without explicit boundary enforcement, compatibility layers can continue to
appear as peer authorities to canonical runtime paths, causing operators and
contributors to rely on the wrong surface for node system truth.

What this module does
---------------------
1. **Surface catalog** — :func:`build_remaining_surface_boundary_catalog`
   returns a machine-checkable list of :class:`NodeSurfaceBoundaryRecord`
   entries covering every remaining node-related surface not yet explicitly
   classified by PRs 5–12.

2. **Category enforcement** — :func:`validate_no_compat_as_primary_canonical_authority`
   asserts that no compat-only or deprecated surface is the sole/primary source
   for canonical node runtime truth.

3. **Operator visibility** — :func:`build_boundary_enforcement_summary` returns
   a structured summary that dashboards and operators can use to verify boundary
   compliance without reading source code.

4. **Policy sentinels** — four policy strings, each asserting a specific
   boundary rule that the remaining surfaces must satisfy.

Surface classification taxonomy
--------------------------------
:attr:`RemainingNodeSurfaceCategory.CANONICAL`
    This surface is a canonical runtime authority.  Dashboards and tools
    **must** use this surface as their primary truth source.

:attr:`RemainingNodeSurfaceCategory.COMPAT_ONLY`
    This surface is a backward-compatibility bridge only.  It may supplement
    canonical data for nodes not yet migrated, but **must not** serve as the
    primary or sole source of node runtime truth for any canonical consumer.

:attr:`RemainingNodeSurfaceCategory.INTERNAL_ONLY`
    This surface is an internal implementation detail.  It **must not** be
    used directly by external consumers, dashboards, or orchestration layers.
    It is only permissible for use within the modules that own it.

:attr:`RemainingNodeSurfaceCategory.DEPRECATED`
    This surface has been explicitly demoted.  It **must not** be reachable
    through any active canonical path.  Its presence in diagnostics is
    acceptable for discoverability but **must** be clearly labelled.

Canonical surfaces (classified by PRs 5–12, cross-referenced here)
--------------------------------------------------------------------
These surfaces were explicitly classified by prior PRs.  They are listed
here for completeness so that the full picture is available from one place.

- ``core.nodes.node_fabric_registry.NodeFabricRegistry`` — canonical runtime
  registry (PR canonical registry consolidation).
- ``core.node_invocation.invoke_node`` / ``UnifiedNodeExecutor`` — canonical
  invocation path (PR-4).
- ``core.fusion_entry_adapter.FusionEntryAdapterContract`` — canonical adapter
  contract (PR-5).
- ``core.node_governance_runtime`` — canonical governance eligibility (PR-6).
- ``core.node_discovery_runtime`` — canonical discovery runtime (PR-7).
- ``core.node_boundary_runtime`` — canonical boundary authority (PR-8).
- ``core.openclawd_canonical_node_tool_exposure`` — canonical tool exposure
  (PR-10).
- ``core.node_invocation_governance`` — canonical governance at invocation
  (PR-11).
- ``core.node_discovery_startup_health_closure`` — canonical discovery/health
  closure (PR-12).

Public API
----------
Authority sentinels::

    NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY
    NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL

Policy sentinels::

    COMPAT_SURFACES_MUST_NOT_BE_SOLE_CANONICAL_SOURCE_POLICY
    INTERNAL_SURFACES_MUST_NOT_BE_USED_BY_EXTERNAL_CONSUMERS_POLICY
    DEPRECATED_SURFACES_MUST_NOT_APPEAR_ON_ACTIVE_CANONICAL_PATHS_POLICY
    SYSTEM_STATUS_COMPAT_SUPPLEMENT_MUST_BE_EXPLICITLY_LABELLED_POLICY

Enums::

    RemainingNodeSurfaceCategory

Dataclasses::

    NodeSurfaceBoundaryRecord
    BoundaryEnforcementSummary

Functions::

    build_remaining_surface_boundary_catalog() -> list[NodeSurfaceBoundaryRecord]
    get_compat_only_surfaces() -> list[NodeSurfaceBoundaryRecord]
    get_internal_only_surfaces() -> list[NodeSurfaceBoundaryRecord]
    get_deprecated_surfaces() -> list[NodeSurfaceBoundaryRecord]
    validate_no_compat_as_primary_canonical_authority() -> bool
    build_boundary_enforcement_summary() -> dict
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeRemainingBoundaryEnforcement")

# ===========================================================================
# Authority sentinels
# ===========================================================================

#: Declares this module as the canonical authority for the final node boundary
#: enforcement pass (PR-13).
NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY: str = (
    "NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY_V1: "
    "core.node_remaining_boundary_enforcement is the canonical authority for "
    "classifying and enforcing the boundary categories of all remaining "
    "node-related surfaces not explicitly classified by PRs 5–12.  Every "
    "surface that was previously ambiguous — whether canonical, compat-only, "
    "internal-only, or deprecated — is given an explicit classification here. "
    "Compat-only surfaces must not serve as primary canonical truth sources. "
    "Internal-only surfaces must not be used by external consumers. "
    "Deprecated surfaces must not be reachable on active canonical paths."
)

#: PR-13 integration sentinel — machine-checkable proof that the remaining
#: node boundary enforcement gaps have been closed.
NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL: str = (
    "NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL_V1: "
    "all remaining node-related surfaces are explicitly classified as "
    "canonical, compat-only, internal-only, or deprecated; "
    "compat-only surfaces (NodeRegistry, node_registry.json scan, legacy "
    "HTTP supplement) are no longer ambiguous peer authorities to canonical "
    "runtime paths; internal surfaces (node_discovery, node_communication, "
    "node_protocol, node_factory_engine) are explicitly marked internal-only; "
    "system status endpoints expose a compat-supplement sentinel so operators "
    "can distinguish canonical from legacy data in a single API response; "
    "build_boundary_enforcement_summary() is available for operator dashboards."
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

#: Compat-only surfaces must never be the sole or primary source of canonical
#: node runtime truth for dashboards, orchestration, or status endpoints.
#: They may supplement canonical data for backward compatibility, but the
#: presence of a compat supplement must be explicitly labelled so operators
#: can distinguish it from canonical truth.
COMPAT_SURFACES_MUST_NOT_BE_SOLE_CANONICAL_SOURCE_POLICY: str = (
    "COMPAT_SURFACES_MUST_NOT_BE_SOLE_CANONICAL_SOURCE_POLICY_V1: "
    "Compat-only surfaces (core.node_registry.NodeRegistry, "
    "config/node_registry.json scan paths, and legacy HTTP supplement paths) "
    "must not be the sole or primary source of node runtime truth for any "
    "canonical consumer.  They may provide supplementary backward-compat data "
    "only when the canonical surface (NodeFabricRegistry) is unavailable or "
    "does not contain the requested node.  All such supplement access must be "
    "explicitly labelled with source='legacy' or equivalent in API responses, "
    "and the registry_authority field must always name the canonical source as "
    "the authoritative value."
)

#: Internal-only surfaces must not be imported or used directly by external
#: consumers, dashboards, or higher-level orchestration layers.
INTERNAL_SURFACES_MUST_NOT_BE_USED_BY_EXTERNAL_CONSUMERS_POLICY: str = (
    "INTERNAL_SURFACES_MUST_NOT_BE_USED_BY_EXTERNAL_CONSUMERS_POLICY_V1: "
    "Internal-only surfaces (core.node_discovery.NodeDiscoveryService for UDP "
    "discovery, core.node_communication for low-level networking, "
    "core.node_protocol for message framing, core.node_factory_engine for "
    "internal node instantiation) are implementation details.  They must not "
    "be imported or used directly by external consumers, dashboards, REST "
    "routes, or orchestration layers.  External consumers must use the "
    "canonical discovery surface (core.node_discovery_runtime) and the "
    "canonical invocation surface (core.node_invocation) instead."
)

#: Deprecated surfaces must not be reachable through any active canonical path.
#: Their presence in the codebase is acceptable but they must be clearly
#: labelled and must not silently provide data to canonical consumers.
DEPRECATED_SURFACES_MUST_NOT_APPEAR_ON_ACTIVE_CANONICAL_PATHS_POLICY: str = (
    "DEPRECATED_SURFACES_MUST_NOT_APPEAR_ON_ACTIVE_CANONICAL_PATHS_POLICY_V1: "
    "Deprecated node surfaces (direct nodes/ filesystem scan for node "
    "membership, config/node_registry.json as the primary node registry, "
    "the legacy node_status_cache as a canonical status source) must not "
    "be reachable through any active canonical path.  Their presence in the "
    "codebase for diagnostic or migration-aid purposes is acceptable, but they "
    "must be explicitly labelled DEPRECATED and must not silently feed data "
    "into canonical outputs without an explicit compat annotation."
)

#: The system status endpoint /api/v1/system/subsystems and /api/v1/nodes/status
#: must explicitly label any data derived from the legacy NodeRegistry supplement
#: so that operators can distinguish it from canonical NodeFabricRegistry data.
SYSTEM_STATUS_COMPAT_SUPPLEMENT_MUST_BE_EXPLICITLY_LABELLED_POLICY: str = (
    "SYSTEM_STATUS_COMPAT_SUPPLEMENT_MUST_BE_EXPLICITLY_LABELLED_POLICY_V1: "
    "When /api/v1/system/subsystems falls back to core.node_registry.NodeRegistry "
    "for the node count, the response must include registry_authority='legacy:NodeRegistry' "
    "and a compat_source_note field explaining that this is a fallback.  When "
    "/api/v1/nodes/status supplements canonical NodeFabricRegistry nodes with "
    "legacy NodeRegistry metadata, each supplementary node entry must carry "
    "source='legacy' and the top-level registry_authority must remain "
    "'canonical:NodeFabricRegistry'.  This ensures operators can distinguish "
    "canonical node data from compat bridge data without reading source code."
)

# ===========================================================================
# Enums
# ===========================================================================


class RemainingNodeSurfaceCategory(str, Enum):
    """Boundary category for a remaining node-related surface."""

    CANONICAL = "canonical"
    """Surface is a canonical runtime authority already classified by a prior PR."""

    COMPAT_ONLY = "compat_only"
    """Surface is a backward-compatibility bridge only.  Must not be the sole
    or primary source of canonical node runtime truth."""

    INTERNAL_ONLY = "internal_only"
    """Surface is an internal implementation detail.  Must not be used directly
    by external consumers, dashboards, or orchestration layers."""

    DEPRECATED = "deprecated"
    """Surface has been explicitly demoted.  Must not appear on active canonical
    paths."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class NodeSurfaceBoundaryRecord:
    """Describes the boundary classification of a single node-related surface.

    Attributes
    ----------
    surface_id:
        Short machine-readable identifier.
    display_name:
        Human-readable name for the surface.
    category:
        :class:`RemainingNodeSurfaceCategory` classification.
    canonical_replacement:
        The canonical surface that should be used instead (empty string for
        canonical surfaces themselves).
    pr_classified:
        The PR in which this surface received its explicit classification.
    notes:
        Additional context for operators and contributors.
    """

    surface_id: str
    display_name: str
    category: RemainingNodeSurfaceCategory
    canonical_replacement: str
    pr_classified: str = "PR-13"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "display_name": self.display_name,
            "category": self.category.value,
            "canonical_replacement": self.canonical_replacement,
            "pr_classified": self.pr_classified,
            "notes": self.notes,
        }


@dataclass
class BoundaryEnforcementSummary:
    """Summary of boundary enforcement status for all remaining node surfaces.

    Attributes
    ----------
    total_surfaces:
        Total number of classified surfaces.
    canonical_count:
        Number of surfaces classified as CANONICAL.
    compat_only_count:
        Number of surfaces classified as COMPAT_ONLY.
    internal_only_count:
        Number of surfaces classified as INTERNAL_ONLY.
    deprecated_count:
        Number of surfaces classified as DEPRECATED.
    no_compat_as_primary_authority:
        True when no compat-only surface is acting as the primary canonical
        authority (invariant enforced by
        :func:`validate_no_compat_as_primary_canonical_authority`).
    surfaces:
        All surface records.
    authority:
        The authority sentinel string.
    """

    total_surfaces: int = 0
    canonical_count: int = 0
    compat_only_count: int = 0
    internal_only_count: int = 0
    deprecated_count: int = 0
    no_compat_as_primary_authority: bool = True
    surfaces: List[NodeSurfaceBoundaryRecord] = field(default_factory=list)
    authority: str = NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_surfaces": self.total_surfaces,
            "canonical_count": self.canonical_count,
            "compat_only_count": self.compat_only_count,
            "internal_only_count": self.internal_only_count,
            "deprecated_count": self.deprecated_count,
            "no_compat_as_primary_authority": self.no_compat_as_primary_authority,
            "surfaces": [s.to_dict() for s in self.surfaces],
            "authority": self.authority,
        }


# ===========================================================================
# Static surface catalog
# ===========================================================================

#: Machine-checkable catalog of all remaining node-related surfaces that were
#: not explicitly classified by PRs 5–12.  Each entry states the category,
#: canonical replacement, and the PR in which the classification was made.
_REMAINING_SURFACE_CATALOGUE: List[NodeSurfaceBoundaryRecord] = [
    # ------------------------------------------------------------------
    # COMPAT-ONLY surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="node_registry_compat_facade_pr13",
        display_name="core.node_registry.NodeRegistry (compat facade)",
        category=RemainingNodeSurfaceCategory.COMPAT_ONLY,
        canonical_replacement=(
            "core.nodes.node_fabric_registry.NodeFabricRegistry "
            "(get_node_fabric_registry())"
        ),
        pr_classified="PR-13",
        notes=(
            "NodeRegistry is retained as a backward-compat facade only.  "
            "It was demoted in the canonical registry consolidation PR and "
            "now explicitly carries COMPAT_ONLY status.  System status "
            "endpoints that fall back to NodeRegistry must label their "
            "response with registry_authority='legacy:NodeRegistry' and "
            "must never present this data as primary canonical truth."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_registry_json_scan",
        display_name="config/node_registry.json — filesystem registry scan",
        category=RemainingNodeSurfaceCategory.COMPAT_ONLY,
        canonical_replacement=(
            "core.nodes.node_fabric_registry.NodeFabricRegistry "
            "(runtime registration via node_startup.py)"
        ),
        pr_classified="PR-13",
        notes=(
            "config/node_registry.json is a generated compat artifact.  "
            "It was used by the legacy Layer 3 discovery path "
            "(OpenClawd._collect_tools) which was disabled by default in "
            "PR-10.  It must not be used as a primary node registry source. "
            "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED=true re-enables it "
            "for explicit backward-compat scenarios only."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="system_status_legacy_supplement",
        display_name=(
            "GET /api/v1/system/subsystems — legacy NodeRegistry supplement"
        ),
        category=RemainingNodeSurfaceCategory.COMPAT_ONLY,
        canonical_replacement=(
            "GET /api/v1/system/subsystems with registry_authority="
            "'canonical:NodeFabricRegistry' (primary path)"
        ),
        pr_classified="PR-13",
        notes=(
            "When NodeFabricRegistry is unavailable, "
            "/api/v1/system/subsystems falls back to the legacy NodeRegistry "
            "for the node count.  This fallback is a compat-only bridge.  "
            "The response must carry registry_authority='legacy:NodeRegistry' "
            "and a compat_source_note so operators can identify compat data."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="nodes_status_legacy_supplement",
        display_name=(
            "GET /api/v1/nodes/status — legacy NodeRegistry node supplement"
        ),
        category=RemainingNodeSurfaceCategory.COMPAT_ONLY,
        canonical_replacement=(
            "GET /api/v1/nodes/status node entries with source='canonical' "
            "(NodeFabricRegistry primary path)"
        ),
        pr_classified="PR-13",
        notes=(
            "When /api/v1/nodes/status finds nodes in the legacy NodeRegistry "
            "that are not present in NodeFabricRegistry, it appends them with "
            "source='legacy'.  This is a compat-only supplement.  The "
            "top-level registry_authority field must remain "
            "'canonical:NodeFabricRegistry' to signal which surface is primary."
        ),
    ),
    # ------------------------------------------------------------------
    # INTERNAL-ONLY surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="node_discovery_udp_service",
        display_name="core.node_discovery.NodeDiscoveryService (UDP broadcast)",
        category=RemainingNodeSurfaceCategory.INTERNAL_ONLY,
        canonical_replacement=(
            "core.node_discovery_runtime — canonical discovery runtime "
            "(get_discovery_participation_summary(), "
            "build_discovery_runtime_snapshot())"
        ),
        pr_classified="PR-13",
        notes=(
            "NodeDiscoveryService performs UDP broadcast-based node discovery "
            "and is an internal implementation detail of the discovery layer. "
            "External consumers must use core.node_discovery_runtime functions "
            "for participation summaries and snapshots, not NodeDiscoveryService "
            "directly.  Health surfaces use build_discovery_health_surface() "
            "from core.node_discovery_startup_health_closure (PR-12)."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_communication_internal",
        display_name="core.node_communication — universal node communication",
        category=RemainingNodeSurfaceCategory.INTERNAL_ONLY,
        canonical_replacement=(
            "core.node_invocation.invoke_node() — canonical invocation path; "
            "core.capability_bus — canonical capability dispatch"
        ),
        pr_classified="PR-13",
        notes=(
            "node_communication implements low-level AODV-based routing, "
            "message ACK, load balancing, and TLS encryption for inter-node "
            "communication.  It is an internal networking layer and must not "
            "be used directly by external consumers, REST routes, or "
            "orchestration.  Node invocation must go through invoke_node(); "
            "capability dispatch must go through the canonical capability bus."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_protocol_internal",
        display_name="core.node_protocol — node message framing protocol",
        category=RemainingNodeSurfaceCategory.INTERNAL_ONLY,
        canonical_replacement=(
            "core.node_invocation — canonical invocation envelope "
            "(NodeInvocationEnvelope, NodeInvocationResult)"
        ),
        pr_classified="PR-13",
        notes=(
            "node_protocol defines low-level message types, framing, "
            "and request/response protocol for internal node communication. "
            "It is an internal implementation detail.  The canonical "
            "invocation contract for node execution is "
            "NodeInvocationEnvelope / NodeInvocationResult from "
            "core.node_invocation (PR-4)."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_factory_engine_internal",
        display_name="core.node_factory_engine — internal node instantiation",
        category=RemainingNodeSurfaceCategory.INTERNAL_ONLY,
        canonical_replacement=(
            "core.node_invocation.invoke_node() — canonical invocation; "
            "core.nodes.node_fabric_registry — canonical registration"
        ),
        pr_classified="PR-13",
        notes=(
            "node_factory_engine provides internal node instantiation and "
            "factory helpers.  It is an internal detail of the startup and "
            "registration pipeline.  External code must not instantiate nodes "
            "via this factory directly; instead, nodes are invoked through "
            "invoke_node() and registered through NodeFabricRegistry."
        ),
    ),
    # ------------------------------------------------------------------
    # DEPRECATED surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="nodes_dir_filesystem_scan",
        display_name="nodes/ directory filesystem scan for node membership",
        category=RemainingNodeSurfaceCategory.DEPRECATED,
        canonical_replacement=(
            "core.nodes.node_fabric_registry.NodeFabricRegistry — canonical "
            "node membership via runtime registration"
        ),
        pr_classified="PR-13",
        notes=(
            "Scanning the nodes/ directory for main.py or fusion_entry.py "
            "presence as the primary node-membership authority is deprecated. "
            "It was demoted in the canonical node list/detail/status PR "
            "(FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY).  "
            "It remains accessible as GET /api/v1/nodes/legacy/filesystem "
            "(compat/diagnostics path only) and must not be used as a primary "
            "node membership source."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_status_cache_as_canonical_status",
        display_name=(
            "core.routes._shared.node_status_cache — as canonical status source"
        ),
        category=RemainingNodeSurfaceCategory.DEPRECATED,
        canonical_replacement=(
            "core.nodes.node_fabric_registry.NodeFabricRegistry.list_nodes() "
            "— canonical status; core.node_discovery_startup_health_closure — "
            "canonical health surface"
        ),
        pr_classified="PR-13",
        notes=(
            "node_status_cache (the in-process shared dict) was demoted as a "
            "canonical status source by NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY. "
            "It must not be consulted by canonical list/detail status surfaces. "
            "Its residual presence is for internal bookkeeping and must not feed "
            "into canonical API responses as a primary source."
        ),
    ),
    # ------------------------------------------------------------------
    # CANONICAL surfaces (cross-referenced from prior PRs for completeness)
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="node_fabric_registry_canonical",
        display_name=(
            "core.nodes.node_fabric_registry.NodeFabricRegistry — canonical "
            "runtime registry"
        ),
        category=RemainingNodeSurfaceCategory.CANONICAL,
        canonical_replacement="",
        pr_classified="canonical registry consolidation PR",
        notes=(
            "NodeFabricRegistry is the single canonical runtime node registry. "
            "All node registration, status, and membership reads must use this "
            "surface.  Cross-referenced here for catalog completeness."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_invocation_canonical",
        display_name=(
            "core.node_invocation.invoke_node / UnifiedNodeExecutor — "
            "canonical invocation path"
        ),
        category=RemainingNodeSurfaceCategory.CANONICAL,
        canonical_replacement="",
        pr_classified="PR-4",
        notes=(
            "invoke_node() is the single canonical node execution entry point. "
            "All invocation paths must converge on it.  "
            "Cross-referenced here for catalog completeness."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_lifecycle_governor_canonical",
        display_name=(
            "core.node_lifecycle_governor.NodeLifecycleGovernor — canonical "
            "lifecycle governance"
        ),
        category=RemainingNodeSurfaceCategory.CANONICAL,
        canonical_replacement="",
        pr_classified="PR-531",
        notes=(
            "NodeLifecycleGovernor is the canonical lifecycle governance layer "
            "for newly onboarded and auto-generated nodes.  It gates nodes "
            "through REGISTERED → READINESS_CHECKED → CALLABLE_CLASSIFIED → "
            "CAPABILITY_REGISTERED → OPTIONAL/EXPERIMENTAL → ACTIVE → DEPRECATED "
            "stages.  Cross-referenced here for catalog completeness."
        ),
    ),
]


# ===========================================================================
# Public API functions
# ===========================================================================


def build_remaining_surface_boundary_catalog() -> List[NodeSurfaceBoundaryRecord]:
    """Return a copy of the static remaining surface boundary catalog.

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        All registered remaining node surface boundary records.
    """
    return list(_REMAINING_SURFACE_CATALOGUE)


def get_compat_only_surfaces() -> List[NodeSurfaceBoundaryRecord]:
    """Return all surfaces classified as :attr:`RemainingNodeSurfaceCategory.COMPAT_ONLY`.

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        Compat-only surface records.
    """
    return [
        r for r in _REMAINING_SURFACE_CATALOGUE
        if r.category == RemainingNodeSurfaceCategory.COMPAT_ONLY
    ]


def get_internal_only_surfaces() -> List[NodeSurfaceBoundaryRecord]:
    """Return all surfaces classified as :attr:`RemainingNodeSurfaceCategory.INTERNAL_ONLY`.

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        Internal-only surface records.
    """
    return [
        r for r in _REMAINING_SURFACE_CATALOGUE
        if r.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY
    ]


def get_deprecated_surfaces() -> List[NodeSurfaceBoundaryRecord]:
    """Return all surfaces classified as :attr:`RemainingNodeSurfaceCategory.DEPRECATED`.

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        Deprecated surface records.
    """
    return [
        r for r in _REMAINING_SURFACE_CATALOGUE
        if r.category == RemainingNodeSurfaceCategory.DEPRECATED
    ]


def get_canonical_surfaces() -> List[NodeSurfaceBoundaryRecord]:
    """Return all surfaces classified as :attr:`RemainingNodeSurfaceCategory.CANONICAL`.

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        Canonical surface records.
    """
    return [
        r for r in _REMAINING_SURFACE_CATALOGUE
        if r.category == RemainingNodeSurfaceCategory.CANONICAL
    ]


def validate_no_compat_as_primary_canonical_authority() -> bool:
    """Validate the core boundary invariant: no compat-only or deprecated
    surface serves as the sole/primary canonical authority.

    This function checks a structural invariant of the surface catalog:

    - Every :attr:`RemainingNodeSurfaceCategory.COMPAT_ONLY` surface must have
      a non-empty ``canonical_replacement`` pointing to the real authority.
    - Every :attr:`RemainingNodeSurfaceCategory.DEPRECATED` surface must have
      a non-empty ``canonical_replacement``.

    Returns
    -------
    bool
        ``True`` when the invariant holds (no compat/deprecated surface lacks
        a canonical replacement).  ``False`` if any violation is found, with
        a warning logged for each offending entry.
    """
    violations: List[str] = []

    for record in _REMAINING_SURFACE_CATALOGUE:
        if record.category in (
            RemainingNodeSurfaceCategory.COMPAT_ONLY,
            RemainingNodeSurfaceCategory.DEPRECATED,
        ):
            if not record.canonical_replacement.strip():
                violations.append(
                    f"surface '{record.surface_id}' (category={record.category.value}) "
                    "has no canonical_replacement — compat/deprecated surfaces must "
                    "always point to the canonical authority."
                )

    for v in violations:
        logger.warning("validate_no_compat_as_primary_canonical_authority: %s", v)

    return len(violations) == 0


def build_boundary_enforcement_summary() -> Dict[str, Any]:
    """Build a structured summary of boundary enforcement status.

    This function is intended for operator dashboards and diagnostic tools.
    It returns a dict that describes how many surfaces fall into each category,
    whether the compat-as-primary-authority invariant holds, and a full list
    of surface records.

    Returns
    -------
    dict
        Keys:

        - ``total_surfaces`` (int)
        - ``canonical_count`` (int)
        - ``compat_only_count`` (int)
        - ``internal_only_count`` (int)
        - ``deprecated_count`` (int)
        - ``no_compat_as_primary_authority`` (bool)
        - ``surfaces`` (list of dicts, each from
          :meth:`NodeSurfaceBoundaryRecord.to_dict`)
        - ``authority`` (str)
    """
    catalog = build_remaining_surface_boundary_catalog()

    canonical_count = sum(
        1 for r in catalog if r.category == RemainingNodeSurfaceCategory.CANONICAL
    )
    compat_only_count = sum(
        1 for r in catalog if r.category == RemainingNodeSurfaceCategory.COMPAT_ONLY
    )
    internal_only_count = sum(
        1 for r in catalog if r.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY
    )
    deprecated_count = sum(
        1 for r in catalog if r.category == RemainingNodeSurfaceCategory.DEPRECATED
    )

    summary = BoundaryEnforcementSummary(
        total_surfaces=len(catalog),
        canonical_count=canonical_count,
        compat_only_count=compat_only_count,
        internal_only_count=internal_only_count,
        deprecated_count=deprecated_count,
        no_compat_as_primary_authority=validate_no_compat_as_primary_canonical_authority(),
        surfaces=catalog,
        authority=NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
    )

    return summary.to_dict()
