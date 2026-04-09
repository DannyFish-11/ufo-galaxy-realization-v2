#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_boundary_runtime.py
==============================
PR-8: Decommission Legacy Node Paths and Formalize Runtime Boundaries.

This module is the **canonical authority** for defining and enforcing the
architectural boundary of the Galaxy node system.  It makes the boundary
between *canonical* node execution pathways and *compatibility-only legacy*
pathways explicit and programmatically enforceable.

Problem addressed
-----------------
Prior to PR-8, the Galaxy node system had several overlapping execution
pathways that competed implicitly as peer authorities:

1. **Legacy direct filesystem scans** — ``GET /api/v1/nodes`` would walk the
   ``nodes/`` directory directly, bypassing :class:`NodeFabricRegistry`.

2. **Legacy registry references** — code still imported from
   ``core.node_registry.NodeRegistry`` even though
   :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` is the
   canonical runtime registry.

3. **Compatibility-only HTTP node execution** — ``POST /api/v1/nodes/call``
   functioned as a peer execution authority to the canonical
   :func:`~core.node_invocation.invoke_node` path, creating ambiguity.

4. **fusion_entry used as a registry/discovery authority** — code imported
   from ``fusion_entry.py`` to determine node existence or eligibility instead
   of consulting the canonical fabric registry.

5. **Deprecated nodes appearing active** — nodes with
   ``LEGACY_ORCHESTRATOR_NODE`` architectural class appeared alongside
   canonical ``CAPABILITY_NODE`` nodes in status surfaces without a clear
   runtime boundary.

This module bridges:
  - :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` — canonical
    runtime registry (single source of truth for running nodes).
  - :class:`~core.node_invocation.UnifiedNodeExecutor` — canonical invocation
    path (all calls must go through :func:`~core.node_invocation.invoke_node`).
  - :class:`~core.fusion_entry_adapter` — execution-adapter-only contract
    (must not be used as registry or discovery authority).
  - :class:`~core.node_governance_runtime` — governance eligibility filter.
  - :class:`~core.node_discovery_runtime` — discovery participation layer.

Boundary definitions
--------------------
Nodes occupy a precisely defined architectural role:

  **CAPABILITY PROVIDER / LOCAL EXECUTOR BACKEND**

  Nodes are local execution backends that provide capabilities to the system's
  capability bus (OpenClawd / CapabilityRegistry).  They are NOT:

  - A competing execution authority or distributed runtime backbone.
  - A peer to the canonical runtime dispatch path.
  - A registry/discovery authority (that role belongs to NodeFabricRegistry
    and NodeDiscoveryService).

Canonical pathway
-----------------
The canonical node execution pathway is::

    caller → invoke_node() → UnifiedNodeExecutor → fusion_entry adapter → result

Any pathway that bypasses :func:`~core.node_invocation.invoke_node` is either
a **compatibility-only legacy surface** or an architectural violation.

Legacy/compat surfaces explicitly demoted by this module
---------------------------------------------------------
+----------------------------------------+------------------------+---------------------+
| Surface                                | Status                 | Canonical path      |
+========================================+========================+=====================+
| NodeRegistry (core.node_registry)      | LEGACY_COMPAT_FACADE   | NodeFabricRegistry  |
| Direct fs scan in GET /api/v1/nodes    | LEGACY_COMPAT_SCAN     | NodeFabricRegistry  |
| POST /api/v1/nodes/call (direct call)  | COMPAT_ENDPOINT        | invoke_node()       |
| fusion_entry as registry authority     | NOT_REGISTRY_AUTHORITY | NodeFabricRegistry  |
| LEGACY_ORCHESTRATOR_NODE on canon path | DEMOTED                | CAPABILITY_NODE only|
+----------------------------------------+------------------------+---------------------+

Compatibility
-------------
Every public function degrades gracefully when
:mod:`core.nodes.node_fabric_registry` or :mod:`core.node_invocation` is
unavailable.  Fallback paths are logged and sentinel-annotated.

Public API
----------
Authority sentinels::

    NODE_BOUNDARY_IS_CANONICAL_AUTHORITY
    NODE_BOUNDARY_RUNTIME_PR8_SENTINEL

Policy sentinels::

    NODES_ARE_CAPABILITY_BACKENDS_ONLY_POLICY
    CANONICAL_INVOCATION_PATH_IS_INVOKE_NODE_POLICY
    LEGACY_REGISTRY_IS_COMPAT_FACADE_POLICY
    DIRECT_SCAN_IS_LEGACY_COMPAT_POLICY
    LEGACY_ORCHESTRATOR_NODES_DEMOTED_FROM_CANONICAL_PATH_POLICY

Enums::

    NodePathwayKind
    LegacyNodeSurfaceStatus

Dataclasses::

    NodeBoundaryDecision
    LegacyNodeSurfaceEntry
    NodeBoundarySnapshot

Functions::

    classify_invocation_pathway(pathway_name)
    build_legacy_surface_registry()
    evaluate_node_boundary_compliance(node_info)
    get_canonical_nodes(fabric_registry=None)
    build_node_boundary_snapshot(fabric_registry=None)
    get_boundary_summary()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.Nodes.NodeBoundaryRuntime")

# ===========================================================================
# Authority sentinels
# ===========================================================================

NODE_BOUNDARY_IS_CANONICAL_AUTHORITY: str = (
    "NODE_BOUNDARY_RUNTIME::PR8_AUTHORITY_V1: "
    "core/node_boundary_runtime.py is the canonical authority for defining and "
    "enforcing Galaxy node system boundaries.  Nodes are capability providers / "
    "local executor backends only — not a competing execution authority or "
    "distributed runtime backbone.  Canonical invocation path is invoke_node() "
    "via UnifiedNodeExecutor.  Legacy surfaces (NodeRegistry, direct fs-scan, "
    "direct /api/v1/nodes/call, LEGACY_ORCHESTRATOR_NODE on canonical path) are "
    "explicitly demoted to compatibility-only status.  NodeFabricRegistry is the "
    "single source of runtime truth for node existence and health."
)

NODE_BOUNDARY_RUNTIME_PR8_SENTINEL: str = (
    "NODE_BOUNDARY_RUNTIME::PR8_SENTINEL_V1"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

NODES_ARE_CAPABILITY_BACKENDS_ONLY_POLICY: str = (
    "NODE_BOUNDARY_RUNTIME::CAPABILITY_BACKENDS_ONLY_POLICY_V1: "
    "Nodes in the Galaxy system occupy exactly one architectural role: "
    "capability provider / local executor backend.  They are not a distributed "
    "runtime backbone, not a peer execution authority to the canonical runtime "
    "dispatch path, and not a registry or discovery authority.  New code must "
    "not expand the node role beyond local capability execution."
)

CANONICAL_INVOCATION_PATH_IS_INVOKE_NODE_POLICY: str = (
    "NODE_BOUNDARY_RUNTIME::CANONICAL_INVOCATION_POLICY_V1: "
    "All node invocations must enter through invoke_node() "
    "(core.node_invocation) which constructs a NodeInvocationEnvelope and "
    "routes through UnifiedNodeExecutor.  Any pathway that bypasses "
    "invoke_node() is a compatibility-only legacy surface and must be "
    "explicitly marked as such.  Direct calls to _load_node/_execute_node "
    "without going through invoke_node() are architectural violations."
)

LEGACY_REGISTRY_IS_COMPAT_FACADE_POLICY: str = (
    "NODE_BOUNDARY_RUNTIME::LEGACY_REGISTRY_COMPAT_FACADE_POLICY_V1: "
    "core.node_registry.NodeRegistry is a compatibility facade only.  "
    "NodeFabricRegistry (core.nodes.node_fabric_registry) is the canonical "
    "runtime node registry.  No new runtime-authority logic must be added to "
    "NodeRegistry.  Callers must migrate to NodeFabricRegistry."
)

DIRECT_SCAN_IS_LEGACY_COMPAT_POLICY: str = (
    "NODE_BOUNDARY_RUNTIME::DIRECT_SCAN_COMPAT_POLICY_V1: "
    "Direct filesystem scans of the nodes/ directory (e.g. os.listdir('nodes/')) "
    "to enumerate nodes are a legacy compatibility pattern.  The canonical source "
    "of running-node truth is NodeFabricRegistry.list_nodes().  Status endpoints "
    "must read from NodeFabricRegistry, not from direct filesystem scans."
)

LEGACY_ORCHESTRATOR_NODES_DEMOTED_FROM_CANONICAL_PATH_POLICY: str = (
    "NODE_BOUNDARY_RUNTIME::LEGACY_ORCHESTRATOR_NODES_DEMOTED_POLICY_V1: "
    "Nodes with NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE must never "
    "appear on the canonical capability-bus surface or canonical tool-exposure "
    "path.  They are guarded by core.orchestration_authority.legacy_paths and "
    "must be registered with explicit architectural_class= "
    "NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE.  Status surfaces may "
    "show them separately as 'legacy' nodes but must not present them as "
    "canonical capability providers."
)

# ===========================================================================
# Enums
# ===========================================================================


class NodePathwayKind(str, Enum):
    """Classification of a node execution or access pathway."""

    CANONICAL = "canonical"
    """Pathway is canonical — routes through invoke_node() / NodeFabricRegistry."""

    COMPAT_ONLY = "compat_only"
    """Pathway is compatibility-only — preserved for backward compatibility but
    must not be used in new code.  Will be removed in a future PR."""

    LEGACY_SCAN = "legacy_scan"
    """Pathway uses direct filesystem scanning instead of NodeFabricRegistry."""

    LEGACY_REGISTRY = "legacy_registry"
    """Pathway reads from the legacy NodeRegistry facade instead of
    NodeFabricRegistry."""

    ARCHITECTURAL_VIOLATION = "architectural_violation"
    """Pathway bypasses invoke_node() without an explicit compat justification."""


class LegacyNodeSurfaceStatus(str, Enum):
    """Lifecycle status for a legacy node surface."""

    ACTIVE_CANONICAL = "active_canonical"
    """Surface is canonical and should be used."""

    COMPAT_FACADE = "compat_facade"
    """Surface is a compatibility facade over a canonical replacement."""

    COMPAT_ENDPOINT = "compat_endpoint"
    """HTTP endpoint preserved for backward compatibility.  Internal use only."""

    LEGACY_SCAN_SURFACE = "legacy_scan_surface"
    """Surface performs direct filesystem node enumeration (legacy pattern)."""

    DEMOTED = "demoted"
    """Surface has been explicitly demoted — not authoritative."""

    DELETED = "deleted"
    """Surface has been physically deleted."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class NodeBoundaryDecision:
    """Records the boundary compliance evaluation for a single node.

    Attributes
    ----------
    node_id:
        Unique identifier of the node being evaluated.
    architectural_class:
        The node's ``architectural_class`` string value.
    is_canonical:
        True when the node's architectural class is CAPABILITY_NODE and it
        is therefore eligible for canonical capability-bus exposure.
    boundary_violations:
        List of human-readable descriptions of boundary violations detected.
    diagnostic_context:
        Free-form dict of additional diagnostic information.
    evaluated_at:
        Unix timestamp when the decision was made.
    """

    node_id: str
    architectural_class: str = "capability_node"
    is_canonical: bool = True
    boundary_violations: List[str] = field(default_factory=list)
    diagnostic_context: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "architectural_class": self.architectural_class,
            "is_canonical": self.is_canonical,
            "boundary_violations": list(self.boundary_violations),
            "diagnostic_context": dict(self.diagnostic_context),
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class LegacyNodeSurfaceEntry:
    """Describes a legacy or compatibility-only node surface.

    Attributes
    ----------
    surface_id:
        Short machine-readable identifier (e.g. ``"node_registry_compat"``).
    display_name:
        Human-readable name of the surface.
    status:
        :class:`LegacyNodeSurfaceStatus` classification.
    canonical_replacement:
        Description of the canonical replacement pathway.
    pr_demoted:
        The PR in which this surface was explicitly demoted.
    notes:
        Additional context.
    """

    surface_id: str
    display_name: str
    status: LegacyNodeSurfaceStatus
    canonical_replacement: str
    pr_demoted: str = "PR-8"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "canonical_replacement": self.canonical_replacement,
            "pr_demoted": self.pr_demoted,
            "notes": self.notes,
        }


@dataclass
class NodeBoundarySnapshot:
    """Snapshot of the node boundary compliance state at a point in time.

    Attributes
    ----------
    total_nodes:
        Total number of registered nodes evaluated.
    canonical_nodes:
        Number of nodes on the canonical CAPABILITY_NODE path.
    legacy_nodes:
        Number of LEGACY_ORCHESTRATOR_NODE nodes (demoted).
    violation_nodes:
        Number of nodes with detected boundary violations.
    node_decisions:
        Per-node :class:`NodeBoundaryDecision` records.
    legacy_surfaces:
        Registered legacy/compat surface entries.
    snapshot_time:
        Unix timestamp when the snapshot was taken.
    """

    total_nodes: int = 0
    canonical_nodes: int = 0
    legacy_nodes: int = 0
    violation_nodes: int = 0
    node_decisions: List[NodeBoundaryDecision] = field(default_factory=list)
    legacy_surfaces: List[LegacyNodeSurfaceEntry] = field(default_factory=list)
    snapshot_time: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "canonical_nodes": self.canonical_nodes,
            "legacy_nodes": self.legacy_nodes,
            "violation_nodes": self.violation_nodes,
            "node_decisions": [d.to_dict() for d in self.node_decisions],
            "legacy_surfaces": [s.to_dict() for s in self.legacy_surfaces],
            "snapshot_time": self.snapshot_time,
        }


# ===========================================================================
# Legacy surface registry (static catalogue)
# ===========================================================================

#: Canonical registry of all legacy/compat node surfaces demoted in PR-8.
_LEGACY_SURFACE_CATALOGUE: List[LegacyNodeSurfaceEntry] = [
    LegacyNodeSurfaceEntry(
        surface_id="node_registry_compat_facade",
        display_name="core.node_registry.NodeRegistry",
        status=LegacyNodeSurfaceStatus.COMPAT_FACADE,
        canonical_replacement=(
            "core.nodes.node_fabric_registry.NodeFabricRegistry — "
            "the canonical runtime node registry.  "
            "Import NodeFabricRegistry and use get_node_fabric_registry()."
        ),
        pr_demoted="PR-2 (compat facade), PR-8 (boundary enforced)",
        notes=(
            "NodeRegistry is retained as a thin compat facade for callers that "
            "have not yet migrated.  It must not receive new runtime-authority "
            "logic.  New code must use NodeFabricRegistry directly."
        ),
    ),
    LegacyNodeSurfaceEntry(
        surface_id="direct_fs_scan_nodes_list",
        display_name="GET /api/v1/nodes (direct filesystem scan)",
        status=LegacyNodeSurfaceStatus.LEGACY_SCAN_SURFACE,
        canonical_replacement=(
            "NodeFabricRegistry.list_nodes() — reads the canonical in-memory "
            "runtime registry.  Status data comes from NodeFabricRegistry, "
            "not from os.listdir('nodes/')."
        ),
        pr_demoted="PR-8",
        notes=(
            "The GET /api/v1/nodes route uses os.listdir() over the nodes/ "
            "directory.  This is a legacy scan pattern; it is preserved for "
            "backward compatibility but must not be treated as the authoritative "
            "node enumeration source.  NodeFabricRegistry is the runtime truth."
        ),
    ),
    LegacyNodeSurfaceEntry(
        surface_id="nodes_call_compat_endpoint",
        display_name="POST /api/v1/nodes/call",
        status=LegacyNodeSurfaceStatus.COMPAT_ENDPOINT,
        canonical_replacement=(
            "invoke_node() via core.node_invocation — the unified node "
            "invocation entry point established in PR-4.  All callers should "
            "construct a NodeInvocationEnvelope and call invoke_node() directly "
            "rather than going through the HTTP endpoint."
        ),
        pr_demoted="PR-4 (unified executor), PR-8 (compat reclassified)",
        notes=(
            "POST /api/v1/nodes/call is an internal/compat REST surface.  "
            "It now routes through invoke_node() (PR-4) but the endpoint itself "
            "is compat-only.  Internal Galaxy components must call invoke_node() "
            "directly.  External/legacy callers may continue to use the endpoint "
            "until migration is complete."
        ),
    ),
    LegacyNodeSurfaceEntry(
        surface_id="fusion_entry_as_registry_authority",
        display_name="fusion_entry.py used as node registry / discovery authority",
        status=LegacyNodeSurfaceStatus.DEMOTED,
        canonical_replacement=(
            "NodeFabricRegistry for node existence/health.  "
            "NodeDiscoveryService for capability-based discovery.  "
            "fusion_entry_adapter.py (core.fusion_entry_adapter) for "
            "local execution adapter contract only."
        ),
        pr_demoted="PR-5 (adapter contract), PR-8 (boundary enforced)",
        notes=(
            "fusion_entry.py is an execution adapter only (PR-5).  "
            "It must not be queried to determine node existence, health, "
            "architectural class, or discovery eligibility.  Those queries "
            "belong to NodeFabricRegistry and NodeDiscoveryService."
        ),
    ),
    LegacyNodeSurfaceEntry(
        surface_id="legacy_orchestrator_node_on_canonical_path",
        display_name="LEGACY_ORCHESTRATOR_NODE appearing on canonical tool surface",
        status=LegacyNodeSurfaceStatus.DEMOTED,
        canonical_replacement=(
            "CAPABILITY_NODE nodes only on the canonical capability-bus surface.  "
            "LEGACY_ORCHESTRATOR_NODE nodes are guarded by "
            "core.orchestration_authority.legacy_paths and must be registered "
            "with architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE."
        ),
        pr_demoted="PR-3 (classification), PR-6 (governance filter), PR-8 (boundary enforced)",
        notes=(
            "Node_110_SmartOrchestrator, Node_81_Orchestrator, and "
            "Node_50_Transformer carry LEGACY_ORCHESTRATOR_NODE class.  "
            "NodeGovernanceRuntime (PR-6) excludes them from canonical capability "
            "exposure.  They must not silently appear as peer execution authorities."
        ),
    ),
]


def build_legacy_surface_registry() -> List[LegacyNodeSurfaceEntry]:
    """Return a copy of the static legacy surface catalogue.

    Returns
    -------
    List[LegacyNodeSurfaceEntry]
        All registered legacy/compat node surfaces.
    """
    return list(_LEGACY_SURFACE_CATALOGUE)


# ===========================================================================
# Pathway classification
# ===========================================================================

#: Mapping from pathway name to canonical/compat classification.
_PATHWAY_KIND_MAP: Dict[str, NodePathwayKind] = {
    # Canonical paths
    "invoke_node": NodePathwayKind.CANONICAL,
    "unified_node_executor": NodePathwayKind.CANONICAL,
    "capability_registry_tool_call": NodePathwayKind.CANONICAL,
    "openclawd_node_dispatch": NodePathwayKind.CANONICAL,
    # Compat-only paths
    "post_api_v1_nodes_call": NodePathwayKind.COMPAT_ONLY,
    "legacy_http_node_call": NodePathwayKind.COMPAT_ONLY,
    # Legacy scan paths
    "get_api_v1_nodes_fs_scan": NodePathwayKind.LEGACY_SCAN,
    "direct_nodes_dir_scan": NodePathwayKind.LEGACY_SCAN,
    "node_discovery_safe_scan": NodePathwayKind.LEGACY_SCAN,
    # Legacy registry paths
    "node_registry_legacy": NodePathwayKind.LEGACY_REGISTRY,
    "node_registry_compat_facade": NodePathwayKind.LEGACY_REGISTRY,
}


def classify_invocation_pathway(pathway_name: str) -> NodePathwayKind:
    """Classify a named node invocation or access pathway.

    Parameters
    ----------
    pathway_name:
        Machine-readable pathway identifier.  Unrecognised names default to
        :attr:`NodePathwayKind.CANONICAL` (caller asserts it is canonical).

    Returns
    -------
    NodePathwayKind
        Classification of the pathway.
    """
    return _PATHWAY_KIND_MAP.get(pathway_name, NodePathwayKind.CANONICAL)


# ===========================================================================
# Boundary compliance evaluation
# ===========================================================================

def evaluate_node_boundary_compliance(node_info: Any) -> NodeBoundaryDecision:
    """Evaluate whether *node_info* complies with canonical boundary rules.

    A node is **boundary-compliant** when:

    1. Its ``architectural_class`` is ``CAPABILITY_NODE``.
    2. It does not carry a LEGACY_ORCHESTRATOR_NODE class on the canonical path.

    Parameters
    ----------
    node_info:
        A :class:`~core.nodes.node_fabric_registry.NodeInfo`-like object with
        at minimum a ``node_id`` attribute and an ``architectural_class``
        attribute (str or Enum).

    Returns
    -------
    NodeBoundaryDecision
        Decision record with compliance result and any violations detected.
    """
    node_id: str = getattr(node_info, "node_id", str(node_info))
    arch_class_raw = getattr(node_info, "architectural_class", "capability_node")
    arch_class_str: str = (
        arch_class_raw.value
        if hasattr(arch_class_raw, "value")
        else str(arch_class_raw)
    )

    violations: List[str] = []
    is_canonical = True

    if "legacy_orchestrator" in arch_class_str.lower():
        is_canonical = False
        violations.append(
            f"Node '{node_id}' has architectural_class='{arch_class_str}' "
            "(LEGACY_ORCHESTRATOR_NODE).  It must not appear on the canonical "
            "capability-bus surface.  Guard with legacy_paths and register "
            "with explicit LEGACY_ORCHESTRATOR_NODE class."
        )

    if "archived" in arch_class_str.lower():
        is_canonical = False
        violations.append(
            f"Node '{node_id}' has architectural_class='{arch_class_str}' "
            "(ARCHIVED_NODE).  Archived nodes must not be exposed on any active path."
        )

    return NodeBoundaryDecision(
        node_id=node_id,
        architectural_class=arch_class_str,
        is_canonical=is_canonical,
        boundary_violations=violations,
        diagnostic_context={
            "arch_class_raw": str(arch_class_raw),
            "violation_count": len(violations),
        },
    )


# ===========================================================================
# Canonical node query
# ===========================================================================

def get_canonical_nodes(fabric_registry: Any = None) -> List[Any]:
    """Return only canonical (CAPABILITY_NODE) nodes from *fabric_registry*.

    Parameters
    ----------
    fabric_registry:
        A :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` instance.
        When ``None``, attempts to import the module-level singleton.

    Returns
    -------
    List[NodeInfo]
        All nodes whose ``architectural_class`` is ``CAPABILITY_NODE``.
    """
    registry = fabric_registry
    if registry is None:
        try:
            from core.nodes.node_fabric_registry import (
                get_node_fabric_registry,
                NodeArchitecturalClass,
            )
            registry = get_node_fabric_registry()
        except ImportError:
            logger.warning(
                "NodeFabricRegistry unavailable — get_canonical_nodes() returning []"
            )
            return []

    try:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        return registry.list_by_architectural_class(NodeArchitecturalClass.CAPABILITY_NODE)
    except Exception as exc:
        logger.warning("get_canonical_nodes() error: %s", exc)
        return []


# ===========================================================================
# Boundary snapshot
# ===========================================================================

def build_node_boundary_snapshot(fabric_registry: Any = None) -> NodeBoundarySnapshot:
    """Build a diagnostic snapshot of node boundary compliance.

    Evaluates all registered nodes against the canonical boundary rules and
    returns a :class:`NodeBoundarySnapshot` with per-node decisions and
    counts.

    Parameters
    ----------
    fabric_registry:
        A :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` instance.
        When ``None``, attempts to import the module-level singleton.

    Returns
    -------
    NodeBoundarySnapshot
    """
    registry = fabric_registry
    if registry is None:
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            registry = get_node_fabric_registry()
        except ImportError:
            logger.warning(
                "NodeFabricRegistry unavailable — returning empty snapshot"
            )
            return NodeBoundarySnapshot(
                legacy_surfaces=build_legacy_surface_registry(),
            )

    try:
        all_nodes = registry.list_nodes()
    except Exception as exc:
        logger.warning("build_node_boundary_snapshot list_nodes() error: %s", exc)
        all_nodes = []

    decisions: List[NodeBoundaryDecision] = []
    canonical_count = 0
    legacy_count = 0
    violation_count = 0

    for node in all_nodes:
        decision = evaluate_node_boundary_compliance(node)
        decisions.append(decision)
        if decision.is_canonical:
            canonical_count += 1
        else:
            legacy_count += 1
        if decision.boundary_violations:
            violation_count += 1

    return NodeBoundarySnapshot(
        total_nodes=len(all_nodes),
        canonical_nodes=canonical_count,
        legacy_nodes=legacy_count,
        violation_nodes=violation_count,
        node_decisions=decisions,
        legacy_surfaces=build_legacy_surface_registry(),
    )


# ===========================================================================
# Summary helper (for /health and status surfaces)
# ===========================================================================

def get_boundary_summary(fabric_registry: Any = None) -> Dict[str, Any]:
    """Return a compact boundary compliance summary dict.

    Suitable for ``/health`` endpoints and dashboard status surfaces.

    Parameters
    ----------
    fabric_registry:
        Optional :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`.

    Returns
    -------
    dict with keys:
        - ``total_nodes`` — total evaluated nodes
        - ``canonical_nodes`` — nodes on the canonical path
        - ``legacy_nodes`` — nodes demoted to legacy/compat
        - ``violation_nodes`` — nodes with explicit boundary violations
        - ``legacy_surface_count`` — number of registered legacy surfaces
        - ``boundary_health`` — ``"clean"`` / ``"violations_detected"``
        - ``pr8_sentinel`` — :data:`NODE_BOUNDARY_RUNTIME_PR8_SENTINEL`
    """
    snapshot = build_node_boundary_snapshot(fabric_registry=fabric_registry)
    boundary_health = (
        "violations_detected" if snapshot.violation_nodes > 0 else "clean"
    )
    return {
        "total_nodes": snapshot.total_nodes,
        "canonical_nodes": snapshot.canonical_nodes,
        "legacy_nodes": snapshot.legacy_nodes,
        "violation_nodes": snapshot.violation_nodes,
        "legacy_surface_count": len(snapshot.legacy_surfaces),
        "boundary_health": boundary_health,
        "pr8_sentinel": NODE_BOUNDARY_RUNTIME_PR8_SENTINEL,
    }
