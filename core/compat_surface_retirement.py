#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/compat_surface_retirement.py
===================================
PR-10 (realization-v2 convergence plan): Explicit compatibility-surface
retirement inventory, tier classification, and roadmap.

Background
----------
After PRs #6–#9 the canonical governance layers are well-defined.  However,
the system still carries many compatibility-era surfaces — legacy routes,
shared caches, transitional registry facades, alias-based protocol surfaces,
and older dispatch/projection adapters.  Some of these remain visible enough
to be mistaken for canonical surfaces, creating a *compatibility authority
illusion* where future work may continue to route through legacy or
transitional surfaces even after canonical replacements exist.

This module resolves that risk by:

1. **Inventorying** all high-risk compatibility surfaces that carry
   meaningful operational exposure.
2. **Classifying** each surface into a retirement tier:
   - **TIER_1** — Immediate retirement target.  Minimal active callers;
     canonical replacement is fully available; may be removed in the
     next cleanup batch.
   - **TIER_2** — Near-term retirement target.  Some active callers remain;
     migration is underway; must not receive new features; targeted for
     removal within 1–2 batches.
   - **TIER_3** — Long-term retirement target.  Active callers are present
     but a clear canonical replacement exists; migration must be tracked;
     must not be treated as a canonical authority.
3. **Labeling** each surface with a ``RetirementStatus`` that makes its
   non-canonical nature explicit and machine-checkable.
4. Providing a **concrete roadmap** so cleanup batches can make targeted
   retirement decisions rather than broadly deleting code.

Design principles
-----------------
- **Additive only** — this module does not modify any existing module.
  It provides vocabulary and a queryable governance surface that other
  modules can import.
- **Honest about callers** — no surface is marked TIER_1 unless its
  active caller set is genuinely minimal.
- **Machine-checkable** — all sentinels are importable strings that CI
  gates, tests, and diagnostic endpoints can assert.
- **Roadmap-first** — every record carries the removal condition so
  cleanup PRs have concrete acceptance criteria.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY`
:data:`COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL`
:data:`HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY`
:data:`COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY`
:data:`RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY`
:data:`COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY`

Enums
~~~~~
:class:`RetirementTier`
:class:`RetirementStatus`
:class:`CompatSurfaceRisk`

Data classes
~~~~~~~~~~~~
:class:`CompatSurfaceRecord`
:class:`RetirementRoadmapSummary`

Functions
~~~~~~~~~
:func:`get_compat_surface_inventory`
:func:`get_surfaces_by_tier`
:func:`get_high_risk_surfaces`
:func:`build_retirement_roadmap_summary`
:func:`classify_surface_tier`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY",
    "COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL",
    "HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY",
    "COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY",
    "RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY",
    "COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY",
    # Enums
    "RetirementTier",
    "RetirementStatus",
    "CompatSurfaceRisk",
    # Data classes
    "CompatSurfaceRecord",
    "RetirementRoadmapSummary",
    # Functions
    "get_compat_surface_inventory",
    "get_surfaces_by_tier",
    "get_high_risk_surfaces",
    "build_retirement_roadmap_summary",
    "classify_surface_tier",
]

# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY: str = (
    "COMPAT_SURFACE_RETIREMENT_IS_CANONICAL_AUTHORITY_PR10: "
    "core.compat_surface_retirement is the canonical authority for the "
    "compatibility-surface retirement inventory, tier classification, and "
    "roadmap for the realization-v2 repository.  "
    "All high-risk compatibility surfaces must be registered here with an "
    "explicit retirement tier and removal condition.  "
    "No compatibility surface is to be treated as a canonical governance "
    "layer; this module ensures that distinction is machine-checkable."
)

COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL: str = (
    "COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL_V1: "
    "PR-10 compatibility-surface retirement plan is active.  "
    "High-risk compat surfaces are inventoried and tier-classified.  "
    "The system is transitioning from strong governance plus broad "
    "compatibility coexistence toward governed convergence plus a shrinking "
    "compatibility footprint.  Each TIER_1/TIER_2/TIER_3 surface has an "
    "explicit roadmap entry and removal condition."
)

#: Every high-risk compatibility surface must appear in the inventory so
#: it cannot be silently promoted to canonical status.
HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY: str = (
    "HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY_V1: "
    "All compatibility surfaces that carry meaningful operational exposure "
    "(active routes, shared caches, registry facades, protocol shims, "
    "dispatch adapters) MUST be registered in the compat surface inventory "
    "with an explicit retirement tier.  Unlisted compat surfaces with "
    "operational exposure are policy violations."
)

#: A compatibility surface must never be treated as or promote itself as a
#: canonical governance authority.
COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY: str = (
    "COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY_V1: "
    "Compatibility surfaces MUST NOT present themselves as canonical "
    "governance layers, status authorities, schema authorities, or "
    "architectural sources of truth.  Any surface classified as "
    "COMPAT_ONLY, LEGACY_COMPAT, or TRANSITIONAL must carry an explicit "
    "marker (sentinel, deprecation warning, or LEGACY_SURFACE.md) that "
    "identifies it as non-canonical.  "
    "Consumers must be directed to the canonical replacement."
)

#: Each surface must carry an explicit tier assignment — undecided or
#: ambiguous tier is not permitted for inventoried surfaces.
RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY: str = (
    "RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY_V1: "
    "Every compat surface in the inventory MUST carry an explicit "
    "RetirementTier assignment.  A tier of TIER_UNDECIDED is permitted "
    "only for surfaces added in the same batch PR and pending initial "
    "review.  No surface may remain TIER_UNDECIDED across batch boundaries."
)

#: The total compatibility footprint must shrink, not grow, across batch PRs.
COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY: str = (
    "COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY_V1: "
    "Each batch PR cycle must retire at least one TIER_1 surface or "
    "downgrade at least one TIER_2 surface to TIER_1.  New compatibility "
    "surfaces may only be introduced when a new canonical replacement is "
    "not yet fully stable, and they must be inventoried at TIER_2 or "
    "below immediately.  The compat surface count must trend downward."
)

# ===========================================================================
# Enumerations
# ===========================================================================


class RetirementTier(Enum):
    """Urgency tier for retiring a compatibility surface."""

    TIER_1 = "tier_1"
    """Immediate retirement target.

    Minimal active callers; canonical replacement is fully available and
    stable; may be removed in the next cleanup batch without risk.
    """

    TIER_2 = "tier_2"
    """Near-term retirement target.

    Some active callers remain; migration is underway; must not receive
    new features; targeted for removal within 1–2 batch PRs.
    """

    TIER_3 = "tier_3"
    """Long-term retirement target.

    Active callers are present; a clear canonical replacement exists;
    migration must be tracked and must not be treated as a canonical
    authority; no forced removal timeline yet.
    """

    TIER_UNDECIDED = "tier_undecided"
    """Tier has not yet been assigned.

    Permitted only for surfaces added in the same batch PR and awaiting
    initial review.  Must not persist across batch boundaries.
    """


class RetirementStatus(Enum):
    """Current lifecycle status of a compatibility surface."""

    COMPAT_ONLY = "compat_only"
    """Surface exists solely for backward-compatibility.

    Must not carry new logic.  Canonical replacement is available.
    """

    LEGACY_COMPAT = "legacy_compat"
    """Surface carries active production traffic from legacy callers.

    Still required; canonical replacement exists; migration in progress.
    """

    TRANSITIONAL = "transitional"
    """Surface is a transitional shim between old and new canonical surfaces.

    Expected to be eliminated once migration completes.
    """

    HARD_DEPRECATED = "hard_deprecated"
    """Surface emits DeprecationWarning; no production callers remain.

    Targeted for physical deletion in the next or next-next batch.
    """

    TOMBSTONE = "tombstone"
    """Surface is a re-export shim only; all logic has been moved.

    Safe to delete; retained only for import-path backward compatibility.
    """


class CompatSurfaceRisk(Enum):
    """Risk level if this surface is mistaken for a canonical layer."""

    HIGH = "high"
    """Surface is prominent enough to be mistaken for a canonical authority.

    Examples: route files that serve active endpoints, registry facades
    that expose a similar API to the canonical registry.
    """

    MEDIUM = "medium"
    """Surface may be used as a shortcut by new contributors.

    Examples: helper modules with public-sounding names that shadow
    canonical equivalents.
    """

    LOW = "low"
    """Surface is clearly marked as non-canonical and unlikely to cause confusion.

    Examples: modules inside ``legacy/`` directories, tombstone shims
    with hard errors on import.
    """


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class CompatSurfaceRecord:
    """Inventory record for a single compatibility surface."""

    surface_id: str
    """Unique identifier (snake_case)."""

    module_path: str
    """Dotted Python module path or file path for documentation purposes."""

    surface_name: str
    """Human-readable name."""

    status: RetirementStatus
    """Current lifecycle status."""

    tier: RetirementTier
    """Retirement urgency tier."""

    risk: CompatSurfaceRisk
    """Risk of confusion with canonical layers."""

    canonical_replacement: str
    """Dotted module path or route of the canonical replacement."""

    removal_condition: str
    """Concrete, verifiable condition under which this surface may be deleted."""

    notes: str = ""
    """Additional governance notes."""

    pr_guardrail_added: str = ""
    """PR where this surface was explicitly classified (if known)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "status": self.status.value,
            "tier": self.tier.value,
            "risk": self.risk.value,
            "canonical_replacement": self.canonical_replacement,
            "removal_condition": self.removal_condition,
            "notes": self.notes,
            "pr_guardrail_added": self.pr_guardrail_added,
        }


@dataclass
class RetirementRoadmapSummary:
    """Aggregate summary of the compatibility-surface retirement roadmap."""

    total_surfaces: int
    tier_1_count: int
    tier_2_count: int
    tier_3_count: int
    tier_undecided_count: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    hard_deprecated_count: int
    tombstone_count: int
    legacy_compat_count: int
    compat_only_count: int
    transitional_count: int
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_surfaces": self.total_surfaces,
            "by_tier": {
                "tier_1": self.tier_1_count,
                "tier_2": self.tier_2_count,
                "tier_3": self.tier_3_count,
                "tier_undecided": self.tier_undecided_count,
            },
            "by_risk": {
                "high": self.high_risk_count,
                "medium": self.medium_risk_count,
                "low": self.low_risk_count,
            },
            "by_status": {
                "compat_only": self.compat_only_count,
                "legacy_compat": self.legacy_compat_count,
                "transitional": self.transitional_count,
                "hard_deprecated": self.hard_deprecated_count,
                "tombstone": self.tombstone_count,
            },
            "policy_sentinels": self.policy_sentinels,
        }


# ===========================================================================
# Compat surface inventory
# ===========================================================================

_COMPAT_SURFACE_INVENTORY: List[CompatSurfaceRecord] = [
    # -------------------------------------------------------------------------
    # 1. Legacy device / Android compat routes
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="routes_compat_legacy_device_api",
        module_path="core.routes.compat",
        surface_name="Legacy Device API Compat Router (core/routes/compat.py)",
        status=RetirementStatus.LEGACY_COMPAT,
        tier=RetirementTier.TIER_2,
        risk=CompatSurfaceRisk.HIGH,
        canonical_replacement="core.routes.devices (/api/v1/devices/*)",
        removal_condition=(
            "Remove when all legacy Android/device callers are confirmed migrated "
            "to /api/v1/devices/* endpoints and no 4xx/5xx traffic is observed on "
            "/api/devices/* for at least one release cycle."
        ),
        notes=(
            "Serves active production traffic from legacy Android clients that "
            "have not yet migrated to /api/v1/devices/*.  Emits DeprecationWarning "
            "at router creation.  Must not be extended with new logic.  "
            "HIGH risk: the route surface is identical in shape to canonical "
            "device routes, making it easy to mistake for the canonical endpoint."
        ),
        pr_guardrail_added="PR-5",
    ),
    # -------------------------------------------------------------------------
    # 2. NodeRegistry compat facade
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="node_registry_compat_facade",
        module_path="core.node_registry.NodeRegistry",
        surface_name="NodeRegistry (compat facade over NodeFabricRegistry)",
        status=RetirementStatus.COMPAT_ONLY,
        tier=RetirementTier.TIER_2,
        risk=CompatSurfaceRisk.HIGH,
        canonical_replacement="core.nodes.node_fabric_registry.NodeFabricRegistry",
        removal_condition=(
            "Remove when all callers that import NodeRegistry have been redirected "
            "to NodeFabricRegistry and the LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL "
            "has no test-only callers remaining."
        ),
        notes=(
            "NodeRegistry is a compat facade (LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL) "
            "over the canonical NodeFabricRegistry.  It provides backward-compatible "
            "node listing APIs but is not authoritative.  "
            "HIGH risk: name 'NodeRegistry' implies authority; new contributors "
            "may reach for it instead of NodeFabricRegistry."
        ),
        pr_guardrail_added="PR-4",
    ),
    # -------------------------------------------------------------------------
    # 3. Dashboard backend legacy UI surface
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="dashboard_backend_legacy_ui",
        module_path="dashboard.backend.main",
        surface_name="Dashboard Backend (legacy headless UI surface)",
        status=RetirementStatus.LEGACY_COMPAT,
        tier=RetirementTier.TIER_2,
        risk=CompatSurfaceRisk.HIGH,
        canonical_replacement=(
            "core.api_routes (CANONICAL_API_ROUTES_AUTHORITY) for route ownership; "
            "windows_client/status_board_v2/ for status display"
        ),
        removal_condition=(
            "Remove when no callers depend on the headless /api/v1/* routes served "
            "by dashboard/backend/main.py and the transition-period status board "
            "consumers have all been migrated to GET /api/v1/projection/runtime."
        ),
        notes=(
            "Dashboard frontend was permanently deleted in PR-1.  The backend is "
            "retained headless-only for transition-period compatibility.  "
            "Carries DASHBOARD_LEGACY_SURFACE_AUTHORITY sentinel.  "
            "Must NOT be treated as a status authority, schema authority, or "
            "architectural source of truth.  "
            "HIGH risk: the /api/v1/* route surface overlaps with canonical routes "
            "served by core/api_routes.py, causing authority ambiguity."
        ),
        pr_guardrail_added="PR-4",
    ),
    # -------------------------------------------------------------------------
    # 4. Shared route cache (node_status_cache / _shared)
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="routes_shared_node_status_cache",
        module_path="core.routes._shared.node_status_cache",
        surface_name="node_status_cache (shared route module cache)",
        status=RetirementStatus.COMPAT_ONLY,
        tier=RetirementTier.TIER_1,
        risk=CompatSurfaceRisk.MEDIUM,
        canonical_replacement="core.nodes.node_fabric_registry.NodeFabricRegistry",
        removal_condition=(
            "Remove when core/routes/compat.py is deleted (its primary consumer) "
            "and no other route module reads node state from _shared.node_status_cache "
            "instead of querying NodeFabricRegistry directly."
        ),
        notes=(
            "node_status_cache in core/routes/_shared.py is a COMPAT_ONLY surface "
            "classified in node_final_boundary_enforcement.py "
            "(NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY).  "
            "The canonical source for node status is NodeFabricRegistry.  "
            "TIER_1: its main consumer (core/routes/compat.py) is itself TIER_2; "
            "once compat.py is removed, this cache has no justification."
        ),
        pr_guardrail_added="PR-13",
    ),
    # -------------------------------------------------------------------------
    # 5. Galaxy Gateway legacy capability registry
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="galaxy_gateway_legacy_capability_registry",
        module_path="galaxy_gateway.legacy.capability_registry",
        surface_name="Legacy Capability Registry (galaxy_gateway/legacy/capability_registry.py)",
        status=RetirementStatus.HARD_DEPRECATED,
        tier=RetirementTier.TIER_1,
        risk=CompatSurfaceRisk.LOW,
        canonical_replacement="core.capability_bus",
        removal_condition=(
            "Remove when no import of galaxy_gateway.legacy.capability_registry "
            "or galaxy_gateway.capability_registry remains outside of deprecation tests."
        ),
        notes=(
            "Emits DeprecationWarning on import.  No production callers remain; "
            "only referenced in deprecation tests.  Canonical replacement "
            "core.capability_bus is fully available.  "
            "LOW risk: emits warning on import; unlikely to be used as canonical."
        ),
        pr_guardrail_added="PR-5",
    ),
    # -------------------------------------------------------------------------
    # 6. Galaxy Gateway legacy task decomposer
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="galaxy_gateway_legacy_task_decomposer",
        module_path="galaxy_gateway.legacy.task_decomposer",
        surface_name="Legacy Task Decomposer (galaxy_gateway/legacy/task_decomposer.py)",
        status=RetirementStatus.HARD_DEPRECATED,
        tier=RetirementTier.TIER_1,
        risk=CompatSurfaceRisk.LOW,
        canonical_replacement="galaxy_gateway.orchestrator",
        removal_condition=(
            "Remove when no import of galaxy_gateway.legacy.task_decomposer "
            "or galaxy_gateway.task_decomposer remains outside of deprecation tests."
        ),
        notes=(
            "Emits DeprecationWarning on import.  No production callers remain; "
            "only referenced in deprecation and integration tests.  "
            "LOW risk: emits warning on import and is inside a /legacy/ directory."
        ),
        pr_guardrail_added="PR-5",
    ),
    # -------------------------------------------------------------------------
    # 7. MultiLLM legacy routing module
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="multi_llm_router_legacy",
        module_path="core.multi_llm_router.MultiLLMRouter",
        surface_name="MultiLLMRouter (legacy multi-provider LLM selector)",
        status=RetirementStatus.LEGACY_COMPAT,
        tier=RetirementTier.TIER_2,
        risk=CompatSurfaceRisk.HIGH,
        canonical_replacement=(
            "core.model_topology.topology_router.TopologyRouter "
            "(TopologyRoutePlan via GET /api/v1/projection/runtime)"
        ),
        removal_condition=(
            "Remove when all model-selection callers have been migrated to "
            "TopologyRouter and no production code references MultiLLMRouter "
            "for new routing decisions."
        ),
        notes=(
            "Registered in core/orchestration_authority/legacy_paths.py as a "
            "LEGACY ROUTING MODULE (PR-routing-authority).  "
            "HIGH risk: the name 'Router' implies canonical routing authority; "
            "new contributors may reach for MultiLLMRouter instead of TopologyRouter."
        ),
        pr_guardrail_added="PR-routing-authority",
    ),
    # -------------------------------------------------------------------------
    # 8. AIP v2 protocol compat layer
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="galaxy_gateway_protocol_compat_aip_v2",
        module_path="galaxy_gateway.protocol.compat",
        surface_name="AIP v2 Protocol Compat Layer (galaxy_gateway/protocol/compat.py)",
        status=RetirementStatus.TRANSITIONAL,
        tier=RetirementTier.TIER_2,
        risk=CompatSurfaceRisk.MEDIUM,
        canonical_replacement="galaxy_gateway.protocol.aip_v3",
        removal_condition=(
            "Remove when all v2 protocol callers (including legacy Android clients) "
            "have been confirmed migrated to AIP v3 and no v2-format messages "
            "are observed in production traffic."
        ),
        notes=(
            "Translation/shim layer for AIP v2 → v3 message format conversion.  "
            "TRANSITIONAL: required while v2 callers remain.  "
            "MEDIUM risk: may be invoked by new protocol-handling code unless "
            "clearly labeled as a translation shim only."
        ),
        pr_guardrail_added="PR-5",
    ),
    # -------------------------------------------------------------------------
    # 9. Fusion unified orchestrator (legacy)
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="fusion_unified_orchestrator_legacy",
        module_path="fusion.unified_orchestrator",
        surface_name="fusion/unified_orchestrator.py (legacy orchestrator)",
        status=RetirementStatus.HARD_DEPRECATED,
        tier=RetirementTier.TIER_1,
        risk=CompatSurfaceRisk.MEDIUM,
        canonical_replacement="galaxy_gateway.orchestrator.GalaxyOrchestrator",
        removal_condition=(
            "Remove when fusion/start_fusion.py and fusion/demo_e2e.py are updated "
            "to import from galaxy_gateway.orchestrator and the only remaining "
            "callers are the deprecation tests."
        ),
        notes=(
            "Carries deprecated docstring marker.  Still imported by "
            "fusion/start_fusion.py and fusion/demo_e2e.py (demo/integration area).  "
            "Registered in core/orchestration_authority/legacy_paths.py.  "
            "MEDIUM risk: 'unified_orchestrator' sounds canonical; the name may "
            "mislead new contributors into treating it as the orchestration authority."
        ),
        pr_guardrail_added="PR-5",
    ),
    # -------------------------------------------------------------------------
    # 10. Launcher config_manager legacy wrapper
    # -------------------------------------------------------------------------
    CompatSurfaceRecord(
        surface_id="launcher_config_manager_legacy",
        module_path="launcher.config_manager",
        surface_name="launcher/config_manager.py (legacy config wrapper)",
        status=RetirementStatus.HARD_DEPRECATED,
        tier=RetirementTier.TIER_1,
        risk=CompatSurfaceRisk.LOW,
        canonical_replacement=(
            "core.unified.config_manager.get_unified_config_manager() for general config; "
            "core.port_config.get_node_port() for port lookups"
        ),
        removal_condition=(
            "Remove when no caller outside of deprecation tests imports "
            "launcher.config_manager and port data consumers have been "
            "confirmed migrated to core.port_config."
        ),
        notes=(
            "Emits DeprecationWarning on import.  No production callers remain.  "
            "Port data may be stale vs config/unified_ports.yaml.  "
            "LOW risk: emits warning on import; clearly marked deprecated."
        ),
        pr_guardrail_added="PR-5",
    ),
]


# ===========================================================================
# Query functions
# ===========================================================================


def get_compat_surface_inventory() -> List[CompatSurfaceRecord]:
    """Return the full list of catalogued compatibility surfaces.

    Returns
    -------
    list[CompatSurfaceRecord]
        All registered compatibility surface records ordered as in the
        inventory definition.
    """
    return list(_COMPAT_SURFACE_INVENTORY)


def get_surfaces_by_tier(tier: RetirementTier) -> List[CompatSurfaceRecord]:
    """Return all surfaces matching the given retirement tier.

    Parameters
    ----------
    tier:
        The :class:`RetirementTier` to filter by.

    Returns
    -------
    list[CompatSurfaceRecord]
        All records whose ``tier`` equals *tier*.
    """
    return [r for r in _COMPAT_SURFACE_INVENTORY if r.tier == tier]


def get_high_risk_surfaces() -> List[CompatSurfaceRecord]:
    """Return all surfaces with ``risk == CompatSurfaceRisk.HIGH``.

    These are the surfaces most likely to be mistaken for canonical
    governance layers and should receive the earliest retirement attention.

    Returns
    -------
    list[CompatSurfaceRecord]
        All high-risk compatibility surface records.
    """
    return [r for r in _COMPAT_SURFACE_INVENTORY if r.risk == CompatSurfaceRisk.HIGH]


def classify_surface_tier(module_path: str) -> Optional[RetirementTier]:
    """Look up the retirement tier for a surface by its module path.

    Parameters
    ----------
    module_path:
        Dotted Python module path of the surface to look up.

    Returns
    -------
    RetirementTier or None
        The tier of the first matching record, or ``None`` if the
        module path is not in the inventory.
    """
    for record in _COMPAT_SURFACE_INVENTORY:
        if record.module_path == module_path or record.module_path.startswith(
            module_path
        ):
            return record.tier
    return None


def build_retirement_roadmap_summary() -> RetirementRoadmapSummary:
    """Build an aggregate summary of the retirement roadmap.

    Returns
    -------
    RetirementRoadmapSummary
        Counts by tier, risk, and status, plus the canonical policy
        sentinel strings.
    """
    inventory = _COMPAT_SURFACE_INVENTORY
    return RetirementRoadmapSummary(
        total_surfaces=len(inventory),
        tier_1_count=sum(1 for r in inventory if r.tier == RetirementTier.TIER_1),
        tier_2_count=sum(1 for r in inventory if r.tier == RetirementTier.TIER_2),
        tier_3_count=sum(1 for r in inventory if r.tier == RetirementTier.TIER_3),
        tier_undecided_count=sum(
            1 for r in inventory if r.tier == RetirementTier.TIER_UNDECIDED
        ),
        high_risk_count=sum(
            1 for r in inventory if r.risk == CompatSurfaceRisk.HIGH
        ),
        medium_risk_count=sum(
            1 for r in inventory if r.risk == CompatSurfaceRisk.MEDIUM
        ),
        low_risk_count=sum(
            1 for r in inventory if r.risk == CompatSurfaceRisk.LOW
        ),
        hard_deprecated_count=sum(
            1 for r in inventory if r.status == RetirementStatus.HARD_DEPRECATED
        ),
        tombstone_count=sum(
            1 for r in inventory if r.status == RetirementStatus.TOMBSTONE
        ),
        legacy_compat_count=sum(
            1 for r in inventory if r.status == RetirementStatus.LEGACY_COMPAT
        ),
        compat_only_count=sum(
            1 for r in inventory if r.status == RetirementStatus.COMPAT_ONLY
        ),
        transitional_count=sum(
            1 for r in inventory if r.status == RetirementStatus.TRANSITIONAL
        ),
        policy_sentinels=[
            HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY,
            COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY,
            RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY,
            COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY,
        ],
    )
