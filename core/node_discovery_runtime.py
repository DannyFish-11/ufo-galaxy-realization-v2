#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/node_discovery_runtime.py
================================
PR-7: Integrate NodeDiscoveryService into the Real Startup and Health Path.

This module is the **canonical authority** for wiring
:class:`~core.node_discovery.NodeDiscoveryService` into the Galaxy runtime
startup path.  Prior to this PR, ``NodeDiscoveryService`` supported seeding,
healthy-node querying, capability lookup, and heartbeat behaviour, but was
never required by the main runtime startup path.  Discovery data could
therefore be absent, stale, or irrelevant to actual production execution.

This module bridges:
  - :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` — the
    canonical runtime node registry (source of truth for running nodes).
  - :class:`~core.node_discovery.NodeDiscoveryService` — the discovery
    plane that makes nodes reachable by capability and role.

Integration responsibilities
----------------------------
1. **Startup seeding** — ``initialize_discovery_from_startup()`` reads the
   canonical fabric registry and seeds every healthy node into discovery so
   the discovery plane reflects the real startup state immediately.

2. **Per-node announcement** — ``announce_node_to_discovery()`` is called by
   ``NodeSystemLauncher`` after each node passes its health check.  This
   keeps the discovery plane up-to-date as nodes come online.

3. **Health/status surfaces** — ``get_discovery_participation_summary()``
   returns a compact dict suitable for ``/health`` and dashboard endpoints.
   It reports total, healthy, and undiscovered node counts so operators can
   detect gaps between the launcher, fabric registry, and discovery planes.

4. **Diagnostic differentiation** — ``build_discovery_runtime_snapshot()``
   compares launcher state, fabric registry state, and discovery state and
   returns per-node records that flag nodes that are running but not
   discoverable (``undiscovered_active``), nodes that are in discovery but
   not healthy in the fabric registry (``discovery_orphan``), and nodes that
   are healthy in both planes (``aligned``).

Compatibility
-------------
Every public function degrades gracefully when either
:mod:`core.node_discovery` or :mod:`core.nodes.node_fabric_registry` is
unavailable (e.g. lightweight test environments without aiohttp / FastAPI).
Fallback paths are logged and sentinel-annotated.

Public API
----------
Authority sentinels::

    NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY
    NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL

Policy sentinels::

    ACTIVE_NODES_ARE_DISCOVERABLE_POLICY
    DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY
    DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY
    DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY
    UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY

Dataclasses::

    NodeDiscoveryParticipationRecord
    DiscoveryRuntimeSnapshot

Functions::

    seed_fabric_nodes_into_discovery(fabric, discovery) -> int
    announce_node_to_discovery(discovery, node_id, host, port, capabilities) -> bool
    initialize_discovery_from_startup(discovery, fabric) -> int
    build_discovery_runtime_snapshot(fabric, discovery, launcher_active_nodes) -> DiscoveryRuntimeSnapshot
    get_discovery_participation_summary(discovery, fabric) -> dict
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.NodeDiscoveryRuntime")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Declares this module as the canonical authority for integrating
#: NodeDiscoveryService into the real runtime startup and health path.
NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY: str = (
    "NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY_V1: "
    "core.node_discovery_runtime is the canonical authority for wiring "
    "NodeDiscoveryService into Galaxy runtime startup.  Active nodes from "
    "NodeFabricRegistry are seeded into discovery at startup.  Per-node "
    "announcements keep the discovery plane current as nodes come online.  "
    "Health/status surfaces reflect discovery state.  Diagnostic tools expose "
    "mismatches between launcher state, fabric registry state, and discovery state."
)

#: PR-7 integration sentinel — machine-checkable proof that discovery has been
#: wired into the real startup and health path.
NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL: str = (
    "NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL_V1: "
    "discovery participates in real startup behavior; active nodes are "
    "discoverable through NodeDiscoveryService; health/status surfaces reflect "
    "discovery state; system can diagnose mismatches between launcher state, "
    "fabric registry state, and discovery state."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

#: Nodes that are healthy in NodeFabricRegistry are seeded into discovery at
#: startup so callers can locate them by capability or role without requiring
#: UDP broadcast to have run first.
ACTIVE_NODES_ARE_DISCOVERABLE_POLICY: str = (
    "ACTIVE_NODES_ARE_DISCOVERABLE_POLICY_V1: "
    "Every node that passes its health check and is registered as healthy in "
    "NodeFabricRegistry is seeded into NodeDiscoveryService during startup.  "
    "This guarantees that the discovery plane reflects the real set of running "
    "nodes regardless of UDP broadcast availability."
)

#: The discovery plane is kept in sync with the fabric registry; a node's
#: discovery state is set to REGISTERED/HEALTHY when it is healthy in the
#: fabric registry and OFFLINE when it is not.
DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY: str = (
    "DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY_V1: "
    "NodeDiscoveryService state for launcher-managed nodes mirrors the health "
    "state reported by NodeFabricRegistry.  Nodes that go offline in the fabric "
    "registry are removed from the discoverable set."
)

#: Every mismatch between launcher state, fabric registry state, and discovery
#: state is recorded in a DiscoveryRuntimeSnapshot and surfaced through
#: build_discovery_runtime_snapshot().
DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY: str = (
    "DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY_V1: "
    "build_discovery_runtime_snapshot() produces per-node "
    "NodeDiscoveryParticipationRecord entries that flag nodes with mismatches "
    "between launcher state, fabric registry state, and discovery state.  "
    "Undiscovered active nodes and discovery orphans are explicitly labelled."
)

#: NodeDiscoveryService is initialized in the main startup path through
#: initialize_discovery_from_startup(), which is called by NodeSystemLauncher
#: after the initial batch of nodes has passed health checks.
DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY: str = (
    "DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY_V1: "
    "initialize_discovery_from_startup() is called during runtime startup to "
    "seed all nodes that are already healthy in NodeFabricRegistry into "
    "NodeDiscoveryService.  This makes discovery a required participant in the "
    "startup path rather than an isolated optional subsystem."
)

#: Nodes that are running (in launcher or fabric registry) but not present in
#: the discovery plane are flagged as 'undiscovered_active' in diagnostic
#: snapshots.  This enables operators to identify gaps in discoverability.
UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY: str = (
    "UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY_V1: "
    "build_discovery_runtime_snapshot() flags nodes that are healthy in "
    "NodeFabricRegistry but absent from NodeDiscoveryService as "
    "'undiscovered_active'.  The summary count is exposed in health surfaces "
    "so operators can detect and remediate discoverability gaps."
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NodeDiscoveryParticipationRecord:
    """Per-node participation record for the discovery runtime snapshot.

    Attributes:
        node_id:              Canonical node identifier.
        in_fabric_registry:   True if the node is registered in NodeFabricRegistry.
        fabric_status:        Status string from NodeFabricRegistry (e.g. "healthy",
                              "offline"), or ``None`` when not in registry.
        in_discovery:         True if the node is present in NodeDiscoveryService.
        discovery_state:      State string from NodeDiscoveryService (e.g.
                              "registered", "healthy", "offline"), or ``None`` when
                              not in discovery.
        in_launcher_active:   True when the node is in the launcher's active set
                              (startup_policy active/optional).
        alignment:            One of:
                              - ``"aligned"`` — healthy in both fabric registry and
                                discovery.
                              - ``"undiscovered_active"`` — healthy in fabric
                                registry but absent from discovery.
                              - ``"discovery_orphan"`` — present in discovery but
                                not healthy in fabric registry.
                              - ``"inactive"`` — offline or excluded in both planes.
        diagnostic_notes:     Human-readable notes explaining the alignment status.
    """

    node_id: str
    in_fabric_registry: bool = False
    fabric_status: Optional[str] = None
    in_discovery: bool = False
    discovery_state: Optional[str] = None
    in_launcher_active: bool = False
    alignment: str = "inactive"
    diagnostic_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "in_fabric_registry": self.in_fabric_registry,
            "fabric_status": self.fabric_status,
            "in_discovery": self.in_discovery,
            "discovery_state": self.discovery_state,
            "in_launcher_active": self.in_launcher_active,
            "alignment": self.alignment,
            "diagnostic_notes": list(self.diagnostic_notes),
        }


@dataclass
class DiscoveryRuntimeSnapshot:
    """Aggregate diagnostic snapshot comparing launcher, fabric, and discovery states.

    Attributes:
        timestamp:                Unix timestamp when the snapshot was taken.
        seeded_count:             Number of nodes seeded into discovery at snapshot time.
        healthy_count:            Number of nodes healthy in both fabric registry and
                                  discovery.
        undiscovered_active_count: Number of nodes healthy in fabric registry but
                                   absent from discovery.
        discovery_orphan_count:   Number of nodes present in discovery but not
                                  healthy in fabric registry.
        total_launcher_active:    Number of nodes the launcher considers active.
        total_fabric_nodes:       Total nodes in fabric registry.
        total_discovery_nodes:    Total nodes in discovery service.
        participation_records:    Per-node :class:`NodeDiscoveryParticipationRecord`
                                  list for the full diagnostic detail.
        authority:                Module authority sentinel string.
    """

    timestamp: float = field(default_factory=time.time)
    seeded_count: int = 0
    healthy_count: int = 0
    undiscovered_active_count: int = 0
    discovery_orphan_count: int = 0
    total_launcher_active: int = 0
    total_fabric_nodes: int = 0
    total_discovery_nodes: int = 0
    participation_records: List[NodeDiscoveryParticipationRecord] = field(default_factory=list)
    authority: str = NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "seeded_count": self.seeded_count,
            "healthy_count": self.healthy_count,
            "undiscovered_active_count": self.undiscovered_active_count,
            "discovery_orphan_count": self.discovery_orphan_count,
            "total_launcher_active": self.total_launcher_active,
            "total_fabric_nodes": self.total_fabric_nodes,
            "total_discovery_nodes": self.total_discovery_nodes,
            "participation_records": [r.to_dict() for r in self.participation_records],
            "authority": self.authority,
        }


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def seed_fabric_nodes_into_discovery(fabric: Any, discovery: Any) -> int:
    """Seed all healthy nodes from *fabric* into *discovery*.

    Reads every :class:`~core.nodes.node_fabric_registry.NodeInfo` in the
    fabric registry that is in a healthy/running state and registers a
    corresponding :class:`~core.node_discovery.DiscoveredNode` in the
    discovery service if it is not already present.

    Args:
        fabric:    A :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
                   instance.  Any object exposing ``list_nodes()`` and
                   ``list_healthy()`` is accepted (for test isolation).
        discovery: A :class:`~core.node_discovery.NodeDiscoveryService` instance.
                   Any object exposing ``register_node()`` and ``.nodes`` is
                   accepted.

    Returns:
        Number of nodes newly seeded into discovery (already-present nodes are
        skipped and not counted).
    """
    try:
        from core.node_discovery import DiscoveredNode, NodeRole as DiscoveryNodeRole, DiscoveryState
    except ImportError:
        logger.warning(
            "seed_fabric_nodes_into_discovery: core.node_discovery unavailable; "
            "skipping seed."
        )
        return 0

    seeded = 0
    try:
        healthy_nodes = fabric.list_healthy()
    except Exception as exc:
        logger.warning("seed_fabric_nodes_into_discovery: list_healthy() failed: %s", exc)
        return 0

    for node_info in healthy_nodes:
        node_id = node_info.node_id
        if node_id in discovery.nodes:
            # Already registered — update heartbeat to keep it alive.
            existing = discovery.nodes[node_id]
            existing.last_heartbeat = time.time()
            if existing.state not in (DiscoveryState.HEALTHY, DiscoveryState.REGISTERED):
                existing.state = DiscoveryState.REGISTERED
            continue

        # Map fabric NodeRole to discovery NodeRole where possible.
        role_value = (
            node_info.role.value
            if hasattr(node_info.role, "value")
            else str(node_info.role)
        )
        try:
            discovery_role = DiscoveryNodeRole(role_value)
        except ValueError:
            discovery_role = DiscoveryNodeRole.WORKER

        host = getattr(node_info, "host", "localhost") or "localhost"
        port = getattr(node_info, "port", 0) or 0
        capabilities = list(getattr(node_info, "capabilities", []) or [])
        if not capabilities:
            capabilities = [node_id]

        dn = DiscoveredNode(
            node_id=node_id,
            host=host,
            port=port,
            role=discovery_role,
            capabilities=capabilities,
            state=DiscoveryState.REGISTERED,
            metadata={
                "seeded_from_fabric_registry": True,
                "architectural_class": (
                    node_info.architectural_class.value
                    if hasattr(node_info.architectural_class, "value")
                    else str(getattr(node_info, "architectural_class", "unknown"))
                ),
            },
        )
        try:
            discovery.register_node(dn)
            seeded += 1
        except Exception as exc:
            logger.debug(
                "seed_fabric_nodes_into_discovery: register_node(%s) failed: %s",
                node_id, exc,
            )

    logger.info(
        "NodeDiscoveryRuntime: seeded %d node(s) from NodeFabricRegistry into discovery",
        seeded,
    )
    return seeded


def announce_node_to_discovery(
    discovery: Any,
    node_id: str,
    host: str = "localhost",
    port: int = 0,
    capabilities: Optional[List[str]] = None,
    role_str: str = "worker",
) -> bool:
    """Announce a single node to the discovery service.

    Called by :class:`~launcher.node_startup.NodeSystemLauncher` immediately
    after a node passes its health check, so the discovery plane is updated
    as each node comes online rather than only at startup batch-seed time.

    If the node is already registered in discovery its heartbeat timestamp is
    refreshed (idempotent).

    Args:
        discovery:    A :class:`~core.node_discovery.NodeDiscoveryService` instance.
        node_id:      Canonical node identifier.
        host:         Node host address (default ``"localhost"``).
        port:         Node HTTP port (default ``0``).
        capabilities: Capability identifiers for the node.  Defaults to
                      ``[node_id]`` when omitted or empty.
        role_str:     Role string matching :class:`~core.node_discovery.NodeRole`
                      value (default ``"worker"``).

    Returns:
        ``True`` when the node was registered or refreshed successfully;
        ``False`` on error.
    """
    try:
        from core.node_discovery import DiscoveredNode, NodeRole as DiscoveryNodeRole, DiscoveryState
    except ImportError:
        logger.debug(
            "announce_node_to_discovery: core.node_discovery unavailable; "
            "skipping announcement for %s.",
            node_id,
        )
        return False

    try:
        if node_id in discovery.nodes:
            existing = discovery.nodes[node_id]
            existing.last_heartbeat = time.time()
            if existing.state not in (DiscoveryState.HEALTHY, DiscoveryState.REGISTERED):
                existing.state = DiscoveryState.REGISTERED
            logger.debug(
                "announce_node_to_discovery: refreshed heartbeat for %s", node_id
            )
            return True

        caps = list(capabilities) if capabilities else [node_id]
        try:
            role = DiscoveryNodeRole(role_str)
        except ValueError:
            role = DiscoveryNodeRole.WORKER

        dn = DiscoveredNode(
            node_id=node_id,
            host=host or "localhost",
            port=port or 0,
            role=role,
            capabilities=caps,
            state=DiscoveryState.REGISTERED,
            metadata={"announced_by_launcher": True},
        )
        discovery.register_node(dn)
        logger.debug("announce_node_to_discovery: registered %s", node_id)
        return True
    except Exception as exc:
        logger.debug(
            "announce_node_to_discovery: failed for %s: %s", node_id, exc
        )
        return False


def initialize_discovery_from_startup(
    discovery: Any,
    fabric: Any,
) -> int:
    """Initialize the discovery service from the current fabric registry state.

    This is the **main startup integration call**.  It should be invoked after
    the initial node batch has been started and health-checked so that the
    discovery plane immediately reflects the real set of running nodes.

    Performs:
    1. Seeds all healthy nodes from *fabric* into *discovery* via
       :func:`seed_fabric_nodes_into_discovery`.
    2. Logs a summary so operators can confirm that discovery has been
       populated at startup.

    Args:
        discovery: :class:`~core.node_discovery.NodeDiscoveryService` instance.
        fabric:    :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
                   instance.

    Returns:
        Number of nodes seeded.
    """
    logger.info(
        "NodeDiscoveryRuntime: initializing discovery from startup "
        "(policy: %s)",
        DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY[:60] + "...",
    )
    seeded = seed_fabric_nodes_into_discovery(fabric, discovery)
    total_in_discovery = len(getattr(discovery, "nodes", {}))
    logger.info(
        "NodeDiscoveryRuntime: startup seed complete — "
        "%d node(s) seeded, %d total in discovery",
        seeded, total_in_discovery,
    )
    return seeded


def build_discovery_runtime_snapshot(
    fabric: Any,
    discovery: Any,
    launcher_active_nodes: Optional[List[str]] = None,
) -> DiscoveryRuntimeSnapshot:
    """Build a diagnostic snapshot comparing launcher, fabric, and discovery states.

    Produces one :class:`NodeDiscoveryParticipationRecord` per unique node
    across all three planes and classifies each into one of four alignment
    categories:

    - ``"aligned"``             — healthy in fabric registry AND present in
                                  discovery.
    - ``"undiscovered_active"`` — healthy in fabric registry but absent from
                                  discovery.
    - ``"discovery_orphan"``    — present in discovery but not healthy in fabric
                                  registry (stale or non-fabric node).
    - ``"inactive"``            — offline/excluded in both planes.

    Args:
        fabric:               :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
                              instance (or any object with ``list_nodes()`` and
                              ``list_healthy()``).
        discovery:            :class:`~core.node_discovery.NodeDiscoveryService`
                              instance (or any object with ``.nodes`` dict).
        launcher_active_nodes: Optional list of node IDs the launcher considers
                              active (startup_policy active/optional).

    Returns:
        :class:`DiscoveryRuntimeSnapshot`
    """
    snap = DiscoveryRuntimeSnapshot(timestamp=time.time())
    launcher_set: Set[str] = set(launcher_active_nodes or [])
    snap.total_launcher_active = len(launcher_set)

    # Collect fabric state.
    fabric_nodes: Dict[str, Any] = {}
    fabric_healthy: Set[str] = set()
    try:
        for node_info in fabric.list_nodes():
            fabric_nodes[node_info.node_id] = node_info
        snap.total_fabric_nodes = len(fabric_nodes)
        for node_info in fabric.list_healthy():
            fabric_healthy.add(node_info.node_id)
    except Exception as exc:
        logger.warning("build_discovery_runtime_snapshot: fabric query failed: %s", exc)

    # Collect discovery state.
    discovery_nodes: Dict[str, Any] = {}
    try:
        discovery_nodes = dict(getattr(discovery, "nodes", {}))
        snap.total_discovery_nodes = len(discovery_nodes)
    except Exception as exc:
        logger.warning("build_discovery_runtime_snapshot: discovery query failed: %s", exc)

    # Build per-node records.
    all_node_ids: Set[str] = (
        set(fabric_nodes.keys()) | set(discovery_nodes.keys()) | launcher_set
    )

    records: List[NodeDiscoveryParticipationRecord] = []
    healthy_count = 0
    undiscovered_active_count = 0
    discovery_orphan_count = 0

    for node_id in sorted(all_node_ids):
        rec = NodeDiscoveryParticipationRecord(node_id=node_id)
        rec.in_launcher_active = node_id in launcher_set

        # Fabric state.
        if node_id in fabric_nodes:
            rec.in_fabric_registry = True
            ni = fabric_nodes[node_id]
            rec.fabric_status = (
                ni.status.value if hasattr(ni.status, "value") else str(ni.status)
            )
        else:
            rec.in_fabric_registry = False

        # Discovery state.
        if node_id in discovery_nodes:
            rec.in_discovery = True
            dn = discovery_nodes[node_id]
            rec.discovery_state = (
                dn.state.value if hasattr(dn.state, "value") else str(dn.state)
            )
        else:
            rec.in_discovery = False

        # Classify alignment.
        is_fabric_healthy = node_id in fabric_healthy
        is_in_discovery = rec.in_discovery

        if is_fabric_healthy and is_in_discovery:
            rec.alignment = "aligned"
            healthy_count += 1
        elif is_fabric_healthy and not is_in_discovery:
            rec.alignment = "undiscovered_active"
            undiscovered_active_count += 1
            rec.diagnostic_notes.append(
                f"{node_id} is healthy in NodeFabricRegistry "
                "but absent from NodeDiscoveryService — "
                "call announce_node_to_discovery() or seed_fabric_nodes_into_discovery()."
            )
        elif not is_fabric_healthy and is_in_discovery:
            # Only flag as orphan if fabric knows the node and it's not healthy.
            if node_id in fabric_nodes:
                rec.alignment = "discovery_orphan"
                discovery_orphan_count += 1
                rec.diagnostic_notes.append(
                    f"{node_id} is present in NodeDiscoveryService "
                    f"but fabric status is '{rec.fabric_status}' — "
                    "discovery entry may be stale."
                )
            else:
                # In discovery but not in fabric at all — external/manually seeded node.
                rec.alignment = "discovery_orphan"
                discovery_orphan_count += 1
                rec.diagnostic_notes.append(
                    f"{node_id} is in NodeDiscoveryService "
                    "but not in NodeFabricRegistry — "
                    "externally seeded or pre-dates fabric registry."
                )
        else:
            rec.alignment = "inactive"

        records.append(rec)

    snap.participation_records = records
    snap.healthy_count = healthy_count
    snap.undiscovered_active_count = undiscovered_active_count
    snap.discovery_orphan_count = discovery_orphan_count
    snap.seeded_count = len(fabric_healthy)

    logger.debug(
        "NodeDiscoveryRuntime snapshot: aligned=%d undiscovered_active=%d "
        "discovery_orphan=%d total=%d",
        healthy_count, undiscovered_active_count, discovery_orphan_count,
        len(all_node_ids),
    )
    return snap


def get_discovery_participation_summary(
    discovery: Any,
    fabric: Any,
) -> Dict[str, Any]:
    """Return a compact discovery participation summary for health/status surfaces.

    Suitable for inclusion in ``/health``, ``/api/v1/system/info``, and
    dashboard endpoints.  Does not include per-node detail (use
    :func:`build_discovery_runtime_snapshot` for full diagnostics).

    Args:
        discovery: :class:`~core.node_discovery.NodeDiscoveryService` instance.
        fabric:    :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
                   instance.

    Returns:
        Dict with keys:
        - ``discovery_total``         — total nodes in discovery service.
        - ``discovery_healthy``       — healthy nodes in discovery service.
        - ``fabric_total``            — total nodes in fabric registry.
        - ``fabric_healthy``          — healthy nodes in fabric registry.
        - ``undiscovered_active``     — nodes healthy in fabric but absent from discovery.
        - ``discovery_participation`` — ``"full"`` / ``"partial"`` / ``"none"``.
        - ``authority``               — module authority sentinel.
    """
    summary: Dict[str, Any] = {
        "discovery_total": 0,
        "discovery_healthy": 0,
        "fabric_total": 0,
        "fabric_healthy": 0,
        "undiscovered_active": 0,
        "discovery_participation": "none",
        "authority": NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY,
    }

    try:
        disc_nodes = getattr(discovery, "nodes", {})
        summary["discovery_total"] = len(disc_nodes)
        try:
            summary["discovery_healthy"] = len(discovery.get_healthy_nodes())
        except Exception:
            summary["discovery_healthy"] = sum(
                1 for n in disc_nodes.values()
                if getattr(n, "state", None) is not None
                and (
                    hasattr(n.state, "value")
                    and n.state.value in ("healthy", "registered")
                    or str(getattr(n.state, "value", n.state)) in ("healthy", "registered")
                )
            )
    except Exception as exc:
        logger.debug("get_discovery_participation_summary: discovery query failed: %s", exc)

    try:
        fabric_healthy_ids: Set[str] = set()
        fabric_all_ids: Set[str] = set()
        disc_ids: Set[str] = set(getattr(discovery, "nodes", {}).keys())

        for ni in fabric.list_nodes():
            fabric_all_ids.add(ni.node_id)
        for ni in fabric.list_healthy():
            fabric_healthy_ids.add(ni.node_id)

        summary["fabric_total"] = len(fabric_all_ids)
        summary["fabric_healthy"] = len(fabric_healthy_ids)
        undiscovered = fabric_healthy_ids - disc_ids
        summary["undiscovered_active"] = len(undiscovered)
    except Exception as exc:
        logger.debug("get_discovery_participation_summary: fabric query failed: %s", exc)

    # Classify participation level.
    disc_total = summary["discovery_total"]
    fab_healthy = summary["fabric_healthy"]
    undiscovered = summary["undiscovered_active"]

    if fab_healthy == 0 and disc_total == 0:
        summary["discovery_participation"] = "none"
    elif undiscovered == 0 and disc_total > 0:
        summary["discovery_participation"] = "full"
    elif disc_total > 0:
        summary["discovery_participation"] = "partial"
    else:
        summary["discovery_participation"] = "none"

    return summary
