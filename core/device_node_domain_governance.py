"""core/device_node_domain_governance.py
==========================================
PR-5: Unified governance model for the device domain and node domain.

This module is the **canonical authority** for defining the governance
boundaries between the *device domain* and the *node domain* in the Galaxy /
OpenClawd center runtime.  It makes the distinction explicit without forcing
false identity equivalence, and documents the bridge relationships that connect
the two domains.

Background
----------
The repository contains a device-domain governance model and a node-domain
governance model that are clearly related but not identical.  Prior to PR-5:

* The device domain was tied to device identity, runtime hosting, connectivity,
  registration, SSOT-aligned state, and presence-oriented lifecycle concerns.
* The node domain was tied to executable units, capability hosting, orchestration
  targets, dispatch semantics, and execution-oriented lifecycle concerns.
* Bridge layers such as capability assimilation and related registry/projection
  surfaces connect the two domains.

This architecture is intentional and workable, but the governance model was not
fully explicit, creating ambiguity around:

* Whether devices should be treated as nodes.
* Whether nodes subsume device identity.
* How runtime hosting should be reasoned about.
* How capability-hosting and dispatch targeting relate to device registration.
* How the central orchestrator governs both domains together without collapsing
  them into one model.

This module resolves that ambiguity by providing:

* The **canonical responsibilities** of the device domain.
* The **canonical responsibilities** of the node domain.
* How **runtime-host** relationships bridge the two.
* How **capability-host** relationships bridge the two.
* How **dispatch targets** should be interpreted across domains.
* Which **registries, managers, and truth surfaces** belong to which domain.
* How both domains are **jointly governed by the center runtime**.

Design principles
-----------------
- **Bridge-preserving** — the current bridge-based architecture is preserved.
  This module makes the bridges explicit and governable; it does not merge the
  two domains.
- **No false identity equivalence** — a device is not a node, and a node is not
  a device.  Both are first-class domain participants in the center runtime, but
  their responsibilities, lifecycles, and governance surfaces are distinct.
- **Additive only** — this module does not modify any existing module.  It
  provides a vocabulary and a queryable governance surface that other modules
  can import.
- **Diagnosable** — all domain and bridge definitions carry descriptions and
  authority annotations so that future operators and reviewers can inspect the
  governance model at runtime.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY`
:data:`DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL`
:data:`DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY`
:data:`NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY`
:data:`BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY`
:data:`CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY`

Enums
~~~~~
:class:`DomainKind`
:class:`DeviceDomainResponsibility`
:class:`NodeDomainResponsibility`
:class:`BridgeRelationshipKind`
:class:`RegistrySurfaceDomain`
:class:`RegistrySurfaceRole`

Data classes
~~~~~~~~~~~~
:class:`DomainDefinition`
:class:`BridgeRelationship`
:class:`RegistrySurfaceClassification`
:class:`DomainGovernanceSnapshot`

Functions
~~~~~~~~~
:func:`get_device_domain_definition`
:func:`get_node_domain_definition`
:func:`get_bridge_relationships`
:func:`classify_registry_surface`
:func:`build_domain_governance_snapshot`
:func:`get_governance_summary`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

__all__ = [
    # Sentinels
    "DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY",
    "DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL",
    "DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY",
    "NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY",
    "BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY",
    "CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY",
    # Enums
    "DomainKind",
    "DeviceDomainResponsibility",
    "NodeDomainResponsibility",
    "BridgeRelationshipKind",
    "RegistrySurfaceDomain",
    "RegistrySurfaceRole",
    # Data classes
    "DomainDefinition",
    "BridgeRelationship",
    "RegistrySurfaceClassification",
    "DomainGovernanceSnapshot",
    # Functions
    "get_device_domain_definition",
    "get_node_domain_definition",
    "get_bridge_relationships",
    "classify_registry_surface",
    "build_domain_governance_snapshot",
    "get_governance_summary",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY: str = (
    "DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY::"
    "core.device_node_domain_governance is the canonical authority for the "
    "unified governance model defining device-domain vs node-domain "
    "responsibilities, bridge relationships, and registry surface "
    "classifications (PR-5, device/node domain governance)."
)

DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL: str = (
    "DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL::package=PR5::"
    "profile=device-node-domain-governance-v1::"
    "module=core.device_node_domain_governance"
)

DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE_POLICY: str = (
    "POLICY::DEVICE_DOMAIN_OWNS_IDENTITY_AND_PRESENCE: the device domain is "
    "the authoritative owner of device identity, physical/virtual endpoint "
    "registration, presence-oriented lifecycle (online/offline/busy), runtime "
    "hosting facts, connectivity metadata, and SSOT-aligned mutable device "
    "state.  No other domain may act as a parallel mutable device-identity "
    "authority."
)

NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH_POLICY: str = (
    "POLICY::NODE_DOMAIN_OWNS_EXECUTION_AND_DISPATCH: the node domain is the "
    "authoritative owner of executable unit registration, capability hosting, "
    "orchestration targeting, dispatch semantics, invocation governance, "
    "boundary enforcement, and execution-oriented lifecycle.  The node domain "
    "does not own device identity or presence-oriented lifecycle."
)

BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS_POLICY: str = (
    "POLICY::BRIDGE_LAYERS_MUST_NOT_COLLAPSE_DOMAINS: bridge layers "
    "(capability assimilation, runtime-host selection, dispatch targeting) "
    "connect the device domain and node domain without collapsing them into "
    "one model.  A device that acts as a runtime host or dispatch target "
    "remains a device-domain participant; it is not reclassified as a node. "
    "Bridge surfaces must be explicitly identified as bridges, not as "
    "canonical domain members of either domain."
)

CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE_POLICY: str = (
    "POLICY::CENTER_GOVERNS_BOTH_DOMAINS_WITHOUT_IDENTITY_EQUIVALENCE: the "
    "center runtime governs both the device domain and the node domain through "
    "separate authority chains (UnifiedDeviceManager for device domain, "
    "NodeFabricRegistry for node domain) without asserting that devices and "
    "nodes are identity-equivalent.  Joint governance is expressed through "
    "bridge relationships, not through domain merger."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DomainKind(str, Enum):
    """The two governed runtime domains.

    device
        The device domain: identity, presence, registration, runtime hosting,
        connectivity, and SSOT-aligned state.

    node
        The node domain: executable units, capability hosting, orchestration
        targets, dispatch semantics, invocation governance, and
        execution-oriented lifecycle.
    """

    device = "device"
    node = "node"


class DeviceDomainResponsibility(str, Enum):
    """The canonical responsibilities of the device domain.

    device_identity
        Maintaining stable, persistent device identifiers and hardware/software
        endpoint facts.

    runtime_hosting
        Tracking which devices currently host active runtimes (execution
        environments that can receive delegated tasks).

    connectivity
        Managing device transport connections (WebSocket, REST, address/port
        facts) and connection state.

    registration
        Canonical registration of new devices through the SSOT write path
        (UnifiedDeviceManager).

    ssot_aligned_state
        Maintaining mutable device state (status, capabilities, metadata,
        last-seen) as the single source of truth.  Only the device-domain
        SSOT write path may mutate canonical device state.

    presence_lifecycle
        Managing presence-oriented lifecycle transitions: device coming online,
        going offline, entering busy/idle states, heartbeat-based timeout
        detection, and reconnect handling.

    capability_evidence
        Collecting and normalizing capability evidence reported by devices
        (e.g. Android capability reports).  Capability evidence is device-domain
        input; capability routing is a node-domain or bridge concern.
    """

    device_identity = "device_identity"
    runtime_hosting = "runtime_hosting"
    connectivity = "connectivity"
    registration = "registration"
    ssot_aligned_state = "ssot_aligned_state"
    presence_lifecycle = "presence_lifecycle"
    capability_evidence = "capability_evidence"


class NodeDomainResponsibility(str, Enum):
    """The canonical responsibilities of the node domain.

    executable_unit_registration
        Registering and tracking executable units (nodes) that can perform
        tasks in the center runtime.

    capability_hosting
        Hosting named capability surfaces that can be discovered and invoked
        through the capability bus.  Capability hosting is distinct from
        capability evidence: the node domain owns the routing surface.

    orchestration_targeting
        Identifying eligible orchestration targets for task dispatch, including
        evaluating node health, architectural class, and invocation governance.

    dispatch_semantics
        Defining and enforcing the semantics of task dispatch: local execution,
        remote handoff, fallback-local, staged mesh, and delegated dispatch
        paths.

    invocation_governance
        Enforcing eligibility rules at node invocation time (node
        governance, boundary enforcement, lifecycle-stage constraints).

    boundary_enforcement
        Classifying node surfaces as canonical, compat-only, internal-only, or
        deprecated, and enforcing that classification at runtime.

    execution_lifecycle
        Managing execution-oriented lifecycle transitions: node starting,
        healthy, unhealthy, suspended, archived, retired.  This lifecycle is
        distinct from device presence lifecycle.

    capability_sync
        Synchronizing capability declarations from eligible nodes into the
        capability registry (OpenClawd capability bus).
    """

    executable_unit_registration = "executable_unit_registration"
    capability_hosting = "capability_hosting"
    orchestration_targeting = "orchestration_targeting"
    dispatch_semantics = "dispatch_semantics"
    invocation_governance = "invocation_governance"
    boundary_enforcement = "boundary_enforcement"
    execution_lifecycle = "execution_lifecycle"
    capability_sync = "capability_sync"


class BridgeRelationshipKind(str, Enum):
    """The kinds of bridge relationships that connect the device and node domains.

    runtime_host
        A device that hosts an active runtime (execution environment).  The
        device is a device-domain participant (identified by device_id, tracked
        by UDM).  The runtime is a node-domain execution target.  The bridge
        surface is :mod:`contracts.registered_runtime_device` combined with
        node dispatch.

    capability_host
        A device whose capability evidence is assimilated into the node-domain
        capability routing plane.  The device contributes capability evidence
        (device domain); the assimilation layer (capability_assimilation) acts
        as the bridge surface that converts device capability evidence into
        node-domain routing entries.

    dispatch_target
        A device selected as the execution target for a delegated task.  The
        source dispatch orchestrator resolves dispatch routing through
        node-domain eligibility logic; when the selected target is a device
        (e.g. Android), the dispatch mechanism bridges into the device domain
        to deliver the task.
    """

    runtime_host = "runtime_host"
    capability_host = "capability_host"
    dispatch_target = "dispatch_target"


class RegistrySurfaceDomain(str, Enum):
    """The domain that owns a given registry or truth surface.

    device
        Owned by the device domain (UDM, device registry, device contract).

    node
        Owned by the node domain (NodeFabricRegistry, invocation governance,
        boundary enforcement).

    bridge
        A bridge surface that connects the two domains without belonging
        exclusively to either (capability assimilation, dispatch orchestrator).

    shared_projection
        A read-only projection surface that assembles facts from both domains
        for operator or external consumption.
    """

    device = "device"
    node = "node"
    bridge = "bridge"
    shared_projection = "shared_projection"


class RegistrySurfaceRole(str, Enum):
    """The authority role of a registry or truth surface.

    ssot
        Single source of truth — this surface is the canonical write authority
        for mutable state.  No other surface may act as a parallel SSOT.

    canonical_registry
        A canonical runtime registry that holds the authoritative set of
        registered entities.

    projection
        A read-only projection or compiled truth view.  Projects or assembles
        facts from one or more authoritative sources; does not write truth.

    cache
        A read-through cache or index derived from an authoritative source.
        Not canonical; must not be treated as truth.

    compat_facade
        A compatibility facade that provides a migration shim over a canonical
        surface.  Not authoritative; must not be extended as canonical
        architecture.

    adapter
        A routing helper, protocol adapter, or transport bridge.  Not a truth
        surface; used only for protocol translation and routing.

    bridge
        A bridge layer connecting two domains.  Not owned exclusively by either
        domain; governed explicitly as a bridge surface.
    """

    ssot = "ssot"
    canonical_registry = "canonical_registry"
    projection = "projection"
    cache = "cache"
    compat_facade = "compat_facade"
    adapter = "adapter"
    bridge = "bridge"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DomainDefinition:
    """Canonical definition of a domain's responsibilities and authority surfaces.

    Attributes
    ----------
    domain:
        The domain this definition describes.
    responsibilities:
        Canonical list of responsibilities owned by this domain.
    authority_surfaces:
        List of canonical authority surface module paths for this domain.
    description:
        Human-readable description of the domain's role in the center runtime.
    lifecycle_kind:
        Short label for the kind of lifecycle this domain governs
        (e.g. ``"presence_lifecycle"`` vs ``"execution_lifecycle"``).
    """

    domain: DomainKind
    responsibilities: List[str]
    authority_surfaces: List[str]
    description: str
    lifecycle_kind: str

    def to_dict(self) -> Dict:
        return {
            "domain": self.domain.value,
            "responsibilities": list(self.responsibilities),
            "authority_surfaces": list(self.authority_surfaces),
            "description": self.description,
            "lifecycle_kind": self.lifecycle_kind,
            "authority": DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY,
        }


@dataclass
class BridgeRelationship:
    """Description of a bridge relationship connecting the device and node domains.

    Attributes
    ----------
    kind:
        The kind of bridge relationship.
    center_surface:
        The center-side module path(s) that implement this bridge.
    device_domain_role:
        How the device domain participates in this bridge.
    node_domain_role:
        How the node domain participates in this bridge.
    description:
        Human-readable description of the bridge semantics.
    android_relevance:
        Brief note on how this bridge applies to Android runtime participants
        (the primary non-center runtime-host participant).
    """

    kind: BridgeRelationshipKind
    center_surface: List[str]
    device_domain_role: str
    node_domain_role: str
    description: str
    android_relevance: str

    def to_dict(self) -> Dict:
        return {
            "kind": self.kind.value,
            "center_surface": list(self.center_surface),
            "device_domain_role": self.device_domain_role,
            "node_domain_role": self.node_domain_role,
            "description": self.description,
            "android_relevance": self.android_relevance,
        }


@dataclass
class RegistrySurfaceClassification:
    """Classification of a registry or truth surface by domain and authority role.

    Attributes
    ----------
    module_path:
        The canonical module path for the surface.
    surface_name:
        Human-readable surface name.
    domain:
        The domain that owns this surface.
    role:
        The authority role of this surface.
    notes:
        Any governance notes, migration status, or constraints.
    is_authoritative:
        True if this surface is an SSOT or canonical registry (may write
        truth); False if it is a projection, cache, facade, or adapter.
    """

    module_path: str
    surface_name: str
    domain: RegistrySurfaceDomain
    role: RegistrySurfaceRole
    notes: str
    is_authoritative: bool = False

    def to_dict(self) -> Dict:
        return {
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "domain": self.domain.value,
            "role": self.role.value,
            "notes": self.notes,
            "is_authoritative": self.is_authoritative,
        }


@dataclass
class DomainGovernanceSnapshot:
    """A complete, JSON-serialisable snapshot of the device/node domain governance model.

    Attributes
    ----------
    device_domain:
        The canonical device domain definition.
    node_domain:
        The canonical node domain definition.
    bridge_relationships:
        All bridge relationships connecting the two domains.
    registry_surface_catalogue:
        All classified registry and truth surfaces across both domains.
    generated_at:
        Monotonic timestamp when the snapshot was generated.
    authority:
        The authority sentinel for this snapshot.
    """

    device_domain: DomainDefinition
    node_domain: DomainDefinition
    bridge_relationships: List[BridgeRelationship]
    registry_surface_catalogue: List[RegistrySurfaceClassification]
    generated_at: float = field(default_factory=time.monotonic)
    authority: str = DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY

    def to_dict(self) -> Dict:
        return {
            "device_domain": self.device_domain.to_dict(),
            "node_domain": self.node_domain.to_dict(),
            "bridge_relationships": [b.to_dict() for b in self.bridge_relationships],
            "registry_surface_catalogue": [
                r.to_dict() for r in self.registry_surface_catalogue
            ],
            "generated_at": self.generated_at,
            "authority": self.authority,
            "sentinel": DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL,
        }


# ---------------------------------------------------------------------------
# Canonical domain definitions
# ---------------------------------------------------------------------------

_DEVICE_DOMAIN_DEFINITION = DomainDefinition(
    domain=DomainKind.device,
    responsibilities=[r.value for r in DeviceDomainResponsibility],
    authority_surfaces=[
        "core.unified.unified_device_manager.UnifiedDeviceManager",
        "contracts.registered_runtime_device.RegisteredRuntimeDevice",
        "core.device_registry.DeviceRegistry",
        "core.device_types.DeviceType",
        "core.device_types.DeviceStatus",
        "core.device_readiness",
        "core.device_participation",
        "core.device_execution_profile",
    ],
    description=(
        "The device domain owns device identity, runtime hosting facts, "
        "connectivity metadata, canonical device registration (through UDM as "
        "the SSOT write authority), presence-oriented lifecycle (online, "
        "offline, busy, heartbeat timeout), and capability evidence collection. "
        "The device domain does NOT own dispatch semantics, invocation "
        "governance, or execution-lifecycle management — those belong to the "
        "node domain.  A device that hosts a runtime or acts as a dispatch "
        "target remains a device-domain participant; it is not reclassified as "
        "a node."
    ),
    lifecycle_kind="presence_lifecycle",
)

_NODE_DOMAIN_DEFINITION = DomainDefinition(
    domain=DomainKind.node,
    responsibilities=[r.value for r in NodeDomainResponsibility],
    authority_surfaces=[
        "core.nodes.node_fabric_registry.NodeFabricRegistry",
        "core.node_invocation_governance",
        "core.node_boundary_runtime",
        "core.node_governance_runtime",
        "core.node_lifecycle_governor",
        "core.node_cognition_activation",
        "core.node_final_boundary_enforcement",
        "core.fusion_entry_adapter",
    ],
    description=(
        "The node domain owns the registration and lifecycle management of "
        "executable units (nodes), capability hosting and synchronization into "
        "the capability bus, orchestration target selection, dispatch semantics "
        "(local, remote, fallback, staged, delegated), invocation governance "
        "(eligibility enforcement at invocation time), and boundary "
        "enforcement (canonical vs compat-only vs deprecated surface "
        "classification).  The node domain does NOT own device identity, "
        "device presence, or SSOT-aligned device state — those belong to the "
        "device domain.  When a device is selected as a dispatch target, the "
        "node domain resolves the dispatch path; the device remains a "
        "device-domain participant receiving the delegated task."
    ),
    lifecycle_kind="execution_lifecycle",
)


# ---------------------------------------------------------------------------
# Canonical bridge relationships
# ---------------------------------------------------------------------------

_BRIDGE_RELATIONSHIPS: List[BridgeRelationship] = [
    BridgeRelationship(
        kind=BridgeRelationshipKind.runtime_host,
        center_surface=[
            "contracts.registered_runtime_device.RegisteredRuntimeDevice",
            "core.attached_runtime_session_registry",
            "core.android_runtime_host",
            "core.runtime.source_dispatch_orchestrator",
        ],
        device_domain_role=(
            "The device provides its device_id, connectivity facts, and "
            "capability evidence to the device domain.  UnifiedDeviceManager "
            "maintains the SSOT device record including runtime-host status."
        ),
        node_domain_role=(
            "The node domain's dispatch orchestrator uses the device's "
            "runtime-host status to determine whether the device is a valid "
            "execution target for delegated task dispatch."
        ),
        description=(
            "A device that hosts an active runtime (execution environment) "
            "may be selected as a dispatch target by the node-domain's source "
            "dispatch orchestrator.  The runtime-host bridge is the primary "
            "device→node bridge: device identity (device domain) combines with "
            "dispatch eligibility logic (node domain) to produce an execution "
            "target selection.  The bridge surface is "
            "RegisteredRuntimeDevice.participant_identity combined with "
            "attached_runtime_session_registry runtime-host tracking."
        ),
        android_relevance=(
            "Android is the primary non-center runtime-host participant.  When "
            "Android is online and its runtime session is active, it is a "
            "candidate dispatch target through this bridge.  Android does not "
            "participate in center-side node governance; it is a device-domain "
            "participant that receives delegated tasks."
        ),
    ),
    BridgeRelationship(
        kind=BridgeRelationshipKind.capability_host,
        center_surface=[
            "core.capability_assimilation.CapabilityAssimilationLayer",
            "core.capability_assimilation.assimilate_device",
            "core.nodes.node_fabric_registry.NodeFabricRegistry.sync_capabilities_to_registry",
        ],
        device_domain_role=(
            "The device reports capability evidence (e.g. camera, screen, "
            "microphone) to the device domain through device_capability_report "
            "messages.  The device domain normalizes and stores this evidence "
            "in the device record (via UDM).  Capability evidence is "
            "device-domain input; the device is not directly registered as a "
            "node."
        ),
        node_domain_role=(
            "The capability assimilation layer (bridge surface) absorbs device "
            "capability evidence and registers the device as a "
            "NodeParticipantKind.DEVICE in the assimilation layer, making its "
            "capabilities discoverable through node-domain routing.  The node "
            "domain's capability sync path controls which assimilated "
            "participants appear on the capability bus."
        ),
        description=(
            "Device capability evidence (device domain) is bridged into "
            "node-domain capability routing through the capability assimilation "
            "layer (core.capability_assimilation).  Devices assimilated via "
            "assimilate_device() receive NodeParticipantKind.DEVICE so the "
            "capability selection plane can treat them as first-class "
            "capability providers alongside nodes, workers, skills, and MCP "
            "providers.  The bridge preserves domain separation: the device "
            "retains its device-domain identity; the assimilation record is a "
            "bridge artifact, not a node-domain node registration."
        ),
        android_relevance=(
            "Android capability reports (capability_report messages) are "
            "normalized at center ingress and may be assimilated as device "
            "capability evidence.  Android-reported capabilities are one input "
            "source for this bridge; they do not make Android a node-domain "
            "participant."
        ),
    ),
    BridgeRelationship(
        kind=BridgeRelationshipKind.dispatch_target,
        center_surface=[
            "core.runtime.source_dispatch_orchestrator",
            "core.android_runtime_dispatch_binding",
            "core.canonical_execution_chain",
            "core.canonical_handoff_path",
        ],
        device_domain_role=(
            "The device is available as a potential dispatch target if its "
            "device-domain runtime-host status is active.  The device receives "
            "the delegated task through its device-domain transport connection "
            "(WebSocket / REST).  Execution results are returned as "
            "delegated_execution_signal messages, normalized at center ingress "
            "by core.android_delegated_signal_ingress."
        ),
        node_domain_role=(
            "The node domain's source dispatch orchestrator resolves the "
            "dispatch mode (local, remote, fallback-local, staged-mesh, "
            "delegated) and selects the execution target using node-domain "
            "eligibility logic and dispatch semantics.  When the selected "
            "target is a device, the dispatch path bridges into the device "
            "domain for delivery."
        ),
        description=(
            "Dispatch targeting is the bridge surface where node-domain "
            "dispatch semantics meet device-domain runtime hosting.  The "
            "source dispatch orchestrator (node domain) selects a dispatch "
            "mode and target; when the target is a device, the delegated "
            "dispatch path (android_runtime_dispatch_binding or equivalent) "
            "delivers the task to the device through its device-domain "
            "transport.  The device is not reclassified as a node by this "
            "selection.  Interpreting a dispatch target: if target_device_id "
            "is set and the device is a registered runtime host, the dispatch "
            "is device-domain-bound; node-domain dispatch logic selected it "
            "based on capability and runtime-host eligibility."
        ),
        android_relevance=(
            "Android receives delegated tasks through this bridge when selected "
            "as the dispatch target.  center source dispatch orchestrator "
            "initiates the delegation; Android receives it, executes locally, "
            "and returns signals through the delegated execution signal "
            "channel.  Android is a device-domain participant throughout; it "
            "is never a node-domain entity."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Canonical registry surface catalogue
# ---------------------------------------------------------------------------

_REGISTRY_SURFACE_CATALOGUE: List[RegistrySurfaceClassification] = [
    # Device domain — SSOT and canonical registry
    RegistrySurfaceClassification(
        module_path="core.unified.unified_device_manager.UnifiedDeviceManager",
        surface_name="UnifiedDeviceManager (UDM)",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.ssot,
        notes=(
            "The only canonical SSOT write authority for device registration "
            "and mutable device state.  All registration paths must write "
            "through UDM.  No other module may act as a parallel mutable "
            "device-state authority."
        ),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="contracts.registered_runtime_device.RegisteredRuntimeDevice",
        surface_name="RegisteredRuntimeDevice contract",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "The sole canonical external single-device read contract (PR-5 "
            "device contract).  All device-surface views must normalize into "
            "this contract before being consumed by runtime, projection, "
            "governance, or API layers."
        ),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.device_registry.DeviceRegistry",
        surface_name="DeviceRegistry",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "Device registry that delegates canonical writes to UDM.  "
            "Maintains in-process device state indexed by device_id.  "
            "UDM-first semantics: UDM is checked before local state "
            "construction to prevent divergent canonical identity."
        ),
        is_authoritative=True,
    ),
    # Device domain — projection and adapter surfaces
    RegistrySurfaceClassification(
        module_path="core.device_readiness",
        surface_name="device readiness",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.projection,
        notes=(
            "Readiness verdict synthesis for devices.  Compiles readiness "
            "evidence into a verdict; does not write canonical device state."
        ),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.device_participation",
        surface_name="device participation",
        domain=RegistrySurfaceDomain.device,
        role=RegistrySurfaceRole.projection,
        notes=(
            "Device participation hints and multi-device group membership.  "
            "Projects from device-domain state; does not write canonical state."
        ),
        is_authoritative=False,
    ),
    # Node domain — canonical registry and governance
    RegistrySurfaceClassification(
        module_path="core.nodes.node_fabric_registry.NodeFabricRegistry",
        surface_name="NodeFabricRegistry",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "The canonical runtime node registry.  Maintains the authoritative "
            "set of registered nodes, their health, capabilities, roles, and "
            "architectural classes.  All node-surface consumers should read "
            "from NodeFabricRegistry, not from compat facades."
        ),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_registry.NodeRegistry",
        surface_name="NodeRegistry (compat facade)",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.compat_facade,
        notes=(
            "Legacy compat facade over NodeFabricRegistry "
            "(LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL).  Not "
            "authoritative.  Must not be extended as canonical architecture."
        ),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_invocation_governance",
        surface_name="node invocation governance",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "Canonical eligibility enforcement at node invocation time.  "
            "Ineligible nodes (archived/deprecated/unhealthy) are denied with "
            "structured eligibility_denial payload.  COMPAT_INTERNAL override "
            "bypasses for internal paths only."
        ),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_governance_runtime",
        surface_name="node governance runtime",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "Canonical runtime governance eligibility authority for node "
            "exposure and capability synchronization.  Enforces architectural "
            "class, health, and lifecycle-stage constraints as real runtime "
            "filters."
        ),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.node_boundary_runtime",
        surface_name="node boundary runtime",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "Canonical authority for Galaxy node boundary definitions and "
            "invocation pathway classification.  Classifies surfaces as "
            "canonical, compat-only, internal-only, or deprecated."
        ),
        is_authoritative=True,
    ),
    RegistrySurfaceClassification(
        module_path="core.fusion_entry_adapter",
        surface_name="fusion_entry adapter contract",
        domain=RegistrySurfaceDomain.node,
        role=RegistrySurfaceRole.adapter,
        notes=(
            "Canonical adapter contract for fusion_entry.py execution adapter.  "
            "fusion_entry.py is execution adapter ONLY — not registry/discovery."
        ),
        is_authoritative=False,
    ),
    # Bridge surfaces
    RegistrySurfaceClassification(
        module_path="core.capability_assimilation.CapabilityAssimilationLayer",
        surface_name="capability assimilation layer",
        domain=RegistrySurfaceDomain.bridge,
        role=RegistrySurfaceRole.bridge,
        notes=(
            "Bridges device capability evidence (device domain) into node-domain "
            "capability routing.  Devices assimilated via assimilate_device() "
            "receive NodeParticipantKind.DEVICE.  This is a bridge surface: "
            "it does not own device identity and is not a node registry."
        ),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.runtime.source_dispatch_orchestrator",
        surface_name="source dispatch orchestrator",
        domain=RegistrySurfaceDomain.bridge,
        role=RegistrySurfaceRole.bridge,
        notes=(
            "Bridges node-domain dispatch semantics with device-domain runtime "
            "hosting for the dispatch-target bridge.  Resolves dispatch mode "
            "and target using node-domain eligibility; delivers to device "
            "domain when target is a device."
        ),
        is_authoritative=False,
    ),
    # Shared projection surfaces
    RegistrySurfaceClassification(
        module_path="core.routes.projection",
        surface_name="projection routes",
        domain=RegistrySurfaceDomain.shared_projection,
        role=RegistrySurfaceRole.projection,
        notes=(
            "Read-only projection surface that assembles runtime facts from "
            "both device-domain and node-domain authority surfaces for "
            "operator and API consumption.  Does not write truth."
        ),
        is_authoritative=False,
    ),
    RegistrySurfaceClassification(
        module_path="core.capability_registry.CapabilityRegistry",
        surface_name="capability registry (OpenClawd bus)",
        domain=RegistrySurfaceDomain.shared_projection,
        role=RegistrySurfaceRole.canonical_registry,
        notes=(
            "The OpenClawd capability bus.  Node-domain capability sync "
            "injects capabilities from eligible nodes; bridge surfaces inject "
            "device capability entries.  This surface is shared: its entries "
            "originate from both node-domain nodes and device-domain devices "
            "(via bridge assimilation)."
        ),
        is_authoritative=True,
    ),
]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def get_device_domain_definition() -> DomainDefinition:
    """Return the canonical device domain definition.

    Returns the authoritative :class:`DomainDefinition` for the device domain,
    including its canonical responsibilities, authority surfaces, description,
    and lifecycle kind.

    Returns
    -------
    DomainDefinition
        The canonical device domain definition.
    """
    return _DEVICE_DOMAIN_DEFINITION


def get_node_domain_definition() -> DomainDefinition:
    """Return the canonical node domain definition.

    Returns the authoritative :class:`DomainDefinition` for the node domain,
    including its canonical responsibilities, authority surfaces, description,
    and lifecycle kind.

    Returns
    -------
    DomainDefinition
        The canonical node domain definition.
    """
    return _NODE_DOMAIN_DEFINITION


def get_bridge_relationships() -> List[BridgeRelationship]:
    """Return all canonical bridge relationships between the device and node domains.

    Returns
    -------
    List[BridgeRelationship]
        Immutable list of all three canonical bridge relationships:
        runtime_host, capability_host, and dispatch_target.
    """
    return list(_BRIDGE_RELATIONSHIPS)


def get_bridge_relationship(kind: BridgeRelationshipKind) -> Optional[BridgeRelationship]:
    """Return the canonical bridge relationship for a given kind.

    Parameters
    ----------
    kind:
        The :class:`BridgeRelationshipKind` to look up.

    Returns
    -------
    BridgeRelationship or None
        The matching bridge relationship, or ``None`` if not found.
    """
    for bridge in _BRIDGE_RELATIONSHIPS:
        if bridge.kind == kind:
            return bridge
    return None


def classify_registry_surface(module_path: str) -> Optional[RegistrySurfaceClassification]:
    """Return the governance classification for a given registry or truth surface.

    Performs a case-insensitive substring match on ``module_path`` against the
    canonical registry surface catalogue.

    Parameters
    ----------
    module_path:
        The module path to classify (e.g.
        ``"core.nodes.node_fabric_registry.NodeFabricRegistry"``).

    Returns
    -------
    RegistrySurfaceClassification or None
        The matching classification, or ``None`` if the surface is not in the
        catalogue.
    """
    query = module_path.lower()
    for entry in _REGISTRY_SURFACE_CATALOGUE:
        if entry.module_path.lower() == query:
            return entry
    # Fallback: allow query to be a prefix/leading substring of an entry path,
    # but not the reverse (avoids matching short prefixes like 'core' against
    # fully-qualified paths).
    for entry in _REGISTRY_SURFACE_CATALOGUE:
        if entry.module_path.lower().startswith(query) and len(query) > 10:
            return entry
    return None


def get_surfaces_by_domain(domain: RegistrySurfaceDomain) -> List[RegistrySurfaceClassification]:
    """Return all registry surface classifications for a given domain.

    Parameters
    ----------
    domain:
        The :class:`RegistrySurfaceDomain` to filter by.

    Returns
    -------
    List[RegistrySurfaceClassification]
        All surfaces classified under the given domain.
    """
    return [s for s in _REGISTRY_SURFACE_CATALOGUE if s.domain == domain]


def get_authoritative_surfaces() -> List[RegistrySurfaceClassification]:
    """Return all registry surfaces that are authoritative truth or SSOT surfaces.

    Returns
    -------
    List[RegistrySurfaceClassification]
        All surfaces with ``is_authoritative=True``.
    """
    return [s for s in _REGISTRY_SURFACE_CATALOGUE if s.is_authoritative]


def build_domain_governance_snapshot() -> DomainGovernanceSnapshot:
    """Build a complete, JSON-serialisable governance snapshot.

    Assembles the full device/node domain governance model into a
    :class:`DomainGovernanceSnapshot` suitable for operator inspection,
    CI-level visibility, and runtime diagnostics.

    Returns
    -------
    DomainGovernanceSnapshot
        The complete governance snapshot.
    """
    return DomainGovernanceSnapshot(
        device_domain=get_device_domain_definition(),
        node_domain=get_node_domain_definition(),
        bridge_relationships=get_bridge_relationships(),
        registry_surface_catalogue=list(_REGISTRY_SURFACE_CATALOGUE),
        generated_at=time.monotonic(),
        authority=DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY,
    )


def get_governance_summary() -> Dict:
    """Return a compact governance summary dictionary.

    Suitable for embedding in projection route responses or diagnostic
    endpoints.

    Returns
    -------
    Dict
        A compact summary of the governance model with domain counts, bridge
        counts, and sentinel information.
    """
    device_def = get_device_domain_definition()
    node_def = get_node_domain_definition()
    bridges = get_bridge_relationships()
    authoritative = get_authoritative_surfaces()
    return {
        "authority": DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY,
        "sentinel": DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL,
        "device_domain": {
            "responsibility_count": len(device_def.responsibilities),
            "authority_surface_count": len(device_def.authority_surfaces),
            "lifecycle_kind": device_def.lifecycle_kind,
        },
        "node_domain": {
            "responsibility_count": len(node_def.responsibilities),
            "authority_surface_count": len(node_def.authority_surfaces),
            "lifecycle_kind": node_def.lifecycle_kind,
        },
        "bridge_relationships": [b.kind.value for b in bridges],
        "total_catalogued_surfaces": len(_REGISTRY_SURFACE_CATALOGUE),
        "authoritative_surfaces": len(authoritative),
        "governance_model": "bridge-preserving, no-false-identity-equivalence",
    }
