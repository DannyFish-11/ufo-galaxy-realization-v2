#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/device_node_domain_governance.py
=====================================
PR-5: Unified governance model for the device domain and node domain without
forcing false identity equivalence.

This module is the canonical authority for:

- defining device-domain vs node-domain responsibilities,
- documenting the bridge relationships (runtime-host, capability-host,
  dispatch-target) that connect the two domains without collapsing them, and
- classifying the major registry surfaces in the repository by domain,
  authority role, and write-truth capability.

The governance model is documented in
``docs/ugcp/UGCP_DEVICE_NODE_DOMAIN_GOVERNANCE_V1.md``.

Design principles
-----------------
- **Devices are not nodes; nodes are not devices.**  A device may act as a
  runtime host or dispatch target, but it is never registered in
  NodeFabricRegistry.  A node may host capabilities, but it is never
  registered in UnifiedDeviceManager unless it also represents a physical
  device endpoint.
- **Bridge layers connect, they do not collapse.**  Bridge artifacts (e.g.
  capability assimilation records for devices) are not domain memberships.
- **The center governs both domains jointly** through separate authority
  chains, without asserting identity equivalence between devices and nodes.
- **Additive only** — this is a governance/vocabulary module, not a write
  surface.  It compiles domain boundary information; it does not own truth.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY: str = (
    "DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY::"
    "core.device_node_domain_governance is the canonical authority for the "
    "unified device/node domain governance model.  It defines device-domain "
    "vs node-domain responsibilities, the bridge relationships that connect "
    "the domains, and the registry surface authority matrix.  Devices and "
    "nodes are governed jointly by the center runtime without false identity "
    "equivalence."
)

DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL: str = (
    "DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL::"
    "PR5::device-node-domain-governance-v1::"
    "core.device_node_domain_governance defines the unified governance model "
    "for the device domain and node domain (PR-5).  Device-domain and "
    "node-domain responsibilities are explicitly separated, bridge "
    "relationships are documented, and registry surfaces are classified by "
    "domain and authority role."
)

DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY: str = (
    "DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY_V1: the device domain "
    "owns device identity, runtime hosting, connectivity, registration, "
    "SSOT-aligned mutable device state (UnifiedDeviceManager is the sole "
    "canonical write authority), presence lifecycle, and capability evidence "
    "collection.  No node-domain surface may claim device identity or "
    "presence authority."
)

NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY: str = (
    "NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY_V1: the node domain owns "
    "executable unit registration, capability hosting, orchestration "
    "targeting, dispatch semantics, invocation governance, boundary "
    "enforcement, execution lifecycle, and capability sync.  No device-domain "
    "surface may claim dispatch or invocation-governance authority."
)

BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY: str = (
    "BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY_V1: bridge layers "
    "(runtime-host, capability-host, dispatch-target) connect the device "
    "domain and the node domain but must not collapse them into one another. "
    "A device that acts through a bridge remains a device-domain participant; "
    "bridge artifacts are never domain memberships."
)

CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY: str = (
    "CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY_V1: the "
    "center runtime is the sole governance authority for both the device "
    "domain and the node domain.  It governs them jointly through separate "
    "authority chains and explicit bridge surfaces, without asserting "
    "identity equivalence between devices and nodes."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DomainKind(str, Enum):
    """The two governance domains of the center runtime."""

    device = "device"
    node = "node"


class DeviceDomainResponsibility(str, Enum):
    """Responsibilities owned by the device domain."""

    device_identity = "device_identity"
    runtime_hosting = "runtime_hosting"
    connectivity = "connectivity"
    registration = "registration"
    ssot_aligned_state = "ssot_aligned_state"
    presence_lifecycle = "presence_lifecycle"
    capability_evidence = "capability_evidence"


class NodeDomainResponsibility(str, Enum):
    """Responsibilities owned by the node domain."""

    executable_unit_registration = "executable_unit_registration"
    capability_hosting = "capability_hosting"
    orchestration_targeting = "orchestration_targeting"
    dispatch_semantics = "dispatch_semantics"
    invocation_governance = "invocation_governance"
    boundary_enforcement = "boundary_enforcement"
    execution_lifecycle = "execution_lifecycle"
    capability_sync = "capability_sync"


class BridgeRelationshipKind(str, Enum):
    """Kinds of bridges connecting the device domain and the node domain."""

    runtime_host = "runtime_host"
    capability_host = "capability_host"
    dispatch_target = "dispatch_target"


class RegistrySurfaceDomain(str, Enum):
    """Domain attribution for catalogued registry surfaces."""

    device = "device"
    node = "node"
    bridge = "bridge"
    shared_projection = "shared_projection"


class RegistrySurfaceRole(str, Enum):
    """Authority role of a catalogued registry surface."""

    ssot = "ssot"
    canonical_registry = "canonical_registry"
    projection = "projection"
    cache = "cache"
    compat_facade = "compat_facade"
    adapter = "adapter"
    bridge = "bridge"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainDefinition:
    """Definition of a single governance domain."""

    domain: DomainKind
    responsibilities: Tuple[str, ...]
    authority_surfaces: Tuple[str, ...]
    description: str
    lifecycle_kind: str
    authority: str = DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "responsibilities": list(self.responsibilities),
            "authority_surfaces": list(self.authority_surfaces),
            "description": self.description,
            "lifecycle_kind": self.lifecycle_kind,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class BridgeRelationship:
    """A bridge surface connecting the device domain and the node domain."""

    kind: BridgeRelationshipKind
    center_surface: Tuple[str, ...]
    device_domain_role: str
    node_domain_role: str
    description: str
    android_relevance: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "center_surface": list(self.center_surface),
            "device_domain_role": self.device_domain_role,
            "node_domain_role": self.node_domain_role,
            "description": self.description,
            "android_relevance": self.android_relevance,
        }


@dataclass(frozen=True)
class RegistrySurfaceClassification:
    """Classification of a single registry surface in the authority matrix."""

    module_path: str
    surface_name: str
    domain: RegistrySurfaceDomain
    role: RegistrySurfaceRole
    notes: str
    is_authoritative: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "domain": self.domain.value,
            "role": self.role.value,
            "notes": self.notes,
            "is_authoritative": self.is_authoritative,
        }


@dataclass(frozen=True)
class DomainGovernanceSnapshot:
    """Aggregate snapshot of the full domain governance model."""

    device_domain: DomainDefinition
    node_domain: DomainDefinition
    bridge_relationships: Tuple[BridgeRelationship, ...]
    registry_surface_catalogue: Tuple[RegistrySurfaceClassification, ...]
    generated_at: float
    authority: str = DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY
    sentinel: str = DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_domain": self.device_domain.to_dict(),
            "node_domain": self.node_domain.to_dict(),
            "bridge_relationships": [b.to_dict() for b in self.bridge_relationships],
            "registry_surface_catalogue": [s.to_dict() for s in self.registry_surface_catalogue],
            "generated_at": self.generated_at,
            "authority": self.authority,
            "sentinel": self.sentinel,
        }


# ---------------------------------------------------------------------------
# Domain definitions
# ---------------------------------------------------------------------------

_DEVICE_DOMAIN_DEFINITION = DomainDefinition(
    domain=DomainKind.device,
    responsibilities=tuple(r.value for r in DeviceDomainResponsibility),
    authority_surfaces=(
        "core.unified.unified_device_manager.UnifiedDeviceManager",
        "contracts.registered_runtime_device.RegisteredRuntimeDevice",
        "core.device_registry.DeviceRegistry",
        "core.device_readiness",
        "core.device_participation",
    ),
    description=(
        "The device domain governs physical and virtual endpoint identity, "
        "runtime hosting, connectivity, registration, SSOT-aligned mutable "
        "device state, and presence-oriented lifecycle.  UnifiedDeviceManager "
        "(UDM) is the SSOT — the sole canonical write authority for device "
        "registration and mutable device state.  Capability evidence reported "
        "by devices is device-domain input; capability routing is a "
        "node-domain or bridge concern."
    ),
    lifecycle_kind="presence_lifecycle",
)

_NODE_DOMAIN_DEFINITION = DomainDefinition(
    domain=DomainKind.node,
    responsibilities=tuple(r.value for r in NodeDomainResponsibility),
    authority_surfaces=(
        "core.nodes.node_fabric_registry.NodeFabricRegistry",
        "core.node_invocation_governance",
        "core.node_governance_runtime",
        "core.node_boundary_runtime",
        "core.node_lifecycle_governor",
        "core.node_cognition_activation",
        "core.node_final_boundary_enforcement",
        "core.fusion_entry_adapter",
    ),
    description=(
        "The node domain governs executable units, capability hosting, "
        "orchestration targets, dispatch semantics, invocation governance, "
        "boundary enforcement, and execution-oriented lifecycle.  "
        "NodeFabricRegistry is the canonical runtime node registry.  The node "
        "domain does not own device identity, device presence, device "
        "connectivity, or SSOT-aligned device state — those belong to the "
        "device domain."
    ),
    lifecycle_kind="execution_lifecycle",
)


# ---------------------------------------------------------------------------
# Bridge relationships
# ---------------------------------------------------------------------------

_BRIDGE_RELATIONSHIPS: Tuple[BridgeRelationship, ...] = (
    BridgeRelationship(
        kind=BridgeRelationshipKind.runtime_host,
        center_surface=(
            "contracts.registered_runtime_device.RegisteredRuntimeDevice",
            "core.attached_runtime_session_registry",
            "core.runtime.source_dispatch_orchestrator",
        ),
        device_domain_role=(
            "Provides device_id, connectivity facts, and runtime-host status " "(maintained by UnifiedDeviceManager)."
        ),
        node_domain_role=(
            "Dispatch orchestrator uses runtime-host status to select the " "device as a valid execution target."
        ),
        description=(
            "A device that hosts an active runtime may be selected as a "
            "dispatch target.  This is the primary device-to-node bridge: the "
            "selection decision is made by node-domain dispatch logic using "
            "device-domain runtime-host facts."
        ),
        android_relevance=(
            "Android is the primary non-center runtime-host participant.  "
            "When Android's runtime session is active it is a candidate "
            "dispatch target.  Android remains a device-domain participant "
            "and does not participate in center-side node governance."
        ),
    ),
    BridgeRelationship(
        kind=BridgeRelationshipKind.capability_host,
        center_surface=(
            "core.capability_assimilation.CapabilityAssimilationLayer",
            "core.capability_assimilation.assimilate_device",
        ),
        device_domain_role=(
            "Reports capability evidence (camera, screen, microphone, ...) "
            "via device_capability_report messages; evidence is normalized "
            "and stored in the device record by UnifiedDeviceManager."
        ),
        node_domain_role=(
            "Capability assimilation layer registers the device as "
            "NodeParticipantKind.DEVICE in the assimilation plane, making its "
            "capabilities discoverable through node-domain routing."
        ),
        description=(
            "Device capability evidence (device domain) is bridged into "
            "node-domain capability routing through the capability "
            "assimilation layer.  The assimilation record is a bridge "
            "artifact — the device retains its device-domain identity."
        ),
        android_relevance=(
            "Android capability reports are normalized at center ingress and "
            "may be assimilated as device capability evidence.  "
            "Android-reported capabilities do not make Android a node-domain "
            "participant; Android stays in the device domain."
        ),
    ),
    BridgeRelationship(
        kind=BridgeRelationshipKind.dispatch_target,
        center_surface=(
            "core.runtime.source_dispatch_orchestrator",
            "core.android_runtime_dispatch_binding",
            "core.canonical_handoff_path",
        ),
        device_domain_role=(
            "Available as a potential dispatch target if its runtime-host "
            "status is active; receives the delegated task through its "
            "device-domain transport and returns results through "
            "delegated_execution_signal."
        ),
        node_domain_role=(
            "Source dispatch orchestrator resolves dispatch mode and selects "
            "the execution target using node-domain eligibility logic; when "
            "the target is a device, the dispatch path bridges into the "
            "device domain for delivery."
        ),
        description=(
            "If target_device_id is set and the device is a registered "
            "runtime host, the dispatch is device-domain-bound.  Node-domain "
            "dispatch logic selected it based on capability and runtime-host "
            "eligibility."
        ),
        android_relevance=(
            "Android receives delegated tasks through this bridge when "
            "selected as the dispatch target.  Android is a device-domain "
            "participant throughout; it is never a node-domain entity."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Registry surface authority matrix
# ---------------------------------------------------------------------------

_REGISTRY_SURFACE_CATALOGUE: Tuple[RegistrySurfaceClassification, ...] = (
    # -- Device domain -------------------------------------------------------
    RegistrySurfaceClassification(
        module_path="core.unified.unified_device_manager.UnifiedDeviceManager",
        surface_name="UnifiedDeviceManager (UDM)",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.ssot,
        notes=("SSOT — sole canonical write authority for device registration " "and mutable device state."),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="contracts.registered_runtime_device.RegisteredRuntimeDevice",
        surface_name="RegisteredRuntimeDevice contract",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.canonical_registry,
        notes=("Canonical external single-device read contract " "(read-authoritative)."),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.device_registry.DeviceRegistry",
        surface_name="DeviceRegistry",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.canonical_registry,
        notes=("Canonical in-process registry; delegates writes to " "UnifiedDeviceManager."),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.device_readiness",
        surface_name="device readiness",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.projection,
        notes=("Readiness verdict synthesis; compiles readiness evidence and " "does not write canonical state."),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.device_participation",
        surface_name="device participation",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.projection,
        notes=("Participation hints and group membership; projects from " "device-domain state."),
        is_authoritative=False,
    ),
    # -- Node domain ---------------------------------------------------------
    RegistrySurfaceClassification(
        module_path="core.nodes.node_fabric_registry.NodeFabricRegistry",
        surface_name="NodeFabricRegistry",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes="Canonical runtime node registry.",
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_registry.NodeRegistry",
        surface_name="NodeRegistry (compat facade)",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.compat_facade,
        notes=("Legacy compat facade; must not be extended as canonical " "architecture.  Not authoritative."),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_invocation_governance",
        surface_name="node invocation governance",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes="Eligibility enforcement authority at node invocation time.",
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_governance_runtime",
        surface_name="node governance runtime",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes=("Runtime governance eligibility authority (architectural class, " "health, lifecycle-stage)."),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_boundary_runtime",
        surface_name="node boundary runtime",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes="Boundary classification authority for node surfaces.",
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.fusion_entry_adapter",
        surface_name="fusion_entry adapter",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.adapter,
        notes=(
            "Canonical adapter contract for node execution; an execution " "adapter, not a registry/discovery surface."
        ),
        is_authoritative=False,
    ),
    # -- Bridge surfaces -----------------------------------------------------
    RegistrySurfaceClassification(
        module_path="core.capability_assimilation.CapabilityAssimilationLayer",
        surface_name="capability assimilation layer",
        domain=RegistrySurfaceDomain.bridge,
        role=RegistrySurfaceRole.bridge,
        notes=(
            "Bridge surface; does not own device identity or the node "
            "registry.  Assimilation records are bridge artifacts."
        ),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.runtime.source_dispatch_orchestrator",
        surface_name="source dispatch orchestrator",
        domain=RegistrySurfaceDomain.bridge,
        role=RegistrySurfaceRole.bridge,
        notes=("Dispatch bridge surface; resolves dispatch targets but does not " "write domain state."),
        is_authoritative=False,
    ),
    # -- Shared projection ----------------------------------------------------
    RegistrySurfaceClassification(
        module_path="core.routes.projection",
        surface_name="projection routes (/api/v1/projection/*)",
        domain=RegistrySurfaceDomain.shared_projection,
        role=RegistrySurfaceRole.projection,
        notes=("Read-only projection assembling facts from both domains; never " "writes canonical state."),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.capability_registry",
        surface_name="capability registry (OpenClawd bus)",
        domain=RegistrySurfaceDomain.shared_projection,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "Shared entries from both the node domain (via capability sync) "
            "and the device domain (via bridge assimilation)."
        ),
        is_authoritative=True,
    ),
)


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_device_domain_definition() -> DomainDefinition:
    """Return the canonical device-domain definition."""
    return _DEVICE_DOMAIN_DEFINITION


def get_node_domain_definition() -> DomainDefinition:
    """Return the canonical node-domain definition."""
    return _NODE_DOMAIN_DEFINITION


def get_bridge_relationships() -> List[BridgeRelationship]:
    """Return all bridge relationships (new list on each call)."""
    return list(_BRIDGE_RELATIONSHIPS)


def get_bridge_relationship(
    kind: BridgeRelationshipKind,
) -> Optional[BridgeRelationship]:
    """Return the bridge relationship of the given kind, or ``None``."""
    for bridge in _BRIDGE_RELATIONSHIPS:
        if bridge.kind == kind:
            return bridge
    return None


def classify_registry_surface(
    module_path: str,
) -> Optional[RegistrySurfaceClassification]:
    """Look up a registry surface classification by its module path."""
    for surface in _REGISTRY_SURFACE_CATALOGUE:
        if surface.module_path == module_path:
            return surface
    return None


def get_surfaces_by_domain(
    domain: RegistrySurfaceDomain,
) -> List[RegistrySurfaceClassification]:
    """Return all catalogued surfaces attributed to the given domain."""
    return [s for s in _REGISTRY_SURFACE_CATALOGUE if s.domain == domain]


def get_authoritative_surfaces() -> List[RegistrySurfaceClassification]:
    """Return all catalogued surfaces that are authoritative."""
    return [s for s in _REGISTRY_SURFACE_CATALOGUE if s.is_authoritative]


def build_domain_governance_snapshot() -> DomainGovernanceSnapshot:
    """Build an aggregate snapshot of the full domain governance model."""
    return DomainGovernanceSnapshot(
        device_domain=_DEVICE_DOMAIN_DEFINITION,
        node_domain=_NODE_DOMAIN_DEFINITION,
        bridge_relationships=_BRIDGE_RELATIONSHIPS,
        registry_surface_catalogue=_REGISTRY_SURFACE_CATALOGUE,
        generated_at=time.time(),
    )


def get_governance_summary() -> Dict[str, Any]:
    """Return a compact summary of the domain governance model."""
    device = _DEVICE_DOMAIN_DEFINITION
    node = _NODE_DOMAIN_DEFINITION
    return {
        "authority": DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY,
        "sentinel": DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL,
        "device_domain": {
            "domain": device.domain.value,
            "responsibility_count": len(device.responsibilities),
            "authority_surface_count": len(device.authority_surfaces),
            "lifecycle_kind": device.lifecycle_kind,
        },
        "node_domain": {
            "domain": node.domain.value,
            "responsibility_count": len(node.responsibilities),
            "authority_surface_count": len(node.authority_surfaces),
            "lifecycle_kind": node.lifecycle_kind,
        },
        "bridge_relationships": [b.kind.value for b in _BRIDGE_RELATIONSHIPS],
        "total_catalogued_surfaces": len(_REGISTRY_SURFACE_CATALOGUE),
        "authoritative_surfaces": len(get_authoritative_surfaces()),
        "governance_model": (
            "Two distinct domains (device, node) governed jointly by the "
            "center runtime through bridge-preserving relationships "
            "(runtime_host, capability_host, dispatch_target) with no false "
            "identity equivalence between devices and nodes."
        ),
    }


# ---------------------------------------------------------------------------
# Runtime governance singleton (consumed by PR-4 operator action governance)
# ---------------------------------------------------------------------------


@dataclass
class DeviceNodeDomainGovernance:
    """Lightweight runtime facade over the domain governance model.

    Exposes the static governance model plus a small mutable surface used by
    operator-action orchestration (:mod:`core.pr4_operator_action_governance`)
    to record path-selection re-evaluation requests.
    """

    path_reevaluation_requests: List[Dict[str, Any]] = field(default_factory=list)

    def request_path_reevaluation(self, entity_id: str) -> Dict[str, Any]:
        """Record a request to re-evaluate path selection for an entity.

        This module is a governance/vocabulary authority, not a dispatch
        engine — the request is recorded for audit/projection visibility and
        the actual re-evaluation is performed by node-domain dispatch logic.
        """
        record: Dict[str, Any] = {
            "entity_id": entity_id,
            "requested_at": time.time(),
            "authority": DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY,
        }
        self.path_reevaluation_requests.append(record)
        return record

    # Convenience pass-throughs so the singleton mirrors the module API.
    def snapshot(self) -> DomainGovernanceSnapshot:
        return build_domain_governance_snapshot()

    def summary(self) -> Dict[str, Any]:
        return get_governance_summary()


_GOVERNANCE_SINGLETON: Optional[DeviceNodeDomainGovernance] = None
_GOVERNANCE_LOCK = threading.Lock()


def get_device_node_domain_governance() -> DeviceNodeDomainGovernance:
    """Return the process-wide :class:`DeviceNodeDomainGovernance` singleton."""
    global _GOVERNANCE_SINGLETON
    if _GOVERNANCE_SINGLETON is None:
        with _GOVERNANCE_LOCK:
            if _GOVERNANCE_SINGLETON is None:
                _GOVERNANCE_SINGLETON = DeviceNodeDomainGovernance()
    return _GOVERNANCE_SINGLETON


def reset_device_node_domain_governance() -> None:
    """Reset the singleton (test support)."""
    global _GOVERNANCE_SINGLETON
    with _GOVERNANCE_LOCK:
        _GOVERNANCE_SINGLETON = None


__all__ = [
    "DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY",
    "DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL",
    "DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY",
    "NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY",
    "BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY",
    "CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY",
    "DomainKind",
    "DeviceDomainResponsibility",
    "NodeDomainResponsibility",
    "BridgeRelationshipKind",
    "RegistrySurfaceDomain",
    "RegistrySurfaceRole",
    "DomainDefinition",
    "BridgeRelationship",
    "RegistrySurfaceClassification",
    "DomainGovernanceSnapshot",
    "DeviceNodeDomainGovernance",
    "get_device_domain_definition",
    "get_node_domain_definition",
    "get_bridge_relationships",
    "get_bridge_relationship",
    "classify_registry_surface",
    "get_surfaces_by_domain",
    "get_authoritative_surfaces",
    "build_domain_governance_snapshot",
    "get_governance_summary",
    "get_device_node_domain_governance",
    "reset_device_node_domain_governance",
]
