#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_final_boundary_enforcement.py
========================================
PR-13 (node track): Finalize Node Boundary Enforcement.

This module is the **canonical authority** for finalizing node boundary
classification and preventing remaining compatibility surfaces from
functioning as peer authorities to canonical runtime paths.

Prior work (PR-5 through PR-12) established the canonical registry
(:mod:`core.nodes.node_fabric_registry`), canonical invocation
(:mod:`core.node_invocation`), governance eligibility
(:mod:`core.node_invocation_governance`), tool-exposure boundary
(:mod:`core.openclawd_canonical_node_tool_exposure`), and discovery/health
wiring (:mod:`core.node_discovery_startup_health_closure`).

However, several surfaces remained without an explicit boundary category:

  - ``core.routes._shared.node_status_cache`` — a legacy in-memory dict
    still read by ``GET /api/v1/system/status`` for ``nodes.total`` and
    ``nodes.active`` counts, making it appear to be a live canonical source.
  - ``core.routes.compat`` / ``core.routes.devices`` — still pass
    ``node_status_cache`` keys to ``available_nodes`` in device-registration
    responses.
  - ``core.node_lifecycle_governor`` — node lifecycle helpers that have no
    explicit boundary label (internal-only, not exposed as a canonical surface).
  - ``core.node_factory_engine`` — node construction helper, internal-only.
  - ``core.node_deps_helpers`` — internal-only dependency helper.

This module closes those gaps by:

1. **Explicit boundary classification** — every remaining node-related
   surface is assigned a :class:`NodeSurfaceBoundaryCategory` and entered
   into the static :func:`build_node_surface_classification_registry`.

2. **Policy enforcement** — four policy sentinels make it machine-checkable
   that ``node_status_cache`` is NOT a canonical authority and that system
   dashboards must prefer :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
   as the source of node-count truth.

3. **Canonical node count helper** — :func:`get_node_count_from_canonical_source`
   reads from ``NodeFabricRegistry`` and returns an explicit ``source`` key
   (``"canonical:NodeFabricRegistry"`` vs ``"compat_fallback:node_status_cache"``)
   so that every caller can see which authority was used.

4. **Snapshot surface** — :func:`build_final_boundary_snapshot` assembles a
   diagnostic dict summarising canonical vs. compat vs. internal vs. deprecated
   surface counts for inclusion in ``/api/v1/health``, CLI inspect, and
   dashboard endpoints.

Compatibility
-------------
All functions degrade gracefully when
:mod:`core.nodes.node_fabric_registry` is unavailable.

Public API
----------
Authority sentinels::

    NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY
    NODE_FINAL_BOUNDARY_ENFORCEMENT_PR13_SENTINEL

Policy sentinels::

    NODE_STATUS_CACHE_IS_COMPAT_NOT_CANONICAL_POLICY
    SYSTEM_STATUS_NODES_COUNT_MUST_PREFER_CANONICAL_REGISTRY_POLICY
    COMPAT_SURFACES_ARE_NOT_PEER_AUTHORITIES_POLICY
    DASHBOARD_SURFACES_MUST_USE_CANONICAL_SOURCES_POLICY

Enums::

    NodeSurfaceBoundaryCategory

Dataclasses::

    NodeSurfaceBoundaryEntry
    NodeFinalBoundarySnapshot

Functions::

    build_node_surface_classification_registry() -> List[NodeSurfaceBoundaryEntry]
    get_compat_only_surfaces() -> List[NodeSurfaceBoundaryEntry]
    get_deprecated_surfaces() -> List[NodeSurfaceBoundaryEntry]
    get_node_count_from_canonical_source(registry=None) -> dict
    build_final_boundary_snapshot(registry=None) -> NodeFinalBoundarySnapshot
    get_final_boundary_summary(registry=None) -> dict
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Nodes.NodeFinalBoundaryEnforcement")

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY: str = (
    "NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY_V1: "
    "core.node_final_boundary_enforcement is the canonical authority for "
    "finalizing node surface boundary classification.  Every remaining "
    "node-related route, helper, adapter, and store is explicitly categorized "
    "as CANONICAL, COMPAT_ONLY, INTERNAL_ONLY, or DEPRECATED.  "
    "node_status_cache is confirmed as COMPAT_ONLY and must not be used as "
    "the primary source of node counts in system dashboards.  "
    "NodeFabricRegistry is the canonical source of node presence and status."
)

#: PR-13 machine-checkable integration sentinel.
NODE_FINAL_BOUNDARY_ENFORCEMENT_PR13_SENTINEL: str = (
    "NODE_FINAL_BOUNDARY_ENFORCEMENT_PR13_SENTINEL_V1: "
    "PR-13 (node track) — node boundary classification finalized.  "
    "build_node_surface_classification_registry() enumerates all surfaces.  "
    "get_node_count_from_canonical_source() prefers NodeFabricRegistry and "
    "surfaces the authority source explicitly.  system/status endpoint "
    "updated to prefer canonical registry over node_status_cache."
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

#: node_status_cache is a legacy in-memory dict — it is a compatibility
#: artifact that must not be treated as a live canonical source of node truth.
NODE_STATUS_CACHE_IS_COMPAT_NOT_CANONICAL_POLICY: str = (
    "NODE_STATUS_CACHE_IS_COMPAT_NOT_CANONICAL_POLICY_V1: "
    "core.routes._shared.node_status_cache is a COMPAT_ONLY store.  "
    "It reflects legacy writes and does NOT represent the authoritative "
    "runtime node registry.  Its keys must not be used as the primary "
    "measure of 'total' or 'active' nodes in canonical dashboards or "
    "health surfaces.  Use NodeFabricRegistry.list_nodes() instead."
)

#: The system/status endpoint must source node counts from the canonical
#: registry, not from the legacy compat cache.
SYSTEM_STATUS_NODES_COUNT_MUST_PREFER_CANONICAL_REGISTRY_POLICY: str = (
    "SYSTEM_STATUS_NODES_COUNT_MUST_PREFER_CANONICAL_REGISTRY_POLICY_V1: "
    "GET /api/v1/system/status nodes.total and nodes.active MUST be derived "
    "from NodeFabricRegistry.list_nodes() as the primary source.  "
    "node_status_cache may be used as a fallback only when NodeFabricRegistry "
    "is unavailable, and the response must include a 'node_count_source' key "
    "indicating which authority was used."
)

#: Compat surfaces carry no canonical authority — they may not silently peer
#: with canonical execution or discovery paths.
COMPAT_SURFACES_ARE_NOT_PEER_AUTHORITIES_POLICY: str = (
    "COMPAT_SURFACES_ARE_NOT_PEER_AUTHORITIES_POLICY_V1: "
    "Surfaces classified as COMPAT_ONLY (node_status_cache, legacy_filesystem "
    "route, NodeRegistry compat facade, fusion_entry legacy scan) carry no "
    "canonical authority.  They must not be consulted by canonical execution, "
    "governance, discovery, or health paths without an explicit compat "
    "justification documented at the call site."
)

#: Dashboard and summary surfaces must consume canonical sources.
DASHBOARD_SURFACES_MUST_USE_CANONICAL_SOURCES_POLICY: str = (
    "DASHBOARD_SURFACES_MUST_USE_CANONICAL_SOURCES_POLICY_V1: "
    "Operator dashboards, /api/v1/system/status, /api/v1/health, and any "
    "status-board surface must derive node counts and node status from "
    "NodeFabricRegistry (canonical) and must not treat node_status_cache, "
    "node_registry_compat_facade, or legacy filesystem scans as primary "
    "sources of node runtime truth."
)

# ===========================================================================
# Enums
# ===========================================================================


class NodeSurfaceBoundaryCategory(str, Enum):
    """Explicit boundary category for a node-related surface.

    Every remaining node route, helper, adapter, or store must be assigned
    one of these categories so that operators and contributors can determine
    at a glance which surfaces are authoritative.
    """

    CANONICAL = "canonical"
    """Surface is the authoritative runtime source.  Canonical surfaces are
    the correct destination for new code, dashboards, and higher-level
    orchestration."""

    COMPAT_ONLY = "compat_only"
    """Surface is preserved for backward compatibility.  Must not be treated
    as a peer authority to canonical surfaces.  New code must not introduce
    new dependencies on these surfaces."""

    INTERNAL_ONLY = "internal_only"
    """Surface is an internal implementation helper.  Not exposed as a public
    API surface; callers outside the node subsystem should not depend on it
    directly."""

    DEPRECATED = "deprecated"
    """Surface has been formally demoted and is scheduled for removal.
    Existing callers should migrate to the canonical replacement."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class NodeSurfaceBoundaryEntry:
    """Boundary classification record for a single node-related surface."""

    surface_id: str
    """Machine-readable identifier for the surface."""

    display_name: str
    """Human-readable fully-qualified name of the surface."""

    category: NodeSurfaceBoundaryCategory
    """Explicit boundary category."""

    canonical_replacement: Optional[str]
    """Canonical replacement surface ID (if this surface is COMPAT_ONLY or
    DEPRECATED).  ``None`` for CANONICAL and INTERNAL_ONLY surfaces."""

    rationale: str
    """One-line explanation of the classification decision."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "display_name": self.display_name,
            "category": self.category.value,
            "canonical_replacement": self.canonical_replacement,
            "rationale": self.rationale,
        }


@dataclass
class NodeFinalBoundarySnapshot:
    """Aggregate snapshot of all classified node surfaces."""

    total_surfaces: int = 0
    canonical_count: int = 0
    compat_only_count: int = 0
    internal_only_count: int = 0
    deprecated_count: int = 0
    entries: List[NodeSurfaceBoundaryEntry] = field(default_factory=list)

    #: Canonical node count as reported by NodeFabricRegistry (or -1 if
    #: registry was unavailable).
    canonical_node_count: int = -1

    #: Indicates which authority provided the node count.
    node_count_source: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_surfaces": self.total_surfaces,
            "canonical_count": self.canonical_count,
            "compat_only_count": self.compat_only_count,
            "internal_only_count": self.internal_only_count,
            "deprecated_count": self.deprecated_count,
            "canonical_node_count": self.canonical_node_count,
            "node_count_source": self.node_count_source,
            "entries": [e.to_dict() for e in self.entries],
            "authority": NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
        }


# ===========================================================================
# Static surface classification catalogue
# ===========================================================================

#: All remaining node-related surfaces with their explicit boundary category.
_SURFACE_CATALOGUE: List[NodeSurfaceBoundaryEntry] = [
    # ------------------------------------------------------------------
    # CANONICAL surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryEntry(
        surface_id="node_fabric_registry",
        display_name="core.nodes.node_fabric_registry.NodeFabricRegistry",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale=(
            "Canonical runtime node registry established in PR-3/PR-4.  "
            "All canonical node presence and status reads must use this."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="invoke_node",
        display_name="core.node_invocation.invoke_node",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale=(
            "Canonical node invocation entry point established in PR-4.  "
            "All node execution must route through invoke_node()."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_governance_runtime",
        display_name="core.node_governance_runtime",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale="Canonical governance eligibility engine (PR-6).",
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_discovery_runtime",
        display_name="core.node_discovery_runtime",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale="Canonical discovery runtime integration authority (PR-7).",
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_boundary_runtime",
        display_name="core.node_boundary_runtime",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale="Canonical node pathway classification authority (PR-8).",
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_invocation_governance",
        display_name="core.node_invocation_governance",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale="Canonical governance gate at invocation time (PR-11).",
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_discovery_startup_health_closure",
        display_name="core.node_discovery_startup_health_closure",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale=(
            "Canonical authority for discovery startup seeding and health "
            "surface wiring (PR-12)."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="canonical_node_list_route",
        display_name="GET /api/v1/nodes (core.routes.nodes)",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale=(
            "Canonical node list/detail surface deriving membership from "
            "NodeFabricRegistry (PR-3)."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="canonical_node_call_route",
        display_name="POST /api/v1/nodes/call (core.routes.nodes)",
        category=NodeSurfaceBoundaryCategory.CANONICAL,
        canonical_replacement=None,
        rationale="Canonical node invocation route routing through invoke_node().",
    ),
    # ------------------------------------------------------------------
    # COMPAT_ONLY surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryEntry(
        surface_id="node_status_cache",
        display_name="core.routes._shared.node_status_cache",
        category=NodeSurfaceBoundaryCategory.COMPAT_ONLY,
        canonical_replacement="node_fabric_registry",
        rationale=(
            "Legacy in-memory dict populated by legacy node write paths.  "
            "Must not be used as the primary source of node counts in "
            "dashboards or health surfaces.  NodeFabricRegistry is canonical."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_registry_compat_facade",
        display_name="core.node_registry.NodeRegistry",
        category=NodeSurfaceBoundaryCategory.COMPAT_ONLY,
        canonical_replacement="node_fabric_registry",
        rationale=(
            "Backward-compatibility facade over NodeFabricRegistry (PR-3).  "
            "New code must use NodeFabricRegistry directly."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="legacy_filesystem_node_list_route",
        display_name="GET /api/v1/nodes/legacy/filesystem",
        category=NodeSurfaceBoundaryCategory.COMPAT_ONLY,
        canonical_replacement="canonical_node_list_route",
        rationale=(
            "Explicit legacy compat surface performing filesystem-based node "
            "scanning.  Intended for diagnostics only; not canonical runtime "
            "authority."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="compat_device_register_available_nodes",
        display_name=(
            "core.routes.compat / core.routes.devices — "
            "available_nodes from node_status_cache"
        ),
        category=NodeSurfaceBoundaryCategory.COMPAT_ONLY,
        canonical_replacement="node_fabric_registry",
        rationale=(
            "Device-registration responses include available_nodes sourced "
            "from node_status_cache.  This is a compat convenience field; "
            "the canonical node list is GET /api/v1/nodes."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="fusion_entry_adapter",
        display_name="core.fusion_entry_adapter / templates/node_template/fusion_entry.py",
        category=NodeSurfaceBoundaryCategory.COMPAT_ONLY,
        canonical_replacement="invoke_node",
        rationale=(
            "Execution adapter only (PR-5).  Must not be used for registry "
            "or discovery.  invoke_node() is canonical for all invocation."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="openclawd_legacy_node_scan",
        display_name=(
            "core.openclawd_canonical_node_tool_exposure — "
            "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED layer"
        ),
        category=NodeSurfaceBoundaryCategory.COMPAT_ONLY,
        canonical_replacement="node_fabric_registry",
        rationale=(
            "Legacy Layer-3 scan (node_registry.json + fusion_entry.py) "
            "disabled by default in OpenClawd._collect_tools() (PR-10).  "
            "Re-enabled only via OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED=true."
        ),
    ),
    # ------------------------------------------------------------------
    # INTERNAL_ONLY surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryEntry(
        surface_id="node_lifecycle_governor",
        display_name="core.node_lifecycle_governor",
        category=NodeSurfaceBoundaryCategory.INTERNAL_ONLY,
        canonical_replacement=None,
        rationale=(
            "Internal lifecycle management helper used within the node "
            "subsystem.  Not a public surface; external code must not "
            "depend on it directly."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_factory_engine",
        display_name="core.node_factory_engine",
        category=NodeSurfaceBoundaryCategory.INTERNAL_ONLY,
        canonical_replacement=None,
        rationale=(
            "Internal node construction helper.  Not a public API surface; "
            "node instantiation is an implementation detail of NodeFabricRegistry."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="node_deps_helpers",
        display_name="core.node_deps_helpers",
        category=NodeSurfaceBoundaryCategory.INTERNAL_ONLY,
        canonical_replacement=None,
        rationale=(
            "Internal dependency resolution helpers for the node subsystem.  "
            "Not a canonical execution surface."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="callable_node_baseline",
        display_name="core.callable_node_baseline",
        category=NodeSurfaceBoundaryCategory.INTERNAL_ONLY,
        canonical_replacement=None,
        rationale=(
            "Phase-B callable-class baseline.  An internal classification "
            "helper that mirrors _CAPABILITY_SYNC_ELIGIBLE from "
            "NodeFabricRegistry.  Not a standalone authority."
        ),
    ),
    # ------------------------------------------------------------------
    # DEPRECATED surfaces
    # ------------------------------------------------------------------
    NodeSurfaceBoundaryEntry(
        surface_id="node_registry_direct_read",
        display_name="core.node_registry.NodeRegistry — direct registry reads",
        category=NodeSurfaceBoundaryCategory.DEPRECATED,
        canonical_replacement="node_fabric_registry",
        rationale=(
            "Direct reads from the legacy NodeRegistry (e.g. "
            "get_node_registry().get_node_metadata()) are deprecated.  "
            "Use NodeFabricRegistry.get_node() or list_nodes() instead."
        ),
    ),
    NodeSurfaceBoundaryEntry(
        surface_id="system_status_node_count_from_compat_cache",
        display_name=(
            "GET /api/v1/system/status — nodes.total/active from "
            "node_status_cache (legacy path)"
        ),
        category=NodeSurfaceBoundaryCategory.DEPRECATED,
        canonical_replacement="node_fabric_registry",
        rationale=(
            "Previously, GET /api/v1/system/status derived nodes.total and "
            "nodes.active from node_status_cache (compat).  This is now "
            "deprecated in favour of NodeFabricRegistry as the primary source "
            "(PR-13 alignment).  The response now includes node_count_source "
            "to make the authority explicit."
        ),
    ),
]


# ===========================================================================
# Public API
# ===========================================================================


def build_node_surface_classification_registry() -> List[NodeSurfaceBoundaryEntry]:
    """Return the complete list of classified node-related surfaces.

    Returns
    -------
    List[NodeSurfaceBoundaryEntry]
        All surfaces in the static catalogue, in canonical-first order.
    """
    return list(_SURFACE_CATALOGUE)


def get_compat_only_surfaces() -> List[NodeSurfaceBoundaryEntry]:
    """Return only the COMPAT_ONLY surfaces.

    Returns
    -------
    List[NodeSurfaceBoundaryEntry]
        Surfaces classified as :attr:`NodeSurfaceBoundaryCategory.COMPAT_ONLY`.
    """
    return [e for e in _SURFACE_CATALOGUE if e.category == NodeSurfaceBoundaryCategory.COMPAT_ONLY]


def get_deprecated_surfaces() -> List[NodeSurfaceBoundaryEntry]:
    """Return only the DEPRECATED surfaces.

    Returns
    -------
    List[NodeSurfaceBoundaryEntry]
        Surfaces classified as :attr:`NodeSurfaceBoundaryCategory.DEPRECATED`.
    """
    return [e for e in _SURFACE_CATALOGUE if e.category == NodeSurfaceBoundaryCategory.DEPRECATED]


def get_node_count_from_canonical_source(
    registry: Any = None,
) -> Dict[str, Any]:
    """Return node total and active counts from the canonical source.

    Prefers :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`.
    Falls back to the legacy ``node_status_cache`` compat store only when
    the canonical registry is unavailable.

    Parameters
    ----------
    registry:
        An optional pre-constructed ``NodeFabricRegistry`` instance.
        When ``None``, the module-level singleton is loaded via
        ``get_node_fabric_registry()``.

    Returns
    -------
    dict
        Keys: ``total`` (int), ``active`` (int), ``node_count_source`` (str),
        ``authority`` (str).
    """
    fab = registry
    if fab is None:
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            fab = get_node_fabric_registry()
        except Exception as exc:
            logger.debug("get_node_count_from_canonical_source: registry unavailable: %s", exc)
            fab = None

    if fab is not None:
        try:
            all_nodes = fab.list_nodes()
            total = len(all_nodes)
            try:
                healthy = fab.list_healthy()
                active = len(healthy)
            except Exception:
                active = sum(
                    1 for n in all_nodes
                    if getattr(getattr(n, "status", None), "value", str(getattr(n, "status", ""))).lower()
                    in ("running", "ready", "active")
                )
            return {
                "total": total,
                "active": active,
                "node_count_source": "canonical:NodeFabricRegistry",
                "authority": NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
            }
        except Exception as exc:
            logger.debug("get_node_count_from_canonical_source: list_nodes failed: %s", exc)

    # Compat fallback: node_status_cache
    try:
        from core.routes._shared import node_status_cache as _cache  # type: ignore[attr-defined]
        total = len(_cache)
        active = sum(1 for n in _cache.values() if n.get("status") == "running")
        return {
            "total": total,
            "active": active,
            "node_count_source": "compat_fallback:node_status_cache",
            "authority": NODE_STATUS_CACHE_IS_COMPAT_NOT_CANONICAL_POLICY,
        }
    except Exception as exc:
        logger.debug("get_node_count_from_canonical_source: compat fallback failed: %s", exc)

    return {
        "total": 0,
        "active": 0,
        "node_count_source": "unavailable",
        "authority": NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
    }


def build_final_boundary_snapshot(
    registry: Any = None,
) -> NodeFinalBoundarySnapshot:
    """Build a complete snapshot of classified node surfaces plus canonical counts.

    Parameters
    ----------
    registry:
        Optional ``NodeFabricRegistry`` instance for the canonical node count.

    Returns
    -------
    NodeFinalBoundarySnapshot
    """
    entries = build_node_surface_classification_registry()
    canonical_count = sum(
        1 for e in entries if e.category == NodeSurfaceBoundaryCategory.CANONICAL
    )
    compat_count = sum(
        1 for e in entries if e.category == NodeSurfaceBoundaryCategory.COMPAT_ONLY
    )
    internal_count = sum(
        1 for e in entries if e.category == NodeSurfaceBoundaryCategory.INTERNAL_ONLY
    )
    deprecated_count = sum(
        1 for e in entries if e.category == NodeSurfaceBoundaryCategory.DEPRECATED
    )

    node_counts = get_node_count_from_canonical_source(registry=registry)

    return NodeFinalBoundarySnapshot(
        total_surfaces=len(entries),
        canonical_count=canonical_count,
        compat_only_count=compat_count,
        internal_only_count=internal_count,
        deprecated_count=deprecated_count,
        entries=entries,
        canonical_node_count=node_counts["total"],
        node_count_source=node_counts["node_count_source"],
    )


def get_final_boundary_summary(registry: Any = None) -> Dict[str, Any]:
    """Return a compact summary dict suitable for health and dashboard surfaces.

    Parameters
    ----------
    registry:
        Optional ``NodeFabricRegistry`` instance.

    Returns
    -------
    dict
        Summary with surface counts, canonical node count, and authority.
    """
    snap = build_final_boundary_snapshot(registry=registry)
    return {
        "total_surfaces": snap.total_surfaces,
        "canonical_count": snap.canonical_count,
        "compat_only_count": snap.compat_only_count,
        "internal_only_count": snap.internal_only_count,
        "deprecated_count": snap.deprecated_count,
        "canonical_node_count": snap.canonical_node_count,
        "node_count_source": snap.node_count_source,
        "authority": NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
    }
