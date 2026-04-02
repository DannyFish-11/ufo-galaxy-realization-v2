#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/projection_surface_bridge.py
===================================
PR-511: Projection Stack Convergence / Surface Bridge.

This module is the **minimal bridge** that connects the two major
runtime/surface stacks operating in the Galaxy system:

Stack A — production projection/status stack
  - ContinuumState
  - TopologyRoutePlan
  - RuntimeProjection / DesktopStatusProjection
  - status_board_v2 / desktop_projection surfaces

Stack B — canonical runtime / operator stack
  - CanonicalTask / TaskGraphRuntime
  - NetworkTopologyRuntime / CapabilityAssimilation
  - ReplayFoundation / OperatorSurface

The bridge is **non-disruptive**: it does not replace or rewrite either
stack.  It defines boundary semantics and provides read-only enrichment
helpers that allow runtime inspection data to augment current production
surfaces without changing projection contracts.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  STACK A — PROJECTION STACK                                     │
    │  ContinuumState → TopologyRoutePlan → RuntimeProjection         │
    │  DesktopStatusProjection → status_board_v2 / desktop surfaces   │
    └──────────────────────────┬───────────────────────────────────────┘
                               │  PROJECTION-DERIVED (read-only)
                               ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  PROJECTION SURFACE BRIDGE  (this module, Layer 11)             │
    │  enrich_runtime_projection()                                     │
    │  build_bridge_snapshot()                                         │
    └──────────┬────────────────────────────────────┬─────────────────┘
               │  RUNTIME-AUGMENTED (read-only)      │
               ▼                                     ▼
    ┌──────────────────────┐          ┌───────────────────────────────┐
    │  STACK B RUNTIME     │          │  BRIDGE SNAPSHOT              │
    │  OperatorSurface     │          │  ProjectionBridgeSnapshot     │
    │  TaskGraphRuntime    │          │  (combined, non-destructive)  │
    │  NetworkTopology     │          └───────────────────────────────┘
    │  CapabilityLayer     │
    └──────────────────────┘

Governance invariants
---------------------
1.  **Bridge is read-only on both sides.**
    The bridge reads from Stack A projections and Stack B operator
    surface projections.  It MUST NOT write to either.
    Governed by :data:`SURFACE_BRIDGE_CONVERGENCE_POLICY`.

2.  **Projection layers remain projection-driven.**
    RuntimeProjection / DesktopStatusProjection continue to be assembled
    from ContinuumState + TopologyRoutePlan.  The bridge enriches on top.
    Governed by :data:`PROJECTION_DERIVED_BOUNDARY`.

3.  **Runtime/operator inspection layers remain read-only and runtime-driven.**
    OperatorSurface remains the sole read authority for canonical runtime
    state.  The bridge consumes OperatorSurface, not raw subsystems.
    Governed by :data:`RUNTIME_AUGMENTED_BOUNDARY`.

4.  **Topology semantics are distinct across three domains.**
    "topology" means different things in different parts of the system.
    Governed by :data:`TOPOLOGY_SEMANTICS_THREE_DOMAINS`.

5.  **No new parallel truth source.**
    The bridge snapshot is a derived/enriched view, not an additional
    truth authority.  It must not be treated as a primary state source.
    Governed by :data:`NO_NEW_TRUTH_SOURCE_POLICY`.

6.  **Graceful degradation.**
    If either stack is unavailable, the bridge returns a minimal valid
    snapshot rather than raising.

Public API
----------
Authority sentinels::

    PROJECTION_SURFACE_BRIDGE_AUTHORITY
    PROJECTION_SURFACE_BRIDGE_LAYER_POSITION
    PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION
    SURFACE_BRIDGE_CONVERGENCE_POLICY

Topology semantics sentinels::

    TOPOLOGY_SEMANTICS_THREE_DOMAINS
    MODEL_PROVIDER_TOPOLOGY_DOMAIN
    DEVICE_NETWORK_TOPOLOGY_DOMAIN
    TASK_GRAPH_TOPOLOGY_DOMAIN

Bridge boundary sentinels::

    PROJECTION_DERIVED_BOUNDARY
    RUNTIME_AUGMENTED_BOUNDARY
    NO_NEW_TRUTH_SOURCE_POLICY

Dataclasses::

    RuntimeAugmentation
    ProjectionBridgeSnapshot

Functions::

    enrich_runtime_projection(projection_dict) -> dict
    build_bridge_snapshot() -> ProjectionBridgeSnapshot
    get_runtime_augmentation() -> RuntimeAugmentation
    get_projection_surface_bridge() -> ProjectionSurfaceBridge
    reset_projection_surface_bridge() -> None
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ProjectionSurfaceBridge")

__all__ = [
    # Authority sentinels
    "PROJECTION_SURFACE_BRIDGE_AUTHORITY",
    "PROJECTION_SURFACE_BRIDGE_LAYER_POSITION",
    "PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION",
    "SURFACE_BRIDGE_CONVERGENCE_POLICY",
    # Topology semantics sentinels
    "TOPOLOGY_SEMANTICS_THREE_DOMAINS",
    "MODEL_PROVIDER_TOPOLOGY_DOMAIN",
    "DEVICE_NETWORK_TOPOLOGY_DOMAIN",
    "TASK_GRAPH_TOPOLOGY_DOMAIN",
    # Bridge boundary sentinels
    "PROJECTION_DERIVED_BOUNDARY",
    "RUNTIME_AUGMENTED_BOUNDARY",
    "NO_NEW_TRUTH_SOURCE_POLICY",
    # Dataclasses
    "RuntimeAugmentation",
    "ProjectionBridgeSnapshot",
    # Functions
    "enrich_runtime_projection",
    "build_bridge_snapshot",
    "get_runtime_augmentation",
    "get_projection_surface_bridge",
    "reset_projection_surface_bridge",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

PROJECTION_SURFACE_BRIDGE_AUTHORITY: str = (
    "PROJECTION_SURFACE_BRIDGE_V1 | PR-511 | "
    "Minimal non-disruptive bridge between production projection stack "
    "and canonical runtime/operator stack."
)
"""Sentinel: this module is the canonical projection/runtime bridge authority."""

PROJECTION_SURFACE_BRIDGE_LAYER_POSITION: int = 11
"""Layer position in the Galaxy architecture stack.

The bridge sits at layer 11, above OperatorSurface (layer 10), because it
consumes OperatorSurface projections and decorates them with projection-stack
context.  It does not replace either stack."""

PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION: str = "1.0"
"""Version of the ProjectionSurfaceBridge contract."""

SURFACE_BRIDGE_CONVERGENCE_POLICY: str = (
    "SURFACE_BRIDGE_CONVERGENCE_POLICY_V1: "
    "The bridge is read-only on both stacks. "
    "Projection layers remain projection-driven (ContinuumState + TopologyRoutePlan). "
    "Runtime layers remain read-only and runtime-driven (OperatorSurface). "
    "The bridge enriches surfaces non-destructively — it must not mutate either stack."
)
"""Policy governing bridge behaviour between the two stacks."""

# ---------------------------------------------------------------------------
# Topology semantics disambiguation sentinels
# ---------------------------------------------------------------------------

TOPOLOGY_SEMANTICS_THREE_DOMAINS: str = (
    "TOPOLOGY_SEMANTICS_THREE_DOMAINS_V1: "
    "The word 'topology' covers three distinct domains in this system. "
    "1. MODEL/PROVIDER TOPOLOGY — model node graph, weights, route plan "
    "(TopologyRoutePlan / RuntimeProjection / DesktopStatusProjection). "
    "2. DEVICE/NETWORK TOPOLOGY — physical/virtual device connectivity, "
    "NATS fabric, gateway paths (NetworkTopologyRuntime / CapabilityAssimilation). "
    "3. TASK GRAPH TOPOLOGY — task lineage, fanout/fanin, retry/fallback "
    "graph (TaskGraphRuntime). "
    "Code paths and docs MUST use the domain-qualified names (model_provider_topology, "
    "device_network_topology, task_graph_topology) to avoid ambiguity."
)
"""Sentinel: clarifies the three topology domains to avoid cross-domain confusion."""

MODEL_PROVIDER_TOPOLOGY_DOMAIN: str = (
    "MODEL_PROVIDER_TOPOLOGY_DOMAIN: "
    "The model/provider routing topology domain. "
    "Authority: TopologyRoutePlan, RuntimeProjection, DesktopStatusProjection. "
    "Stack: Stack A (projection stack). "
    "Concerns: model node weights, route selection, provider health, "
    "primary/support model IDs. "
    "NOT redesigned in PR-511 — this domain continues to be projection-driven."
)
"""Sentinel: model/provider topology domain definition and authority."""

DEVICE_NETWORK_TOPOLOGY_DOMAIN: str = (
    "DEVICE_NETWORK_TOPOLOGY_DOMAIN: "
    "The device/network connectivity topology domain. "
    "Authority: NetworkTopologyRuntime, CapabilityAssimilation, "
    "CapabilityNetworkRuntimePolicy (PR-509). "
    "Stack: Stack B (canonical runtime stack). "
    "Concerns: device presence, NATS fabric connectivity, gateway paths, "
    "transport strategy, executor routable state. "
    "Bridge: available via get_runtime_augmentation() for surface enrichment."
)
"""Sentinel: device/network topology domain definition and authority."""

TASK_GRAPH_TOPOLOGY_DOMAIN: str = (
    "TASK_GRAPH_TOPOLOGY_DOMAIN: "
    "The task execution graph topology domain. "
    "Authority: TaskGraphRuntime, CanonicalTask, ReplayFoundation. "
    "Stack: Stack B (canonical runtime stack). "
    "Concerns: task lineage, fanout/fanin graph, retry/fallback relations, "
    "task lifecycle state, task graph snapshot. "
    "Bridge: available via get_runtime_augmentation() for surface enrichment."
)
"""Sentinel: task graph topology domain definition and authority."""

# ---------------------------------------------------------------------------
# Bridge boundary sentinels
# ---------------------------------------------------------------------------

PROJECTION_DERIVED_BOUNDARY: str = (
    "PROJECTION_DERIVED_BOUNDARY_V1: "
    "The following information MUST continue to come exclusively from "
    "RuntimeProjection / DesktopStatusProjection (projection-derived): "
    "- tri_state_phase, runtime_domain, presence_intensity, coherence, "
    "  collapse_tendency, retreat_tendency (from ContinuumState). "
    "- primary_model_id, support_model_ids, active_weights, route_reason "
    "  (from TopologyRoutePlan — model/provider topology domain). "
    "- execution_stage, current_task_summary (projection-assembled). "
    "- topology_ready block (DesktopStatusProjection — model/provider topology). "
    "These fields are authoritative in Stack A and MUST NOT be overridden "
    "by runtime augmentation."
)
"""Sentinel: declares what information must remain projection-derived."""

RUNTIME_AUGMENTED_BOUNDARY: str = (
    "RUNTIME_AUGMENTED_BOUNDARY_V1: "
    "The following information CAN be augmented from operator/runtime "
    "inspection (runtime-augmented, Stack B enrichment): "
    "- active_task_count — from TaskGraphRuntime task graph snapshot. "
    "- active_device_ids — can be cross-validated from CapabilityAssimilation. "
    "- executor_count — from CapabilityAssimilation online node count. "
    "- network_reachability — from NetworkTopologyRuntime topology snapshot. "
    "- replay_event_count — from ReplayFoundation ring buffer depth. "
    "- task_graph_snapshot — from TaskGraphRuntime graph snapshot. "
    "- operator_snapshot — from OperatorSurface. "
    "Augmented fields are ADDITIVE to the projection dict and must never "
    "replace or shadow projection-derived fields."
)
"""Sentinel: declares what information can be augmented from runtime inspection."""

NO_NEW_TRUTH_SOURCE_POLICY: str = (
    "NO_NEW_TRUTH_SOURCE_POLICY_V1: "
    "ProjectionBridgeSnapshot is a derived/enriched view, NOT a truth authority. "
    "It must not be used as a primary state source or stored as canonical truth. "
    "Downstream consumers must continue to read from their respective canonical "
    "sources: projection stack for model/routing truth; operator surface for "
    "runtime truth. The bridge snapshot is informational only."
)
"""Policy: no new parallel truth source is introduced by the bridge."""

# ---------------------------------------------------------------------------
# RuntimeAugmentation dataclass
# ---------------------------------------------------------------------------


@dataclass
class RuntimeAugmentation:
    """Read-only runtime-derived data from Stack B for surface enrichment.

    Fields
    ------
    active_task_count
        Number of tasks currently registered in TaskGraphRuntime.
        0 when TaskGraphRuntime is unavailable or empty.
    executor_count
        Number of online executor nodes from CapabilityAssimilation.
        0 when CapabilityAssimilation is unavailable or empty.
    network_reachable_node_count
        Count of reachable topology nodes from NetworkTopologyRuntime.
        0 when NetworkTopologyRuntime is unavailable or empty.
    replay_event_count
        Number of replay events in the ReplayFoundation ring buffer.
        0 when ReplayFoundation is unavailable.
    operator_snapshot_dict
        The OperatorSnapshot as a dict, or None when OperatorSurface is unavailable.
    task_graph_snapshot_dict
        The TaskGraphRuntime snapshot as a dict (subset), or None when unavailable.
    augmented_at
        Unix epoch seconds when this augmentation was assembled.
    _source
        Provenance sentinel — always includes PROJECTION_SURFACE_BRIDGE_AUTHORITY.
    """

    active_task_count: int = 0
    executor_count: int = 0
    network_reachable_node_count: int = 0
    replay_event_count: int = 0
    operator_snapshot_dict: Optional[Dict[str, Any]] = None
    task_graph_snapshot_dict: Optional[Dict[str, Any]] = None
    augmented_at: float = field(default_factory=time.time)
    _source: str = field(default=PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "active_task_count": self.active_task_count,
            "executor_count": self.executor_count,
            "network_reachable_node_count": self.network_reachable_node_count,
            "replay_event_count": self.replay_event_count,
            "operator_snapshot_dict": self.operator_snapshot_dict,
            "task_graph_snapshot_dict": self.task_graph_snapshot_dict,
            "augmented_at": self.augmented_at,
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# ProjectionBridgeSnapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProjectionBridgeSnapshot:
    """Combined snapshot bridging Stack A projection data and Stack B runtime data.

    This snapshot is **informational only** — see :data:`NO_NEW_TRUTH_SOURCE_POLICY`.
    It is a non-destructive enrichment of the current projection state with
    runtime inspection data.

    Fields
    ------
    snapshot_id
        Unique identifier for this snapshot instance.
    projection_dict
        The current RuntimeProjection as a dict (from Stack A).
        May be None when the projection stack is unavailable.
    runtime_augmentation
        The runtime-derived augmentation data from Stack B.
    model_provider_topology_domain
        Constant referencing :data:`MODEL_PROVIDER_TOPOLOGY_DOMAIN` for
        downstream consumers to verify topology semantics.
    device_network_topology_domain
        Constant referencing :data:`DEVICE_NETWORK_TOPOLOGY_DOMAIN`.
    task_graph_topology_domain
        Constant referencing :data:`TASK_GRAPH_TOPOLOGY_DOMAIN`.
    projection_derived_fields
        List of field names that are exclusively projection-derived
        (per :data:`PROJECTION_DERIVED_BOUNDARY`).
    runtime_augmented_fields
        List of field names that are runtime-augmented
        (per :data:`RUNTIME_AUGMENTED_BOUNDARY`).
    bridge_authority
        Always :data:`PROJECTION_SURFACE_BRIDGE_AUTHORITY`.
    assembled_at
        Unix epoch seconds when this snapshot was assembled.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"psb_{uuid.uuid4().hex[:12]}"
    )
    projection_dict: Optional[Dict[str, Any]] = None
    runtime_augmentation: RuntimeAugmentation = field(
        default_factory=RuntimeAugmentation
    )
    model_provider_topology_domain: str = field(
        default=MODEL_PROVIDER_TOPOLOGY_DOMAIN
    )
    device_network_topology_domain: str = field(
        default=DEVICE_NETWORK_TOPOLOGY_DOMAIN
    )
    task_graph_topology_domain: str = field(
        default=TASK_GRAPH_TOPOLOGY_DOMAIN
    )
    projection_derived_fields: List[str] = field(default_factory=lambda: [
        "tri_state_phase",
        "runtime_domain",
        "presence_intensity",
        "coherence",
        "collapse_tendency",
        "retreat_tendency",
        "primary_model_id",
        "support_model_ids",
        "active_weights",
        "route_reason",
        "execution_stage",
        "current_task_summary",
        "topology_ready",
    ])
    runtime_augmented_fields: List[str] = field(default_factory=lambda: [
        "active_task_count",
        "executor_count",
        "network_reachable_node_count",
        "replay_event_count",
        "operator_snapshot_dict",
        "task_graph_snapshot_dict",
    ])
    bridge_authority: str = field(default=PROJECTION_SURFACE_BRIDGE_AUTHORITY)
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation of the bridge snapshot."""
        return {
            "snapshot_id": self.snapshot_id,
            "projection_dict": self.projection_dict,
            "runtime_augmentation": self.runtime_augmentation.to_dict(),
            "model_provider_topology_domain": self.model_provider_topology_domain,
            "device_network_topology_domain": self.device_network_topology_domain,
            "task_graph_topology_domain": self.task_graph_topology_domain,
            "projection_derived_fields": list(self.projection_derived_fields),
            "runtime_augmented_fields": list(self.runtime_augmented_fields),
            "bridge_authority": self.bridge_authority,
            "assembled_at": self.assembled_at,
        }

    def get_enriched_projection(self) -> Dict[str, Any]:
        """Return a copy of the projection dict enriched with runtime augmentation.

        The returned dict contains all projection-derived keys from
        :attr:`projection_dict` **plus** the runtime-augmented keys from
        :attr:`runtime_augmentation`.  Projection-derived keys are never
        shadowed by runtime augmentation.

        Returns an empty dict when no projection is available.
        """
        base: Dict[str, Any] = dict(self.projection_dict) if self.projection_dict else {}
        augmentation = self.runtime_augmentation.to_dict()
        for key in self.runtime_augmented_fields:
            if key not in base:
                base[key] = augmentation.get(key)
        base["_bridge_authority"] = self.bridge_authority
        base["_bridge_snapshot_id"] = self.snapshot_id
        return base


# ---------------------------------------------------------------------------
# ProjectionSurfaceBridge class
# ---------------------------------------------------------------------------


class ProjectionSurfaceBridge:
    """Minimal bridge connecting Stack A projections and Stack B runtime layers.

    This class is the singleton bridge authority.  It provides:

    - :meth:`get_runtime_augmentation` — reads from Stack B (OperatorSurface,
      TaskGraphRuntime, CapabilityAssimilation, NetworkTopologyRuntime,
      ReplayFoundation) and returns a :class:`RuntimeAugmentation`.
    - :meth:`enrich_runtime_projection` — non-destructively enriches a
      projection dict with runtime augmentation data.
    - :meth:`build_bridge_snapshot` — assembles a full
      :class:`ProjectionBridgeSnapshot`.

    Design invariants
    -----------------
    1.  **Read-only on both stacks.**
    2.  **Non-destructive enrichment.**  Projection-derived fields are never
        overwritten by runtime data.
    3.  **Graceful degradation.**  Unavailable stack layers produce empty
        defaults rather than raising.
    4.  **No truth authority.**  The bridge snapshot is informational only.
    """

    def get_runtime_augmentation(self) -> RuntimeAugmentation:
        """Assemble a :class:`RuntimeAugmentation` from Stack B canonical layers.

        Reads from (in order):
        - TaskGraphRuntime — active task count + task graph snapshot
        - CapabilityAssimilation — online executor count
        - NetworkTopologyRuntime — reachable node count
        - ReplayFoundation — replay event count
        - OperatorSurface — operator snapshot

        Returns a default :class:`RuntimeAugmentation` with zero counts if
        all layers are unavailable.
        """
        active_task_count = 0
        executor_count = 0
        network_reachable_node_count = 0
        replay_event_count = 0
        operator_snapshot_dict: Optional[Dict[str, Any]] = None
        task_graph_snapshot_dict: Optional[Dict[str, Any]] = None

        # TaskGraphRuntime — active task count
        try:
            from core.task_graph_runtime import get_task_graph_runtime
            tgr = get_task_graph_runtime()
            snap = tgr.snapshot()
            active_task_count = snap.total_nodes
            task_graph_snapshot_dict = {
                "total_nodes": snap.total_nodes,
                "total_edges": snap.total_edges,
                "by_state": {k: v for k, v in snap.by_state.items()},
            }
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("ProjectionSurfaceBridge: TaskGraphRuntime unavailable: %s", exc)

        # CapabilityAssimilation — online executor count
        try:
            from core.capability_assimilation import get_capability_assimilation_layer
            cal = get_capability_assimilation_layer()
            snap = cal.snapshot()
            executor_count = snap.online_count
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("ProjectionSurfaceBridge: CapabilityAssimilation unavailable: %s", exc)

        # NetworkTopologyRuntime — reachable node count
        try:
            from core.network_topology_runtime import get_network_topology_runtime
            ntr = get_network_topology_runtime()
            topo_snap = ntr.snapshot()
            network_reachable_node_count = sum(
                1 for n in topo_snap.nodes
                if getattr(n, "state", None) is not None
                and getattr(n.state, "value", "") in ("reachable", "connected", "preferred")
            )
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug(
                "ProjectionSurfaceBridge: NetworkTopologyRuntime unavailable: %s", exc
            )

        # ReplayFoundation — event count
        try:
            from core.replay_foundation import get_replay_foundation
            rf = get_replay_foundation()
            rf_snap = rf.snapshot()
            replay_event_count = len(rf_snap.runtime_events)
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("ProjectionSurfaceBridge: ReplayFoundation unavailable: %s", exc)

        # OperatorSurface — operator snapshot
        try:
            from core.operator_surface import get_operator_surface
            os_ = get_operator_surface()
            op_snap = os_.operator_snapshot()
            operator_snapshot_dict = op_snap.to_dict()
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("ProjectionSurfaceBridge: OperatorSurface unavailable: %s", exc)

        return RuntimeAugmentation(
            active_task_count=active_task_count,
            executor_count=executor_count,
            network_reachable_node_count=network_reachable_node_count,
            replay_event_count=replay_event_count,
            operator_snapshot_dict=operator_snapshot_dict,
            task_graph_snapshot_dict=task_graph_snapshot_dict,
        )

    def enrich_runtime_projection(
        self,
        projection_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return a **copy** of *projection_dict* enriched with runtime data.

        Projection-derived fields (per :data:`PROJECTION_DERIVED_BOUNDARY`)
        are never overwritten.  Only the runtime-augmented fields
        (per :data:`RUNTIME_AUGMENTED_BOUNDARY`) are added.

        Parameters
        ----------
        projection_dict:
            A dict representation of a RuntimeProjection or
            DesktopStatusProjection (as returned by ``.to_dict()``).

        Returns
        -------
        dict
            A new dict that is a copy of *projection_dict* with runtime
            augmentation fields added.  The original *projection_dict* is
            not mutated.
        """
        augmentation = self.get_runtime_augmentation()
        enriched = dict(projection_dict)
        aug_dict = augmentation.to_dict()
        # Only add augmented fields if not already present in projection
        for key in [
            "active_task_count",
            "executor_count",
            "network_reachable_node_count",
            "replay_event_count",
            "operator_snapshot_dict",
            "task_graph_snapshot_dict",
        ]:
            if key not in enriched:
                enriched[key] = aug_dict.get(key)
        enriched["_bridge_authority"] = PROJECTION_SURFACE_BRIDGE_AUTHORITY
        return enriched

    def build_bridge_snapshot(
        self,
        projection_dict: Optional[Dict[str, Any]] = None,
    ) -> ProjectionBridgeSnapshot:
        """Assemble a :class:`ProjectionBridgeSnapshot`.

        Reads the current RuntimeProjection from Stack A (if not provided
        explicitly) and the runtime augmentation from Stack B, then
        combines them into a bridge snapshot.

        Parameters
        ----------
        projection_dict:
            Optional pre-assembled projection dict.  When omitted, the bridge
            attempts to read the current RuntimeProjection from the projection
            compiler.

        Returns
        -------
        ProjectionBridgeSnapshot
            A snapshot combining projection data and runtime augmentation.
            Projection-derived fields are authoritative.
        """
        if projection_dict is None:
            projection_dict = self._read_current_projection()

        augmentation = self.get_runtime_augmentation()
        return ProjectionBridgeSnapshot(
            projection_dict=projection_dict,
            runtime_augmentation=augmentation,
        )

    def _read_current_projection(self) -> Optional[Dict[str, Any]]:
        """Attempt to read the current RuntimeProjection from Stack A.

        Returns a dict or None if the projection stack is unavailable.
        """
        try:
            from core.projection.projection_compiler import build_runtime_projection
            from core.continuum.types import ContinuumState
            # Build a minimal default projection when no live continuum state
            # is readily accessible at this layer.  Real surfaces should pass
            # their own projection_dict.
            dummy = ContinuumState()
            proj = build_runtime_projection(dummy)
            return proj.to_dict()
        except (ImportError, AttributeError) as exc:
            logger.debug(
                "ProjectionSurfaceBridge: could not read current projection: %s", exc
            )
            return None


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_BRIDGE_INSTANCE: Optional[ProjectionSurfaceBridge] = None


def get_projection_surface_bridge() -> ProjectionSurfaceBridge:
    """Return the singleton :class:`ProjectionSurfaceBridge`.

    Creates the instance on first access.
    """
    global _BRIDGE_INSTANCE
    if _BRIDGE_INSTANCE is None:
        _BRIDGE_INSTANCE = ProjectionSurfaceBridge()
    return _BRIDGE_INSTANCE


def reset_projection_surface_bridge() -> None:
    """Reset the singleton bridge instance.

    Intended for use in tests only.  Do not call in production code.
    """
    global _BRIDGE_INSTANCE
    _BRIDGE_INSTANCE = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def get_runtime_augmentation() -> RuntimeAugmentation:
    """Convenience wrapper around :meth:`ProjectionSurfaceBridge.get_runtime_augmentation`."""
    return get_projection_surface_bridge().get_runtime_augmentation()


def enrich_runtime_projection(projection_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience wrapper around :meth:`ProjectionSurfaceBridge.enrich_runtime_projection`.

    Returns a new dict that is a copy of *projection_dict* with runtime
    augmentation fields added without mutating the input.
    """
    return get_projection_surface_bridge().enrich_runtime_projection(projection_dict)


def build_bridge_snapshot(
    projection_dict: Optional[Dict[str, Any]] = None,
) -> ProjectionBridgeSnapshot:
    """Convenience wrapper around :meth:`ProjectionSurfaceBridge.build_bridge_snapshot`."""
    return get_projection_surface_bridge().build_bridge_snapshot(projection_dict)
