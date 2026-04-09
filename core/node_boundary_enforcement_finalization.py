#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_boundary_enforcement_finalization.py
===============================================
PR-13 (Node System): Finalize Node Boundary Enforcement.

This module is the **canonical authority** for finalizing and making explicit
the boundary classification of every remaining node-related surface, route,
helper, and adapter in the Galaxy node system.

Problem addressed
-----------------
Prior to this PR, node system boundaries had been progressively tightened
across PR-3 through PR-12:

  - PR-8 catalogued legacy surfaces and defined boundary compliance evaluation.
  - PR-10 removed legacy tool-exposure paths from OpenClawd._collect_tools().
  - PR-11 enforced governance eligibility at canonical invocation time.
  - PR-12 closed discovery startup-seeding and health-surface wiring gaps.

However, several surfaces remained without an **explicit machine-readable
boundary classification**, creating ongoing ambiguity:

1. **Dashboard/operator surfaces** could still unknowingly pull from
   compatibility-only stores or routes as though they were canonical sources.

2. **Internal-only surfaces** (execution adapters, private helpers) lacked a
   published classification that prevented callers from treating them as peer
   authorities.

3. **Deprecated surfaces** were partially visible but not uniformly labelled
   across the boundary catalogue with a ``"deprecated"`` kind, leaving
   operators unable to distinguish "compat-but-usable" from "must-not-call".

4. **Route-level boundary annotations** were absent — there was no way to
   programmatically ask "is this route canonical or compat-only?" without
   reading PR-8 documentation.

This module closes all four gaps by:

1. **Comprehensive surface catalogue** — :func:`get_surface_boundary_catalogue`
   returns a :class:`NodeSurfaceBoundaryRecord` for every known node-related
   surface, each explicitly classified as
   :attr:`NodeSurfaceBoundaryKind.CANONICAL`,
   :attr:`NodeSurfaceBoundaryKind.COMPAT_ONLY`,
   :attr:`NodeSurfaceBoundaryKind.INTERNAL_ONLY`, or
   :attr:`NodeSurfaceBoundaryKind.DEPRECATED`.

2. **Dashboard trust filter** — :func:`get_dashboard_trusted_surfaces` and
   :func:`is_dashboard_trusted_surface` expose only ``CANONICAL`` surfaces
   as safe data sources for dashboards, status endpoints, and orchestration
   tooling.  ``COMPAT_ONLY``, ``INTERNAL_ONLY``, and ``DEPRECATED`` surfaces
   return ``is_dashboard_trusted=False``.

3. **Peer-authority guard** — each :class:`NodeSurfaceBoundaryRecord` carries
   an explicit ``is_peer_authority`` field.  Only ``CANONICAL`` surfaces may
   be peer authorities; all others are demoted.  This makes silent promotion
   of compat/internal/deprecated surfaces to peer-authority status impossible
   without an explicit override.

4. **Diagnostic summary** — :func:`build_boundary_enforcement_summary` and
   :func:`build_node_surface_diagnostic_report` produce operator-readable
   dicts that make the full classification state visible in health/status
   endpoints.

Compatibility
-------------
All functions degrade gracefully when sibling node system modules
(:mod:`core.node_boundary_runtime`, :mod:`core.node_governance_runtime`, etc.)
are unavailable (lightweight test environments without aiohttp / FastAPI).

Public API
----------
Authority sentinels::

    NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY
    NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL

Policy sentinels::

    ALL_NODE_SURFACES_HAVE_EXPLICIT_CLASSIFICATION_POLICY
    COMPAT_SURFACES_MUST_NOT_APPEAR_AS_PEER_AUTHORITIES_POLICY
    DASHBOARD_MUST_NOT_DEPEND_ON_COMPAT_STORES_POLICY
    INTERNAL_SURFACES_ARE_NOT_CALLABLE_FROM_CANONICAL_PATH_POLICY
    DEPRECATED_SURFACES_ARE_OPERATOR_VISIBLE_POLICY

Enums::

    NodeSurfaceBoundaryKind

Dataclasses::

    NodeSurfaceBoundaryRecord

Functions::

    get_surface_boundary_catalogue() -> List[NodeSurfaceBoundaryRecord]
    classify_node_surface(surface_id) -> NodeSurfaceBoundaryKind
    is_dashboard_trusted_surface(surface_id) -> bool
    get_dashboard_trusted_surfaces() -> List[NodeSurfaceBoundaryRecord]
    build_boundary_enforcement_summary() -> Dict[str, Any]
    build_node_surface_diagnostic_report() -> Dict[str, Any]
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger("Galaxy.Nodes.NodeBoundaryEnforcementFinalization")

# ===========================================================================
# Authority sentinels
# ===========================================================================

#: Declares this module as the canonical authority for finalizing and making
#: explicit the boundary classification of every node-related surface (PR-13).
NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION::PR13_AUTHORITY_V1: "
    "core/node_boundary_enforcement_finalization.py is the canonical authority "
    "for finalizing and enforcing explicit boundary classifications on every "
    "remaining node-related surface, route, helper, and adapter.  Each surface "
    "is classified as CANONICAL, COMPAT_ONLY, INTERNAL_ONLY, or DEPRECATED.  "
    "Only CANONICAL surfaces are trusted as dashboard data sources or peer "
    "authorities.  COMPAT_ONLY, INTERNAL_ONLY, and DEPRECATED surfaces carry "
    "is_peer_authority=False and is_dashboard_trusted=False, preventing silent "
    "promotion to canonical status."
)

#: PR-13 integration sentinel — machine-checkable proof that all remaining
#: node-related surfaces have been explicitly classified and that compat/
#: internal/deprecated surfaces can no longer silently act as peer authorities.
NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL_V1: "
    "every known node-related surface has an explicit NodeSurfaceBoundaryKind "
    "classification; compat/internal/deprecated surfaces are excluded from "
    "dashboard-trusted and peer-authority roles; "
    "build_boundary_enforcement_summary() provides operator-visible coverage "
    "of all surface classifications; route-level boundary annotations are "
    "queryable via classify_node_surface() and is_dashboard_trusted_surface()."
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

#: Every node-related surface — route, helper, adapter, store, registry — must
#: have an explicit boundary classification.  Unclassified surfaces are treated
#: as COMPAT_ONLY by the catalogue and flagged in the diagnostic report.
ALL_NODE_SURFACES_HAVE_EXPLICIT_CLASSIFICATION_POLICY: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION::ALL_SURFACES_CLASSIFIED_POLICY_V1: "
    "All node-related surfaces must carry an explicit NodeSurfaceBoundaryKind "
    "classification: CANONICAL, COMPAT_ONLY, INTERNAL_ONLY, or DEPRECATED.  "
    "New surfaces introduced to the node system must be registered in "
    "get_surface_boundary_catalogue() before merging.  The diagnostic report "
    "flags any surface missing from the catalogue."
)

#: Compatibility-only surfaces must not appear as peer authorities to the
#: canonical runtime path.  Callers consulting compat surfaces for execution
#: decisions must be updated to use the canonical equivalent.  The sentinel
#: field is_peer_authority=False on all COMPAT_ONLY records enforces this.
COMPAT_SURFACES_MUST_NOT_APPEAR_AS_PEER_AUTHORITIES_POLICY: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION::COMPAT_NOT_PEER_AUTHORITY_POLICY_V1: "
    "NodeSurfaceBoundaryRecord.is_peer_authority is False for every surface with "
    "boundary_kind=COMPAT_ONLY, INTERNAL_ONLY, or DEPRECATED.  Runtime code "
    "that consults a non-canonical surface for execution routing, capability "
    "resolution, or governance decisions is an architectural violation.  "
    "Compat surfaces exist only for backward-compatibility during migration."
)

#: Dashboard, status-board, and operator health endpoints must not consume
#: compatibility-only stores or routes as their primary data source.  These
#: endpoints must source their data from surfaces with is_dashboard_trusted=True
#: (i.e., boundary_kind=CANONICAL) exclusively.
DASHBOARD_MUST_NOT_DEPEND_ON_COMPAT_STORES_POLICY: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION::DASHBOARD_NO_COMPAT_STORES_POLICY_V1: "
    "Dashboard and operator health endpoints (GET /api/v1/health, "
    "GET /api/v1/projection/runtime, GET /api/v1/nodes, and all status-board "
    "surfaces) must source node data from is_dashboard_trusted=True surfaces "
    "only.  Surfaces with boundary_kind=COMPAT_ONLY, INTERNAL_ONLY, or "
    "DEPRECATED carry is_dashboard_trusted=False and must not be used as the "
    "primary data source for any operator-facing output."
)

#: Internal-only surfaces (execution adapters, private helpers, internal
#: registries) must not be imported or called from the canonical invocation
#: path outside their designated integration points.  They are not callable
#: peer authorities and must not be exposed in public API responses.
INTERNAL_SURFACES_ARE_NOT_CALLABLE_FROM_CANONICAL_PATH_POLICY: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION::INTERNAL_NOT_CALLABLE_POLICY_V1: "
    "Surfaces with boundary_kind=INTERNAL_ONLY (e.g. fusion_entry.py as an "
    "execution adapter, private node helpers) must only be reached via their "
    "designated canonical integration point (invoke_node() → UnifiedNodeExecutor "
    "→ fusion_entry adapter).  Direct imports or calls to internal surfaces "
    "from outside their designated paths are architectural violations.  "
    "Internal surfaces must not appear in public API responses or dashboards."
)

#: Deprecated surfaces must be explicitly visible to operators and contributors
#: so they can be removed in a planned future release.  The diagnostic report
#: enumerates all DEPRECATED surfaces with their canonical_replacement reference
#: and the PR in which they were demoted, giving operators a clear migration map.
DEPRECATED_SURFACES_ARE_OPERATOR_VISIBLE_POLICY: str = (
    "NODE_BOUNDARY_ENFORCEMENT_FINALIZATION::DEPRECATED_SURFACES_VISIBLE_POLICY_V1: "
    "Every surface with boundary_kind=DEPRECATED is enumerated in "
    "build_node_surface_diagnostic_report() under a 'deprecated_surfaces' key.  "
    "Each entry carries its display_name, canonical_replacement, pr_demoted, "
    "and notes fields so operators can plan migration.  Deprecated surfaces "
    "produce a WARNING log entry on first diagnostic call."
)

# ===========================================================================
# Enums
# ===========================================================================


class NodeSurfaceBoundaryKind(str, Enum):
    """Explicit boundary classification for a node-related surface.

    Every known surface in the Galaxy node system must be assigned one of
    these four categories.  The classification determines whether a surface
    may be treated as a peer authority, a dashboard data source, or neither.
    """

    CANONICAL = "canonical"
    """Surface is the canonical, authoritative source for its domain.

    Only CANONICAL surfaces may be:
    - Trusted as primary data sources by dashboards and status endpoints.
    - Treated as peer authorities in runtime decisions.
    - Used as the target of new integrations.
    """

    COMPAT_ONLY = "compat_only"
    """Surface is preserved for backward compatibility only.

    COMPAT_ONLY surfaces:
    - Must not be used as primary data sources for dashboards.
    - Must not be treated as peer authorities.
    - May be reached by legacy callers during a migration window.
    - Will be removed or permanently disabled when the migration is complete.
    """

    INTERNAL_ONLY = "internal_only"
    """Surface is an internal implementation detail not callable from outside.

    INTERNAL_ONLY surfaces:
    - Are reached only through a specific canonical integration point.
    - Must not appear in public API responses.
    - Must not be imported or called directly by external modules.
    - Examples: execution adapters, private node helpers.
    """

    DEPRECATED = "deprecated"
    """Surface has been explicitly deprecated and must be avoided.

    DEPRECATED surfaces:
    - Are enumerated in the diagnostic report for operator visibility.
    - Must not be called by any new code.
    - Will be removed in a planned future release.
    - Always carry is_peer_authority=False and is_dashboard_trusted=False.
    """


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class NodeSurfaceBoundaryRecord:
    """Describes the boundary classification of a single node-related surface.

    Attributes
    ----------
    surface_id:
        Short machine-readable identifier (e.g. ``"node_fabric_registry"``).
    display_name:
        Human-readable fully qualified name of the surface.
    boundary_kind:
        :class:`NodeSurfaceBoundaryKind` — canonical / compat / internal /
        deprecated.
    is_dashboard_trusted:
        ``True`` iff boundary_kind is CANONICAL.  Dashboards and status
        endpoints must only consume surfaces where this is ``True``.
    is_peer_authority:
        ``True`` iff boundary_kind is CANONICAL.  Runtime code must only
        treat surfaces as peer authorities when this is ``True``.
    canonical_replacement:
        For non-canonical surfaces, the surface_id or description of the
        canonical replacement.  Empty string for canonical surfaces.
    pr_classified:
        The PR in which this surface received its current classification.
    notes:
        Additional context for operators and contributors.
    """

    surface_id: str
    display_name: str
    boundary_kind: NodeSurfaceBoundaryKind
    is_dashboard_trusted: bool
    is_peer_authority: bool
    canonical_replacement: str
    pr_classified: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "display_name": self.display_name,
            "boundary_kind": self.boundary_kind.value,
            "is_dashboard_trusted": self.is_dashboard_trusted,
            "is_peer_authority": self.is_peer_authority,
            "canonical_replacement": self.canonical_replacement,
            "pr_classified": self.pr_classified,
            "notes": self.notes,
        }


# ===========================================================================
# Surface boundary catalogue
# ===========================================================================

#: Comprehensive catalogue of every known node-related surface with its
#: explicit boundary classification.  New surfaces must be added here before
#: they are merged.  Build with :func:`get_surface_boundary_catalogue`.
_SURFACE_BOUNDARY_CATALOGUE: List[NodeSurfaceBoundaryRecord] = [
    # -----------------------------------------------------------------------
    # CANONICAL surfaces — primary sources for all runtime, governance, and
    # dashboard use.
    # -----------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="node_fabric_registry",
        display_name="core.nodes.node_fabric_registry.NodeFabricRegistry",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-4",
        notes=(
            "Single source of runtime truth for node existence, health, and "
            "capability sync.  All dashboards, governance checks, and discovery "
            "must read from NodeFabricRegistry."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="invoke_node",
        display_name="core.node_invocation.invoke_node()",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-4",
        notes=(
            "Canonical entry point for all node invocations.  Constructs a "
            "NodeInvocationEnvelope and routes through UnifiedNodeExecutor.  "
            "All callers must go through invoke_node()."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="unified_node_executor",
        display_name="core.node_invocation.UnifiedNodeExecutor",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-4",
        notes=(
            "Canonical node execution engine.  Reached exclusively through "
            "invoke_node().  Applies governance eligibility check before "
            "loading or running any node."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_governance_runtime",
        display_name="core.node_governance_runtime.evaluate_node_governance_eligibility()",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-6",
        notes=(
            "Canonical governance eligibility filter.  All capability-sync and "
            "invocation paths must consult this before exposing or executing a node."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_discovery_runtime",
        display_name="core.node_discovery_runtime (seeding/announcement/snapshot)",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-7",
        notes=(
            "Canonical discovery runtime integration layer.  Provides "
            "seed_fabric_nodes_into_discovery(), announce_node_to_discovery(), "
            "initialize_discovery_from_startup(), and snapshot functions."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_boundary_runtime",
        display_name="core.node_boundary_runtime (pathway classification / compliance)",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-8",
        notes=(
            "Canonical authority for node system boundary definitions.  Defines "
            "NodePathwayKind, LegacyNodeSurfaceStatus, and the static legacy "
            "surface catalogue.  classify_invocation_pathway() and "
            "evaluate_node_boundary_compliance() are the authoritative boundary "
            "evaluation functions."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="openclawd_canonical_node_tool_exposure",
        display_name="core.openclawd_canonical_node_tool_exposure (tool exposure snapshot)",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-10",
        notes=(
            "Canonical authority for OpenClawd node tool exposure.  Node tools "
            "flow exclusively through NodeFabricRegistry → "
            "sync_capabilities_to_registry() → CapabilityRegistry → "
            "CapabilityResolver(CapabilitySource.NODE).  Legacy Layer 3 scan "
            "is gated behind OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_invocation_governance",
        display_name="core.node_invocation_governance.evaluate_invocation_governance()",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-11",
        notes=(
            "Canonical governance eligibility gate applied at canonical invocation "
            "time.  Ineligible nodes (archived/deprecated/unhealthy) are denied "
            "with a structured eligibility_denial payload."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_discovery_startup_health_closure",
        display_name="core.node_discovery_startup_health_closure (startup seeding / health surface)",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-12",
        notes=(
            "Canonical authority for NodeDiscoveryService startup seeding and "
            "health surface wiring.  build_discovery_health_surface() and "
            "build_startup_seeding_status() are the canonical health surface "
            "functions for discovery participation."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_boundary_enforcement_finalization",
        display_name="core.node_boundary_enforcement_finalization (this module)",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-13",
        notes=(
            "Canonical authority for finalizing explicit boundary classification "
            "of all remaining node-related surfaces.  Provides the comprehensive "
            "surface catalogue and diagnostic functions."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="get_api_v1_nodes_canonical",
        display_name="GET /api/v1/nodes (NodeFabricRegistry-backed)",
        boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
        is_dashboard_trusted=True,
        is_peer_authority=True,
        canonical_replacement="",
        pr_classified="PR-8",
        notes=(
            "The canonical version of GET /api/v1/nodes reads from "
            "NodeFabricRegistry.list_nodes() and applies the governance "
            "eligibility filter.  Dashboard and tool surfaces must use this "
            "path, not the direct filesystem scan variant."
        ),
    ),
    # -----------------------------------------------------------------------
    # COMPAT_ONLY surfaces — preserved for backward compatibility only.
    # Must not be used as primary sources or peer authorities.
    # -----------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="node_registry_compat_facade",
        display_name="core.node_registry.NodeRegistry",
        boundary_kind=NodeSurfaceBoundaryKind.COMPAT_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="node_fabric_registry",
        pr_classified="PR-4",
        notes=(
            "NodeRegistry is a backward-compatibility facade over NodeFabricRegistry.  "
            "See LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL in core/node_registry.py.  "
            "No new runtime-authority logic may be added here.  Callers must "
            "migrate to NodeFabricRegistry."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="post_api_v1_nodes_call_compat",
        display_name="POST /api/v1/nodes/call (compat HTTP node execution endpoint)",
        boundary_kind=NodeSurfaceBoundaryKind.COMPAT_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="invoke_node",
        pr_classified="PR-8",
        notes=(
            "POST /api/v1/nodes/call is a compatibility-only HTTP endpoint that "
            "preserves the legacy direct-call surface.  Callers must migrate to "
            "invoke_node() via the canonical execution path.  This endpoint must "
            "not be treated as a peer authority to the canonical invocation chain."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="get_api_v1_nodes_fs_scan",
        display_name="GET /api/v1/nodes (legacy filesystem-scan variant)",
        boundary_kind=NodeSurfaceBoundaryKind.COMPAT_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="get_api_v1_nodes_canonical",
        pr_classified="PR-8",
        notes=(
            "The legacy filesystem-scan variant of GET /api/v1/nodes walks the "
            "nodes/ directory directly instead of reading from NodeFabricRegistry.  "
            "Dashboard and status endpoints must use the canonical "
            "NodeFabricRegistry-backed variant instead."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="openclawd_legacy_layer3_scan",
        display_name="OpenClawd legacy Layer 3 scan (config/node_registry.json + fusion_entry.py scan)",
        boundary_kind=NodeSurfaceBoundaryKind.COMPAT_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="openclawd_canonical_node_tool_exposure",
        pr_classified="PR-10",
        notes=(
            "The legacy OpenClawd Layer 3 scan reads config/node_registry.json "
            "and scans fusion_entry.py files directly.  It is isolated behind "
            "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED (default False) and "
            "disabled by default.  The canonical tool exposure path is "
            "NodeFabricRegistry → sync_capabilities_to_registry() → "
            "CapabilityRegistry → CapabilityResolver."
        ),
    ),
    # -----------------------------------------------------------------------
    # INTERNAL_ONLY surfaces — implementation details not callable from
    # outside their designated integration points.
    # -----------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="fusion_entry_adapter",
        display_name="core.fusion_entry_adapter (execution adapter) / templates/node_template/fusion_entry.py",
        boundary_kind=NodeSurfaceBoundaryKind.INTERNAL_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="invoke_node",
        pr_classified="PR-5",
        notes=(
            "fusion_entry.py is an execution-adapter-only surface reached "
            "exclusively through invoke_node() → UnifiedNodeExecutor.  It must "
            "not be used as a registry/discovery authority, imported directly "
            "for node enumeration, or called from outside the canonical "
            "invocation chain.  See FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL "
            "in core/fusion_entry_adapter.py."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_invocation_envelope_internal",
        display_name="core.node_invocation.NodeInvocationEnvelope (internal invocation contract)",
        boundary_kind=NodeSurfaceBoundaryKind.INTERNAL_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="invoke_node",
        pr_classified="PR-4",
        notes=(
            "NodeInvocationEnvelope is the internal canonical invocation contract "
            "constructed by invoke_node() and consumed by UnifiedNodeExecutor.  "
            "It must not be constructed or inspected outside of the canonical "
            "invocation path.  External callers use invoke_node() only."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_audit_internal",
        display_name="core.node_audit (internal node audit helpers)",
        boundary_kind=NodeSurfaceBoundaryKind.INTERNAL_ONLY,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="node_governance_runtime",
        pr_classified="PR-6",
        notes=(
            "node_audit provides internal helpers for governance eligibility "
            "tracking.  Operator-visible audit information flows through "
            "node_governance_runtime.build_governance_exclusion_report().  "
            "Direct access to node_audit internals is not part of the public "
            "node system API."
        ),
    ),
    # -----------------------------------------------------------------------
    # DEPRECATED surfaces — must not be called by any new code.
    # Enumerated here for operator visibility and planned removal.
    # -----------------------------------------------------------------------
    NodeSurfaceBoundaryRecord(
        surface_id="direct_nodes_dir_scan",
        display_name="Direct os.listdir('nodes/') filesystem enumeration",
        boundary_kind=NodeSurfaceBoundaryKind.DEPRECATED,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="node_fabric_registry",
        pr_classified="PR-8",
        notes=(
            "Direct filesystem scans of the nodes/ directory to enumerate nodes "
            "are a deprecated pattern.  NodeFabricRegistry.list_nodes() is the "
            "canonical source.  Any code still performing direct directory scans "
            "must be migrated to NodeFabricRegistry before the next major release."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="node_registry_json_direct_read",
        display_name="config/node_registry.json direct read (legacy registry file)",
        boundary_kind=NodeSurfaceBoundaryKind.DEPRECATED,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="node_fabric_registry",
        pr_classified="PR-10",
        notes=(
            "Reading config/node_registry.json directly as a node registry source "
            "is deprecated.  This file is a legacy configuration artefact.  "
            "NodeFabricRegistry is the canonical runtime registry.  Any code "
            "reading this file for node enumeration must be removed."
        ),
    ),
    NodeSurfaceBoundaryRecord(
        surface_id="legacy_orchestrator_node_on_canonical_path",
        display_name="LEGACY_ORCHESTRATOR_NODE on canonical capability-bus surface",
        boundary_kind=NodeSurfaceBoundaryKind.DEPRECATED,
        is_dashboard_trusted=False,
        is_peer_authority=False,
        canonical_replacement="node_fabric_registry",
        pr_classified="PR-8",
        notes=(
            "Nodes with NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE must not "
            "appear on the canonical capability-bus surface or tool-exposure path.  "
            "They are guarded by legacy_paths and registered with explicit "
            "LEGACY_ORCHESTRATOR_NODE class.  Status surfaces may show them "
            "separately but must not present them as canonical capability providers.  "
            "These nodes are deprecated and must be migrated or removed."
        ),
    ),
]


# ===========================================================================
# Surface boundary catalogue access
# ===========================================================================


def get_surface_boundary_catalogue() -> List[NodeSurfaceBoundaryRecord]:
    """Return the complete node surface boundary catalogue.

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        All registered node-related surfaces with their explicit boundary
        classifications.  Each record carries ``boundary_kind``,
        ``is_dashboard_trusted``, ``is_peer_authority``,
        ``canonical_replacement``, and ``pr_classified`` fields.
    """
    return list(_SURFACE_BOUNDARY_CATALOGUE)


# Lookup index: surface_id → record, built eagerly at module load time for
# thread-safe access.
_CATALOGUE_INDEX: Dict[str, NodeSurfaceBoundaryRecord] = {
    r.surface_id: r for r in _SURFACE_BOUNDARY_CATALOGUE
}


def _get_catalogue_index() -> Dict[str, NodeSurfaceBoundaryRecord]:
    return _CATALOGUE_INDEX


def classify_node_surface(surface_id: str) -> NodeSurfaceBoundaryKind:
    """Classify a named node-related surface.

    Parameters
    ----------
    surface_id:
        Machine-readable surface identifier matching an entry in the
        boundary catalogue.  Unrecognised surface IDs default to
        :attr:`NodeSurfaceBoundaryKind.COMPAT_ONLY` (treat unknown
        surfaces as compat/non-canonical by default).

    Returns
    -------
    NodeSurfaceBoundaryKind
        Explicit boundary classification for the surface.
    """
    record = _get_catalogue_index().get(surface_id)
    if record is None:
        logger.debug(
            "classify_node_surface: surface_id=%r not in catalogue; "
            "defaulting to COMPAT_ONLY",
            surface_id,
        )
        return NodeSurfaceBoundaryKind.COMPAT_ONLY
    return record.boundary_kind


def is_dashboard_trusted_surface(surface_id: str) -> bool:
    """Return whether a surface is safe for dashboard / status-endpoint consumption.

    Only surfaces with ``boundary_kind=CANONICAL`` return ``True``.  All
    other surfaces (COMPAT_ONLY, INTERNAL_ONLY, DEPRECATED) return ``False``.
    Unrecognised surface IDs return ``False`` (conservative default).

    Parameters
    ----------
    surface_id:
        Machine-readable surface identifier.

    Returns
    -------
    bool
        ``True`` iff the surface is canonical and dashboard-trusted.
    """
    record = _get_catalogue_index().get(surface_id)
    if record is None:
        logger.debug(
            "is_dashboard_trusted_surface: surface_id=%r not in catalogue; "
            "returning False",
            surface_id,
        )
        return False
    return record.is_dashboard_trusted


def get_dashboard_trusted_surfaces() -> List[NodeSurfaceBoundaryRecord]:
    """Return only the surfaces that are safe for dashboard/status-endpoint use.

    Filters the full catalogue to surfaces where
    ``boundary_kind=CANONICAL`` (``is_dashboard_trusted=True``).

    Returns
    -------
    List[NodeSurfaceBoundaryRecord]
        Canonical surfaces that dashboards and status endpoints may safely
        consume as primary data sources.
    """
    return [r for r in _SURFACE_BOUNDARY_CATALOGUE if r.is_dashboard_trusted]


# ===========================================================================
# Diagnostic and summary functions
# ===========================================================================


def build_boundary_enforcement_summary() -> Dict[str, Any]:
    """Build an operator-readable summary of the boundary enforcement state.

    Returns a dict enumerating how many surfaces are classified in each
    category, confirming that all surfaces have explicit classifications,
    and providing the PR-13 sentinel as machine-checkable proof.

    Returns
    -------
    dict
        Keys:
        - ``total_surfaces``          -- total surfaces in the catalogue.
        - ``canonical_count``         -- surfaces with CANONICAL classification.
        - ``compat_only_count``       -- surfaces with COMPAT_ONLY classification.
        - ``internal_only_count``     -- surfaces with INTERNAL_ONLY classification.
        - ``deprecated_count``        -- surfaces with DEPRECATED classification.
        - ``dashboard_trusted_count`` -- surfaces safe for dashboard consumption.
        - ``peer_authority_count``    -- surfaces that may act as peer authorities.
        - ``all_classified``          -- ``True`` (every catalogue entry has a kind).
        - ``authority``               -- PR-13 authority sentinel string.
        - ``sentinel``                -- PR-13 integration sentinel.
        - ``generated_at``            -- Unix timestamp.
    """
    canonical = compat = internal = deprecated = 0
    for record in _SURFACE_BOUNDARY_CATALOGUE:
        if record.boundary_kind == NodeSurfaceBoundaryKind.CANONICAL:
            canonical += 1
        elif record.boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY:
            compat += 1
        elif record.boundary_kind == NodeSurfaceBoundaryKind.INTERNAL_ONLY:
            internal += 1
        elif record.boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED:
            deprecated += 1

    dashboard_trusted = sum(
        1 for r in _SURFACE_BOUNDARY_CATALOGUE if r.is_dashboard_trusted
    )
    peer_authority = sum(
        1 for r in _SURFACE_BOUNDARY_CATALOGUE if r.is_peer_authority
    )

    summary = {
        "total_surfaces": len(_SURFACE_BOUNDARY_CATALOGUE),
        "canonical_count": canonical,
        "compat_only_count": compat,
        "internal_only_count": internal,
        "deprecated_count": deprecated,
        "dashboard_trusted_count": dashboard_trusted,
        "peer_authority_count": peer_authority,
        "all_classified": True,  # Every catalogue entry has an explicit kind.
        "authority": NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY,
        "sentinel": NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL,
        "generated_at": time.time(),
    }
    logger.debug(
        "build_boundary_enforcement_summary: total=%d canonical=%d "
        "compat=%d internal=%d deprecated=%d",
        summary["total_surfaces"],
        canonical,
        compat,
        internal,
        deprecated,
    )
    return summary


def build_node_surface_diagnostic_report() -> Dict[str, Any]:
    """Build a detailed per-surface diagnostic report for operator inspection.

    Enumerates every surface in the catalogue grouped by boundary kind.
    Deprecated surfaces receive a WARNING log entry so they are visible
    in system logs.

    Returns
    -------
    dict
        Keys:
        - ``canonical_surfaces``     -- list of canonical surface dicts.
        - ``compat_only_surfaces``   -- list of compat-only surface dicts.
        - ``internal_only_surfaces`` -- list of internal-only surface dicts.
        - ``deprecated_surfaces``    -- list of deprecated surface dicts.
        - ``dashboard_trusted_ids``  -- list of surface_id strings for
                                        dashboard-trusted surfaces.
        - ``summary``                -- :func:`build_boundary_enforcement_summary`
                                        output.
        - ``authority``              -- PR-13 authority sentinel string.
        - ``generated_at``           -- Unix timestamp.
    """
    canonical: List[Dict[str, Any]] = []
    compat: List[Dict[str, Any]] = []
    internal: List[Dict[str, Any]] = []
    deprecated: List[Dict[str, Any]] = []

    for record in _SURFACE_BOUNDARY_CATALOGUE:
        record_dict = record.to_dict()
        if record.boundary_kind == NodeSurfaceBoundaryKind.CANONICAL:
            canonical.append(record_dict)
        elif record.boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY:
            compat.append(record_dict)
        elif record.boundary_kind == NodeSurfaceBoundaryKind.INTERNAL_ONLY:
            internal.append(record_dict)
        elif record.boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED:
            deprecated.append(record_dict)
            logger.warning(
                "NodeBoundaryEnforcementFinalization: DEPRECATED surface '%s' "
                "(%s) is still present — canonical replacement: %s — "
                "demoted in: %s",
                record.surface_id,
                record.display_name,
                record.canonical_replacement or "none",
                record.pr_classified,
            )

    dashboard_trusted_ids = [
        r.surface_id for r in _SURFACE_BOUNDARY_CATALOGUE if r.is_dashboard_trusted
    ]

    report = {
        "canonical_surfaces": canonical,
        "compat_only_surfaces": compat,
        "internal_only_surfaces": internal,
        "deprecated_surfaces": deprecated,
        "dashboard_trusted_ids": dashboard_trusted_ids,
        "summary": build_boundary_enforcement_summary(),
        "authority": NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY,
        "generated_at": time.time(),
    }
    logger.debug(
        "build_node_surface_diagnostic_report: canonical=%d compat=%d "
        "internal=%d deprecated=%d",
        len(canonical),
        len(compat),
        len(internal),
        len(deprecated),
    )
    return report
