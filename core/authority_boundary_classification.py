#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/authority_boundary_classification.py
==========================================
PR-6 (UGCP convergence plan, realization-v2 side): Explicit authority boundary
classification across SSOT, UDM, UCM, registries, caches, projections, facades,
and adapters.

Background
----------
The repository contains meaningful distinctions between SSOT write paths,
UDM-aligned device authority, registry surfaces, projection layers,
compatibility facades, caches, adapters, and routing helpers.  However,
these distinctions were not consistently explicit enough to prevent future
misuse.

Several non-canonical or compatibility-facing surfaces could still be
mistaken for authority-bearing layers, creating governance ambiguity and
increasing the risk that future work would:

* deepen complexity instead of reducing it
* route new logic through compatibility surfaces
* treat index/cache/facade layers as if they were canonical truth layers
* perpetuate authority illusion across the registration and truth stack

This module resolves that ambiguity by providing:

* An **explicit authority role taxonomy** (``AuthorityRole``) covering
  every kind of surface in the repository.
* A **comprehensive authority matrix** (``_AUTHORITY_MATRIX``) that
  classifies every major surface by its authority role.
* Clear **policy sentinels** affirming the key invariants that must hold.
* **Query helpers** so that operator tools, diagnostic surfaces, and CI
  gates can inspect the authority boundary model at runtime.

Design principles
-----------------
- **Additive only** — this module does not modify any existing module.
  It provides vocabulary and a queryable governance surface that other
  modules can import.
- **Containment, not deletion** — compatibility surfaces are catalogued and
  marked as non-authoritative.  They are not removed.  Future work should
  not extend them as canonical architecture.
- **Machine-checkable** — all sentinels are importable strings that CI
  gates, tests, and diagnostic endpoints can assert.
- **Diagnosable** — every surface entry carries a ``notes`` field
  explaining its role, any migration status, and governance constraints.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY`
:data:`AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL`
:data:`COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY`
:data:`CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY`
:data:`ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY`
:data:`TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY`

Enums
~~~~~
:class:`AuthorityRole`

Data classes
~~~~~~~~~~~~
:class:`AuthoritySurface`
:class:`AuthorityMatrixSummary`

Functions
~~~~~~~~~
:func:`get_authority_matrix`
:func:`classify_surface`
:func:`get_surfaces_by_role`
:func:`get_non_authoritative_surfaces`
:func:`get_transitional_surfaces`
:func:`build_authority_matrix_summary`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

__all__ = [
    # Sentinels
    "AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY",
    "AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL",
    "COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY",
    "CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY",
    "ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY",
    "TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY",
    # Enums
    "AuthorityRole",
    # Data classes
    "AuthoritySurface",
    "AuthorityMatrixSummary",
    # Functions
    "get_authority_matrix",
    "classify_surface",
    "get_surfaces_by_role",
    "get_non_authoritative_surfaces",
    "get_transitional_surfaces",
    "build_authority_matrix_summary",
]


# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY: str = (
    "AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY::"
    "core.authority_boundary_classification is the canonical authority for "
    "classifying all major SSOT, UDM, UCM, registry, cache, projection, "
    "compat-facade, adapter, and routing-helper surfaces by authority role.  "
    "This module defines the PR-6 authority matrix and the governance "
    "invariants that prevent authority illusion across the registration and "
    "truth stack."
)

AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL: str = (
    "AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL::"
    "PR6::authority-boundary-classification-v1::"
    "core.authority_boundary_classification is the PR-6 authority boundary "
    "classification module.  All major surfaces are classified by authority "
    "role.  Compatibility-facing surfaces are explicitly marked as "
    "non-authoritative.  The authority matrix is reviewable and "
    "machine-checkable.  The repository is easier to reason about in terms "
    "of where truth is written, compiled, projected, cached, or adapted."
)

#: Compatibility surfaces (facades, legacy caches, alias-based paths) are
#: explicitly non-authoritative.  Future work must not route new canonical
#: logic through them.
COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY: str = (
    "COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY_V1: "
    "Compatibility surfaces (compat facades, legacy caches, alias-based "
    "protocol surfaces, transitional registry shims) are explicitly "
    "non-authoritative.  They exist for migration continuity only.  Future "
    "work must not route new canonical logic through them, treat them as "
    "SSOT write authorities, or extend them as permanent canonical "
    "architecture."
)

#: Cache and index surfaces compile or derive truth from canonical sources.
#: They must not independently write authoritative state.
CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY: str = (
    "CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY_V1: "
    "Cache and index surfaces (device_pool_manager, device_status_api, "
    "node_status_cache, capability index caches) derive their content from "
    "canonical authority layers.  They must not independently write "
    "authoritative state, act as alternative SSOT paths, or be treated as "
    "primary truth sources by downstream consumers."
)

#: Adapter and routing helper surfaces translate between layers.
#: They are not truth surfaces.
ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY: str = (
    "ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY_V1: "
    "Adapter and routing helper surfaces (fusion_entry_adapter, "
    "legacy_adapters, device_agent_manager_adapter, android_runtime_dispatch "
    "binding) are protocol translation and routing layers only.  They are not "
    "truth surfaces.  Write operations that pass through adapters must "
    "ultimately resolve to the canonical SSOT (UDM for device state, "
    "NodeFabricRegistry for node state)."
)

#: Transitional surfaces must not be extended as canonical architecture.
TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY: str = (
    "TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY_V1: "
    "Surfaces explicitly classified as transitional (legacy node registry "
    "facade, compat HTTP endpoint supplements, legacy device_agent_manager, "
    "registered_devices compat cache) must not be extended with new "
    "canonical logic.  New features must target canonical authority surfaces "
    "only.  Transitional surfaces may be retired once their migration "
    "continuity purpose is fulfilled."
)


# ---------------------------------------------------------------------------
# AuthorityRole enum
# ---------------------------------------------------------------------------


class AuthorityRole(str, Enum):
    """The authority role of a surface in the Galaxy/OpenClawd runtime.

    ssot_write
        Single source of truth write authority.  This surface is the only
        canonical writer for the mutable state it owns.  No other surface
        may act as a parallel SSOT for the same state.  Examples: UDM for
        device state, NodeFabricRegistry for node state.

    canonical_registry
        A canonical runtime registry that holds the authoritative set of
        registered entities.  Reads from this surface are the definitive
        answer for what exists and what its current state is.  Examples:
        NodeFabricRegistry (node registry), CapabilityRegistry (capability
        bus).

    truth_compilation
        A truth compilation or assembly surface.  Reads from multiple
        canonical sources and assembles a coherent truth snapshot or
        projection payload.  Does not independently write canonical state.
        Examples: runtime_truth_compiler, outward_truth_assembly,
        truth_integration_layer.

    projection
        A read-only projection or compiled truth view.  Projects or adapts
        canonical facts into an external representation (API response,
        status board payload, desktop projection).  Does not write truth.
        Examples: projection routes, DesktopStatusProjection,
        RuntimeProjection.

    cache_index
        A read-through cache, scheduling index, or derived index maintained
        over a canonical authority layer.  Must not be treated as truth.
        Content is derived and may lag the authoritative source.  Examples:
        device_pool_manager (scheduling cache), device_status_api (REST
        cache layer), node_status_cache (compat cache for node counts).

    compat_facade
        A compatibility facade or migration shim that provides legacy API
        compatibility over a canonical surface.  Not authoritative.  Must
        not be extended as canonical architecture.  Examples: NodeRegistry
        (compat facade over NodeFabricRegistry), DeviceRegistry compat path,
        registered_devices compat cache.

    adapter_routing
        A routing helper, protocol adapter, or transport bridge.  Translates
        between protocol surfaces or routes requests to canonical targets.
        Not a truth surface.  Examples: fusion_entry_adapter,
        LegacyDeviceAgentManagerAdapter, android_runtime_dispatch_binding.

    transitional
        A surface explicitly marked as transitional.  It exists for migration
        continuity only and must not be extended as permanent canonical
        architecture.  Future work should target canonical replacements.
        Examples: legacy node registry scan, compat HTTP node supplement,
        legacy device_agent_manager direct writes.
    """

    ssot_write = "ssot_write"
    canonical_registry = "canonical_registry"
    truth_compilation = "truth_compilation"
    projection = "projection"
    cache_index = "cache_index"
    compat_facade = "compat_facade"
    adapter_routing = "adapter_routing"
    transitional = "transitional"


# ---------------------------------------------------------------------------
# AuthoritySurface dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuthoritySurface:
    """Classification of a surface in the Galaxy/OpenClawd authority model.

    Attributes
    ----------
    surface_id:
        Short identifier for the surface (used for lookup).
    module_path:
        Canonical Python module path for the surface.
    surface_name:
        Human-readable surface name.
    role:
        The authority role of this surface.
    is_authoritative:
        ``True`` if this surface may write canonical truth (role is
        ``ssot_write`` or ``canonical_registry``).  ``False`` for all
        other roles.
    is_transitional:
        ``True`` if this surface is explicitly marked as transitional and
        must not be extended as canonical architecture.
    notes:
        Governance notes explaining the surface's role, any migration
        status, constraints, or relationship to canonical replacements.
    canonical_replacement:
        If this surface is a compat facade, cache, or transitional surface,
        the module path of the canonical surface that should be preferred
        instead.  ``None`` for authoritative surfaces.
    """

    surface_id: str
    module_path: str
    surface_name: str
    role: AuthorityRole
    is_authoritative: bool
    notes: str
    is_transitional: bool = False
    canonical_replacement: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "role": self.role.value,
            "is_authoritative": self.is_authoritative,
            "is_transitional": self.is_transitional,
            "notes": self.notes,
            "canonical_replacement": self.canonical_replacement,
        }


# ---------------------------------------------------------------------------
# AuthorityMatrixSummary dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuthorityMatrixSummary:
    """Compact summary of the authority matrix at a point in time.

    Attributes
    ----------
    total_surfaces:
        Total number of classified surfaces in the authority matrix.
    authoritative_count:
        Number of surfaces with ``is_authoritative == True``.
    non_authoritative_count:
        Number of surfaces with ``is_authoritative == False``.
    transitional_count:
        Number of surfaces explicitly marked as transitional.
    by_role:
        Mapping of role value → count of surfaces with that role.
    compat_facade_surfaces:
        Surface IDs of all compat facade surfaces.
    transitional_surface_ids:
        Surface IDs of all transitional surfaces.
    generated_at:
        Unix timestamp when this summary was generated.
    """

    total_surfaces: int
    authoritative_count: int
    non_authoritative_count: int
    transitional_count: int
    by_role: Dict[str, int]
    compat_facade_surfaces: List[str]
    transitional_surface_ids: List[str]
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "total_surfaces": self.total_surfaces,
            "authoritative_count": self.authoritative_count,
            "non_authoritative_count": self.non_authoritative_count,
            "transitional_count": self.transitional_count,
            "by_role": self.by_role,
            "compat_facade_surfaces": self.compat_facade_surfaces,
            "transitional_surface_ids": self.transitional_surface_ids,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Authority matrix catalog
# ---------------------------------------------------------------------------
#
# Each entry classifies one major surface in the Galaxy/OpenClawd runtime.
# The matrix is organized into sections:
#
#   1. SSOT write surfaces
#   2. Canonical registries
#   3. Truth compilation surfaces
#   4. Projection surfaces
#   5. Cache / index surfaces
#   6. Compatibility facades
#   7. Adapter / routing helper surfaces
#   8. Transitional surfaces
# ---------------------------------------------------------------------------

_AUTHORITY_MATRIX: List[AuthoritySurface] = [
    # =========================================================================
    # 1. SSOT write surfaces
    #    These are the only surfaces allowed to write authoritative state.
    # =========================================================================

    AuthoritySurface(
        surface_id="udm",
        module_path="core.unified.device_manager.UnifiedDeviceManager",
        surface_name="UnifiedDeviceManager (UDM)",
        role=AuthorityRole.ssot_write,
        is_authoritative=True,
        notes=(
            "The only canonical SSOT write authority for device state in the "
            "Galaxy runtime.  All device registration, state mutation, and "
            "unregistration must go through UDM.  No other module may act as a "
            "parallel mutable device-state authority.  UCM (UnifiedConnectionManager) "
            "is a separate connection-presence authority; it does not replace UDM."
        ),
    ),
    AuthoritySurface(
        surface_id="ucm",
        module_path="core.unified.connection_manager.UnifiedConnectionManager",
        surface_name="UnifiedConnectionManager (UCM)",
        role=AuthorityRole.ssot_write,
        is_authoritative=True,
        notes=(
            "The canonical write authority for device connection and presence "
            "state (connected, disconnected, active WebSocket sessions).  UCM "
            "governs connection-plane truth; UDM governs device-registration "
            "truth.  Both are SSOT for their respective planes and must not be "
            "conflated.  Downstream modules must not independently maintain "
            "competing connection-state stores."
        ),
    ),

    # =========================================================================
    # 2. Canonical registries
    #    Hold the authoritative set of registered entities and current state.
    # =========================================================================

    AuthoritySurface(
        surface_id="node_fabric_registry",
        module_path="core.nodes.node_fabric_registry.NodeFabricRegistry",
        surface_name="NodeFabricRegistry",
        role=AuthorityRole.canonical_registry,
        is_authoritative=True,
        notes=(
            "The canonical runtime node registry.  Maintains the authoritative "
            "set of registered nodes, their health, capabilities, roles, and "
            "architectural classes.  All node-surface consumers must read from "
            "NodeFabricRegistry.  The legacy NodeRegistry (core.node_registry) "
            "is a compat facade over this surface and must not be used for new "
            "canonical logic."
        ),
    ),
    AuthoritySurface(
        surface_id="registered_runtime_device_contract",
        module_path="contracts.registered_runtime_device.RegisteredRuntimeDevice",
        surface_name="RegisteredRuntimeDevice contract",
        role=AuthorityRole.canonical_registry,
        is_authoritative=True,
        notes=(
            "The sole canonical external single-device read contract.  All "
            "device-surface views must normalize into this contract before "
            "being consumed by runtime, projection, governance, or API layers.  "
            "This is a read contract, not a write surface — writes go through "
            "UDM."
        ),
    ),
    AuthoritySurface(
        surface_id="capability_registry",
        module_path="core.capability_registry.CapabilityRegistry",
        surface_name="CapabilityRegistry (capability bus)",
        role=AuthorityRole.canonical_registry,
        is_authoritative=True,
        notes=(
            "The OpenClawd capability bus.  Node-domain capability sync injects "
            "capabilities from governance-eligible nodes; bridge surfaces inject "
            "device capability entries (via capability assimilation).  Entries "
            "originate from both node-domain nodes and device-domain devices.  "
            "This is a canonical shared registry whose entries are governed by "
            "node_governance_runtime and capability_assimilation constraints."
        ),
    ),
    AuthoritySurface(
        surface_id="node_invocation_governance",
        module_path="core.node_invocation_governance",
        surface_name="node invocation governance",
        role=AuthorityRole.canonical_registry,
        is_authoritative=True,
        notes=(
            "Canonical eligibility enforcement at node invocation time.  "
            "Ineligible nodes (archived/deprecated/unhealthy) are denied with "
            "structured eligibility_denial payload.  COMPAT_INTERNAL override "
            "bypasses for internal paths only.  Not a write authority — it "
            "enforces constraints at invocation time."
        ),
    ),
    AuthoritySurface(
        surface_id="node_governance_runtime",
        module_path="core.node_governance_runtime",
        surface_name="node governance runtime",
        role=AuthorityRole.canonical_registry,
        is_authoritative=True,
        notes=(
            "Canonical runtime governance eligibility authority for node "
            "exposure and capability synchronization.  Enforces architectural "
            "class, health, and lifecycle-stage constraints as real runtime "
            "filters.  Results are diagnostic and machine-checkable.  "
            "sync_capabilities_to_registry() in NodeFabricRegistry uses this "
            "surface."
        ),
    ),
    AuthoritySurface(
        surface_id="node_boundary_runtime",
        module_path="core.node_boundary_runtime",
        surface_name="node boundary runtime",
        role=AuthorityRole.canonical_registry,
        is_authoritative=True,
        notes=(
            "Canonical authority for Galaxy node boundary definitions and "
            "invocation pathway classification.  Classifies surfaces and "
            "pathways as canonical, compat-only, internal-only, or deprecated.  "
            "This is the definitive record of which node surfaces are part of "
            "the governed canonical architecture."
        ),
    ),

    # =========================================================================
    # 3. Truth compilation surfaces
    #    Compile or assemble truth from canonical sources into coherent snapshots.
    # =========================================================================

    AuthoritySurface(
        surface_id="truth_integration_layer",
        module_path="core.truth_integration_layer",
        surface_name="truth integration layer",
        role=AuthorityRole.truth_compilation,
        is_authoritative=False,
        notes=(
            "Canonical multi-device truth compilation surface.  "
            "resolve_all_device_truth() compiles device truth from UDM and UCM "
            "canonical sources and returns a coherent multi-device snapshot.  "
            "This surface reads from authoritative sources; it does not "
            "independently write canonical state.  Downstream consumers must "
            "use this surface for multi-device queries rather than fanning out "
            "to raw UDM/UCM internals."
        ),
    ),
    AuthoritySurface(
        surface_id="truth_source_lock",
        module_path="core.truth_source_lock",
        surface_name="truth source lock",
        role=AuthorityRole.truth_compilation,
        is_authoritative=False,
        notes=(
            "Governance record for the canonical device truth source boundaries "
            "(PR-B truth source lock).  Locks which authority writes device "
            "truth (UDM), which model is the canonical single-device read "
            "contract (RegisteredRuntimeDevice), and which projection is the "
            "canonical multi-device read (resolve_all_device_truth).  This is "
            "a governance/vocabulary module, not a write surface."
        ),
    ),
    AuthoritySurface(
        surface_id="truth_projection_boundary",
        module_path="core.truth_projection_boundary",
        surface_name="truth vs projection boundary",
        role=AuthorityRole.truth_compilation,
        is_authoritative=False,
        notes=(
            "Canonical authority for classifying cross-plane surfaces as "
            "truth-owner, projection/read-model, synchronization-mapping, or "
            "compatibility-only (PR-7 boundary).  This is a governance/vocab "
            "module.  Classifies surfaces across the participant, device, "
            "session, capability, and execution planes."
        ),
    ),
    AuthoritySurface(
        surface_id="device_node_domain_governance",
        module_path="core.device_node_domain_governance",
        surface_name="device/node domain governance",
        role=AuthorityRole.truth_compilation,
        is_authoritative=False,
        notes=(
            "Canonical authority for the unified governance model defining "
            "device-domain vs node-domain responsibilities, bridge "
            "relationships, and registry surface authority matrix (PR-5 "
            "domain governance).  This is a governance/vocab module that "
            "compiles domain boundary information; it is not itself a "
            "write authority."
        ),
    ),

    # =========================================================================
    # 4. Projection surfaces
    #    Read-only views that adapt canonical truth for external consumers.
    # =========================================================================

    AuthoritySurface(
        surface_id="projection_routes",
        module_path="core.routes.projection",
        surface_name="projection routes (/api/v1/projection/*)",
        role=AuthorityRole.projection,
        is_authoritative=False,
        notes=(
            "Read-only projection routes for the status board and desktop "
            "projection surfaces.  Assembles runtime facts from canonical "
            "truth layers for API consumption.  Does not write truth.  The "
            "/api/v1/projection/runtime-truth endpoint is the single canonical "
            "read-only projection surface for runtime-facing output state; all "
            "other overlapping status endpoints are compatibility/management "
            "surfaces."
        ),
    ),
    AuthoritySurface(
        surface_id="desktop_status_projection",
        module_path="contracts.desktop_status_projection",
        surface_name="DesktopStatusProjection",
        role=AuthorityRole.projection,
        is_authoritative=False,
        notes=(
            "Canonical external contract for the desktop status projection.  "
            "Assembles a coherent view of runtime state for desktop "
            "consumers.  Adapts canonical truth for display; does not write "
            "truth.  ModelRoutingProjection within this contract should "
            "prefer the canonical TopologyRouter path; the legacy_ucp_keys "
            "path is explicitly marked as degraded/compatibility mode."
        ),
    ),
    AuthoritySurface(
        surface_id="runtime_projection",
        module_path="core.projection",
        surface_name="RuntimeProjection",
        role=AuthorityRole.projection,
        is_authoritative=False,
        notes=(
            "The canonical lightweight runtime projection model.  Assembles "
            "a stable snapshot of runtime state from ContinuumState and "
            "TopologyRoutePlan.  Read-only.  Status Board V2 should prefer "
            "richer board-facing truth surfaces for authoritative reads and "
            "treat this as a compatibility fallback."
        ),
    ),
    AuthoritySurface(
        surface_id="device_readiness",
        module_path="core.device_readiness",
        surface_name="device readiness",
        role=AuthorityRole.projection,
        is_authoritative=False,
        notes=(
            "Readiness verdict synthesis for devices.  Compiles readiness "
            "evidence into a verdict; does not write canonical device state.  "
            "Readiness verdicts are advisory projections consumed by "
            "scheduling, governance, and status surfaces."
        ),
    ),
    AuthoritySurface(
        surface_id="device_participation",
        module_path="core.device_participation",
        surface_name="device participation",
        role=AuthorityRole.projection,
        is_authoritative=False,
        notes=(
            "Device participation hints and multi-device group membership "
            "projection.  Projects from device-domain state; does not write "
            "canonical state.  Participation hints are enrichment-only and "
            "must not set registered, online, or routable independently of "
            "Layer-1 canonical readiness."
        ),
    ),

    # =========================================================================
    # 5. Cache / index surfaces
    #    Derived from canonical sources; must not be treated as truth.
    # =========================================================================

    AuthoritySurface(
        surface_id="device_pool_manager",
        module_path="core.device_pool_manager",
        surface_name="device pool manager (scheduling cache)",
        role=AuthorityRole.cache_index,
        is_authoritative=False,
        notes=(
            "Scheduling and availability index derived from UDM and UCM "
            "canonical sources.  Maintains per-device scheduling metadata, "
            "load estimates, and pool groupings for the dispatch layer.  Must "
            "not be treated as a canonical device truth source.  Writes to "
            "this surface do not propagate back to UDM; it is a derived cache."
        ),
        canonical_replacement="core.unified.device_manager.UnifiedDeviceManager",
    ),
    AuthoritySurface(
        surface_id="device_status_api",
        module_path="core.device_status_api",
        surface_name="device status API (REST cache layer)",
        role=AuthorityRole.cache_index,
        is_authoritative=False,
        notes=(
            "REST-facing status cache that assembles device status payloads "
            "from UDM, UCM, and device readiness canonical sources.  This "
            "surface is read-only from the client perspective and must not be "
            "written to as a primary store.  Device status queries should "
            "prefer the canonical projection endpoint over this cache surface "
            "for authoritative reads."
        ),
        canonical_replacement="core.unified.device_manager.UnifiedDeviceManager",
    ),
    AuthoritySurface(
        surface_id="registered_devices_compat_cache",
        module_path="core.routes._shared.registered_devices",
        surface_name="registered_devices compat cache",
        role=AuthorityRole.cache_index,
        is_authoritative=False,
        is_transitional=True,
        notes=(
            "Legacy compat cache for registered device records, maintained in "
            "`core/routes/_shared.py`.  This is a READ-ONLY compat cache; it "
            "is NOT an authoritative truth source.  Governed by "
            "COMPAT_CACHE_READ_ONLY in truth_source_lock.  Devices loaded from "
            "this cache are in OFFLINE state until they re-register through the "
            "canonical UDM write path.  Must not be written to as a primary "
            "store.  Future work should migrate consumers to the canonical "
            "projection endpoint."
        ),
        canonical_replacement="core.unified.device_manager.UnifiedDeviceManager",
    ),
    AuthoritySurface(
        surface_id="node_status_cache",
        module_path="core.nodes.node_status_cache",
        surface_name="node_status_cache (compat cache)",
        role=AuthorityRole.cache_index,
        is_authoritative=False,
        is_transitional=True,
        notes=(
            "Legacy compat cache that supplements node count and status "
            "information.  Classified as COMPAT_ONLY by "
            "node_final_boundary_enforcement.  Must not be used as the "
            "canonical source for node counts or health status.  "
            "get_node_count_from_canonical_source() in system.py now prefers "
            "NodeFabricRegistry and labels this surface as a compat supplement."
        ),
        canonical_replacement="core.nodes.node_fabric_registry.NodeFabricRegistry",
    ),

    # =========================================================================
    # 6. Compatibility facades
    #    Legacy shims providing backward-compatible APIs over canonical surfaces.
    # =========================================================================

    AuthoritySurface(
        surface_id="node_registry_compat_facade",
        module_path="core.node_registry.NodeRegistry",
        surface_name="NodeRegistry (compat facade)",
        role=AuthorityRole.compat_facade,
        is_authoritative=False,
        is_transitional=True,
        notes=(
            "Legacy compat facade over NodeFabricRegistry "
            "(LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL).  Provides "
            "backward-compatible node listing APIs.  Not authoritative.  "
            "Must not be extended as canonical architecture.  New consumers "
            "must read from NodeFabricRegistry directly.  This surface "
            "exists for migration continuity only."
        ),
        canonical_replacement="core.nodes.node_fabric_registry.NodeFabricRegistry",
    ),
    AuthoritySurface(
        surface_id="device_registry_compat",
        module_path="core.device_registry.DeviceRegistry",
        surface_name="DeviceRegistry (compat / indexing layer)",
        role=AuthorityRole.compat_facade,
        is_authoritative=False,
        notes=(
            "Compatibility and indexing layer over UDM.  Maintains an "
            "in-process device dict, group/tag/capability indexes, and an "
            "on-disk snapshot as a compat convenience layer.  All "
            "registration and mutable-state writes are forwarded to UDM "
            "first.  The local state is treated as a snapshot/projection "
            "cache.  Must not be treated as a parallel canonical truth source."
        ),
        canonical_replacement="core.unified.device_manager.UnifiedDeviceManager",
    ),
    AuthoritySurface(
        surface_id="device_agent_manager_compat",
        module_path="core.device_agent_manager.DeviceAgentManager",
        surface_name="DeviceAgentManager (compat write path)",
        role=AuthorityRole.compat_facade,
        is_authoritative=False,
        is_transitional=True,
        notes=(
            "Compatibility write path that must delegate device-state writes "
            "to UnifiedDeviceManager (SSOT).  Direct writes to internal "
            "DeviceAgentManager state without going through UDM constitute a "
            "compat write path violation.  LegacyDeviceAgentManagerAdapter "
            "(core.legacy_adapters) provides the approved migration adapter. "
            "New code must not use DeviceAgentManager as a primary registration "
            "authority."
        ),
        canonical_replacement="core.unified.device_manager.UnifiedDeviceManager",
    ),

    # =========================================================================
    # 7. Adapter / routing helper surfaces
    #    Protocol translation, transport routing, and migration adapters.
    # =========================================================================

    AuthoritySurface(
        surface_id="fusion_entry_adapter",
        module_path="core.fusion_entry_adapter",
        surface_name="fusion_entry adapter contract",
        role=AuthorityRole.adapter_routing,
        is_authoritative=False,
        notes=(
            "Canonical adapter contract authority for fusion_entry.py (PR-5 "
            "fusion entry adapter).  fusion_entry.py is a LOCAL EXECUTION "
            "ADAPTER ONLY — not a registry or discovery surface.  Defines "
            "FusionEntryAdapterContract (FusionNode class, async execute, "
            "get_node_instance).  Direct _load_node/_execute_node patterns "
            "have been redirected through invoke_node() (canonical invocation "
            "path).  Not a truth surface."
        ),
    ),
    AuthoritySurface(
        surface_id="legacy_device_agent_manager_adapter",
        module_path="core.legacy_adapters.device_agent_manager_adapter.LegacyDeviceAgentManagerAdapter",
        surface_name="LegacyDeviceAgentManagerAdapter",
        role=AuthorityRole.adapter_routing,
        is_authoritative=False,
        notes=(
            "Migration adapter that preserves legacy DeviceAgentManager "
            "API signatures while delegating device-state writes to "
            "UnifiedDeviceManager (SSOT).  This is the approved pattern for "
            "migrating legacy callers.  Not a truth surface.  Write operations "
            "that pass through this adapter resolve to UDM as the canonical "
            "write authority."
        ),
    ),
    AuthoritySurface(
        surface_id="android_runtime_dispatch_binding",
        module_path="core.android_runtime_dispatch_binding",
        surface_name="android runtime dispatch binding",
        role=AuthorityRole.adapter_routing,
        is_authoritative=False,
        notes=(
            "Transport adapter that bridges node-domain dispatch semantics to "
            "Android device-domain delivery.  Translates dispatched tasks into "
            "Android-compatible delegated execution payloads and routes them "
            "through the device-domain WebSocket transport.  Not a truth "
            "surface.  Android remains a device-domain participant throughout "
            "the dispatch cycle."
        ),
    ),
    AuthoritySurface(
        surface_id="capability_assimilation",
        module_path="core.capability_assimilation.CapabilityAssimilationLayer",
        surface_name="capability assimilation layer",
        role=AuthorityRole.adapter_routing,
        is_authoritative=False,
        notes=(
            "Bridge surface that translates device capability evidence "
            "(device domain) into node-domain capability routing entries.  "
            "Devices assimilated via assimilate_device() receive "
            "NodeParticipantKind.DEVICE in the capability bus.  This is a "
            "bridge/adapter surface: it does not own device identity and is "
            "not a node registry.  Truth about device capabilities originates "
            "in UDM; truth about registered capability bus entries lives in "
            "CapabilityRegistry."
        ),
    ),
    AuthoritySurface(
        surface_id="source_dispatch_orchestrator",
        module_path="core.runtime.source_dispatch_orchestrator",
        surface_name="source dispatch orchestrator",
        role=AuthorityRole.adapter_routing,
        is_authoritative=False,
        notes=(
            "Bridges node-domain dispatch semantics with device-domain runtime "
            "hosting for the dispatch-target bridge.  Resolves dispatch mode "
            "(local, remote, fallback-local, staged-mesh, delegated) and "
            "selects the execution target using node-domain eligibility logic.  "
            "When the target is a device, delivery goes through the device "
            "domain.  Not a truth surface — dispatch decisions are routing "
            "outcomes derived from canonical eligibility state."
        ),
    ),

    # =========================================================================
    # 8. Transitional surfaces
    #    Must not be extended as canonical architecture.
    # =========================================================================

    AuthoritySurface(
        surface_id="legacy_node_registry_json_scan",
        module_path="core.openclawd._collect_tools.layer3_node_registry_json",
        surface_name="legacy node_registry.json + fusion_entry.py scan (Layer 3)",
        role=AuthorityRole.transitional,
        is_authoritative=False,
        is_transitional=True,
        notes=(
            "Legacy Layer 3 in OpenClawd._collect_tools() that scans "
            "node_registry.json and fusion_entry.py directly for node "
            "discovery.  Disabled by default "
            "(OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED=false) as of PR-10 "
            "(canonical node tool exposure).  Re-enabled only by explicit env "
            "flag for migration continuity.  Must not be extended.  New node "
            "discovery must go through NodeFabricRegistry."
        ),
        canonical_replacement="core.nodes.node_fabric_registry.NodeFabricRegistry",
    ),
    AuthoritySurface(
        surface_id="compat_http_node_supplement",
        module_path="core.routes.system.nodes_status_compat_supplement",
        surface_name="nodes/status compat supplement (GET /api/v1/nodes/status)",
        role=AuthorityRole.transitional,
        is_authoritative=False,
        is_transitional=True,
        notes=(
            "Compat supplement endpoint that returns node status from the "
            "NodeRegistry compat facade as a supplement to the canonical "
            "NodeFabricRegistry response.  Classified as COMPAT_ONLY by "
            "node_remaining_boundary_enforcement.  Response carries "
            "compat_supplement_note field.  Must not be extended as canonical "
            "architecture.  Future node status queries must target "
            "NodeFabricRegistry."
        ),
        canonical_replacement="core.nodes.node_fabric_registry.NodeFabricRegistry",
    ),
]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def get_authority_matrix() -> List[AuthoritySurface]:
    """Return the full authority matrix as an immutable list.

    Returns
    -------
    List[AuthoritySurface]
        The complete authority matrix catalog.  Each entry classifies one
        major surface in the Galaxy/OpenClawd runtime by its authority role.
    """
    return list(_AUTHORITY_MATRIX)


def classify_surface(surface_id: str) -> Optional[AuthoritySurface]:
    """Look up a surface in the authority matrix by its ``surface_id``.

    Parameters
    ----------
    surface_id:
        The ``surface_id`` key of the surface to look up.

    Returns
    -------
    AuthoritySurface or None
        The classification entry if found; ``None`` if the surface is not
        in the authority matrix.
    """
    for entry in _AUTHORITY_MATRIX:
        if entry.surface_id == surface_id:
            return entry
    return None


def get_surfaces_by_role(role: AuthorityRole) -> List[AuthoritySurface]:
    """Return all authority matrix entries with the given ``role``.

    Parameters
    ----------
    role:
        The :class:`AuthorityRole` to filter by.

    Returns
    -------
    List[AuthoritySurface]
        All surfaces in the authority matrix with the specified role.
    """
    return [entry for entry in _AUTHORITY_MATRIX if entry.role == role]


def get_non_authoritative_surfaces() -> List[AuthoritySurface]:
    """Return all surfaces that are **not** canonical write authorities.

    Returns all entries where ``is_authoritative == False``.  These
    surfaces include projections, caches, compat facades, adapters,
    transitional surfaces, and truth compilation helpers.

    Returns
    -------
    List[AuthoritySurface]
        Surfaces that must not be treated as canonical write authorities.
    """
    return [entry for entry in _AUTHORITY_MATRIX if not entry.is_authoritative]


def get_transitional_surfaces() -> List[AuthoritySurface]:
    """Return all surfaces explicitly marked as transitional.

    Returns all entries where ``is_transitional == True``.  These are
    surfaces that must not be extended as canonical architecture and should
    be migrated to their canonical replacements.

    Returns
    -------
    List[AuthoritySurface]
        Surfaces marked as transitional in the authority matrix.
    """
    return [entry for entry in _AUTHORITY_MATRIX if entry.is_transitional]


def build_authority_matrix_summary() -> AuthorityMatrixSummary:
    """Build a compact summary of the authority matrix.

    Returns
    -------
    AuthorityMatrixSummary
        A compact summary including counts by role, compat facade surface
        IDs, and transitional surface IDs.
    """
    matrix = _AUTHORITY_MATRIX
    total = len(matrix)
    authoritative = sum(1 for e in matrix if e.is_authoritative)
    non_authoritative = total - authoritative
    transitional = sum(1 for e in matrix if e.is_transitional)

    by_role: Dict[str, int] = {}
    for role in AuthorityRole:
        count = sum(1 for e in matrix if e.role == role)
        if count:
            by_role[role.value] = count

    compat_facade_ids = [
        e.surface_id for e in matrix if e.role == AuthorityRole.compat_facade
    ]
    transitional_ids = [e.surface_id for e in matrix if e.is_transitional]

    return AuthorityMatrixSummary(
        total_surfaces=total,
        authoritative_count=authoritative,
        non_authoritative_count=non_authoritative,
        transitional_count=transitional,
        by_role=by_role,
        compat_facade_surfaces=compat_facade_ids,
        transitional_surface_ids=transitional_ids,
    )
