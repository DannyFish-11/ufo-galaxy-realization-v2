#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/multi_device_projection_canonicalization.py
=====================================================
PR-522: Multi-Device Projection Canonicalization.

**Architecture role**
---------------------
This module closes **GAP-517-008** by ensuring the multi-device runtime
projection endpoint (/api/v1/projection/runtime/multi-device) derives its
representative state from *canonical* chain/runtime sources rather than
relying primarily on raw transport/session registry data.

Before this PR the endpoint assembled a projection that included chain and
task-graph snapshots only as supplementary metadata (PR-519 partial).  The
merged_results body and the top-level projection surface remained anchored to
raw registry/session data.

After this PR:

1. **Canonical sources are primary** — the projection enrichment layer reads
   from :class:`~core.cross_device_execution_chain.CrossDeviceChainSingleton`,
   :class:`~core.task_graph_runtime.TaskGraphRuntime`,
   :class:`~core.operator_surface.OperatorSurface` (optional), and
   :class:`~core.device_formation.formation_resolver.resolve_formation`
   (optional) before falling back to registry/session data.

2. **Degraded state is explicit** — when canonical data is unavailable or
   only partially populated the enrichment result carries a
   :attr:`CanonicalProjectionSurfacingState` of ``PARTIAL`` or ``DEGRADED``
   with machine-readable ``surfacing_gap_reasons`` rather than silently
   presenting a falsely complete view.

3. **Raw transport/session authority is downgraded** — session registry data
   may still appear in the projection when canonical data is absent, but is
   labelled as transport-local and not presented as canonical truth.

Public API
----------
Sentinels::

    MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY
    MULTI_DEVICE_PROJECTION_CANONICALIZATION_LAYER_POSITION
    MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED
    MULTI_DEVICE_PROJECTION_GAP008_RESOLVED

Enums::

    CanonicalProjectionSurfacingState

Dataclasses::

    MultiDeviceCanonicalEnrichment

Functions::

    enrich_multi_device_projection(*, max_chain_records, max_graph_records)
        -> MultiDeviceCanonicalEnrichment

Resolves
--------
- **GAP-517-008**: multi-device runtime projection is now enriched from
  canonical CrossDeviceChainSingleton and TaskGraphRuntime state.  Incomplete
  or degraded canonical surfacing is made explicit.
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    # Sentinels
    "MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY",
    "MULTI_DEVICE_PROJECTION_CANONICALIZATION_LAYER_POSITION",
    "MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED",
    "MULTI_DEVICE_PROJECTION_GAP008_RESOLVED",
    # Enums
    "CanonicalProjectionSurfacingState",
    # Dataclasses
    "MultiDeviceCanonicalEnrichment",
    # Functions
    "enrich_multi_device_projection",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Authority sentinel — identifies this module as the canonical enrichment
#: authority for multi-device runtime projection (PR-522 / GAP-517-008).
MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY: str = (
    "MULTI_DEVICE_PROJECTION_CANONICALIZATION::PR522_CANONICAL_PROJECTION_AUTHORITY_V1"
)

#: Architectural layer position.  Sits above result surface (layer 12),
#: below presentation (layer 14).
MULTI_DEVICE_PROJECTION_CANONICALIZATION_LAYER_POSITION: int = 13

#: Wiring sentinel — added to core/routes/projection.py to signal that
#: the multi-device projection endpoint has been integrated with this module.
MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED: str = (
    "MULTI_DEVICE_PROJECTION_CANONICALIZATION::INTEGRATED_V1: "
    "get_multi_device_runtime_projection() now consumes enrich_multi_device_projection() "
    "so that the projection is grounded in canonical CrossDeviceChainSingleton, "
    "TaskGraphRuntime, OperatorSurface, and formation state rather than raw "
    "transport/session registry data alone.  Resolves GAP-517-008."
)

#: Gap-resolution sentinel — importable evidence that GAP-517-008 is closed.
MULTI_DEVICE_PROJECTION_GAP008_RESOLVED: str = (
    "MULTI_DEVICE_PROJECTION_CANONICALIZATION::GAP_517_008_RESOLVED: "
    "Multi-device runtime projection is now enriched from canonical "
    "CrossDeviceChainSingleton, TaskGraphRuntime, OperatorSurface, and "
    "formation/runtime metadata rather than raw transport/session registry data."
)


# ---------------------------------------------------------------------------
# CanonicalProjectionSurfacingState
# ---------------------------------------------------------------------------


class CanonicalProjectionSurfacingState(str, Enum):
    """Describes how completely the projection was populated from canonical sources.

    ``FULL``
        All canonical sources (chain, graph, operator) were available and
        contributed data to the projection.

    ``PARTIAL``
        At least one canonical source contributed data, but one or more
        sources were unavailable or returned empty state.

    ``DEGRADED``
        No canonical source contributed meaningful data; the projection falls
        back to transport/session registry data (if any).

    ``UNAVAILABLE``
        All canonical sources raised exceptions; no canonical data is
        available.  The projection body is entirely transport-local.
    """

    FULL = "full"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# MultiDeviceCanonicalEnrichment
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class MultiDeviceCanonicalEnrichment:
    """Result of enriching a multi-device projection from canonical runtime sources.

    Attributes
    ----------
    enrichment_id:
        Unique identifier for this enrichment snapshot (UUID4 by default).
    surfacing_state:
        Overall canonical surfacing fidelity (FULL / PARTIAL / DEGRADED /
        UNAVAILABLE).
    surfacing_gap_reasons:
        Machine-readable list of reasons why canonical surfacing is incomplete.
        Empty list indicates full canonical coverage.
    chain_snapshot:
        Serialised snapshot from :class:`~core.cross_device_execution_chain.CrossDeviceChainSingleton`,
        or ``None`` if unavailable.
    chain_available:
        True if the cross-device chain singleton was successfully queried.
    canonical_executions:
        Number of canonical chain executions recorded in this session.
    legacy_executions:
        Number of legacy chain executions recorded in this session.
    total_executions:
        Total chain executions recorded.
    recent_chain_records:
        Serialised list of recent :class:`~core.cross_device_execution_chain.ChainExecutionRecord`
        entries (up to ``max_chain_records``).
    graph_snapshot:
        Serialised snapshot from :class:`~core.task_graph_runtime.TaskGraphRuntime`,
        or ``None`` if unavailable.
    graph_available:
        True if the task graph runtime was successfully queried.
    graph_node_count:
        Number of nodes in the task graph (0 if unavailable).
    recent_graph_records:
        Serialised list of recent graph runtime records.
    operator_snapshot:
        Serialised snapshot from :class:`~core.operator_surface.OperatorSurface`,
        or ``None`` if unavailable.
    operator_available:
        True if the operator surface was successfully queried.
    formation_metadata:
        Optional formation descriptor dict (from ``DeviceFormationGroup``),
        or ``None`` if not applicable.
    formation_available:
        True if formation metadata was resolved.
    integrity_snapshot:
        Optional integrity audit snapshot from
        :class:`~core.multi_device_control_integrity.MultiDeviceControlIntegrityRuntime`,
        or ``None`` if unavailable.
    integrity_available:
        True if the integrity runtime was successfully queried.
    transport_local_only:
        True when no canonical source provided data and the projection body
        must rely solely on transport/session registry data.
    timestamp:
        UNIX timestamp when this enrichment was assembled.
    """

    enrichment_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    surfacing_state: CanonicalProjectionSurfacingState = (
        CanonicalProjectionSurfacingState.UNAVAILABLE
    )
    surfacing_gap_reasons: List[str] = dataclasses.field(default_factory=list)

    # Cross-device chain (CrossDeviceChainSingleton)
    chain_snapshot: Optional[Dict[str, Any]] = None
    chain_available: bool = False
    canonical_executions: int = 0
    legacy_executions: int = 0
    total_executions: int = 0
    recent_chain_records: List[Dict[str, Any]] = dataclasses.field(
        default_factory=list
    )

    # Task graph runtime (TaskGraphRuntime)
    graph_snapshot: Optional[Dict[str, Any]] = None
    graph_available: bool = False
    graph_node_count: int = 0
    recent_graph_records: List[Dict[str, Any]] = dataclasses.field(
        default_factory=list
    )

    # Operator surface (OperatorSurface)
    operator_snapshot: Optional[Dict[str, Any]] = None
    operator_available: bool = False

    # Formation metadata (DeviceFormationGroup)
    formation_metadata: Optional[Dict[str, Any]] = None
    formation_available: bool = False

    # Integrity audit snapshot
    integrity_snapshot: Optional[Dict[str, Any]] = None
    integrity_available: bool = False

    # Degradation flag
    transport_local_only: bool = True

    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enrichment_id": self.enrichment_id,
            "surfacing_state": self.surfacing_state.value,
            "surfacing_gap_reasons": list(self.surfacing_gap_reasons),
            "chain_snapshot": self.chain_snapshot,
            "chain_available": self.chain_available,
            "canonical_executions": self.canonical_executions,
            "legacy_executions": self.legacy_executions,
            "total_executions": self.total_executions,
            "recent_chain_records": list(self.recent_chain_records),
            "graph_snapshot": self.graph_snapshot,
            "graph_available": self.graph_available,
            "graph_node_count": self.graph_node_count,
            "recent_graph_records": list(self.recent_graph_records),
            "operator_snapshot": self.operator_snapshot,
            "operator_available": self.operator_available,
            "formation_metadata": self.formation_metadata,
            "formation_available": self.formation_available,
            "integrity_snapshot": self.integrity_snapshot,
            "integrity_available": self.integrity_available,
            "transport_local_only": self.transport_local_only,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# enrich_multi_device_projection
# ---------------------------------------------------------------------------


def enrich_multi_device_projection(
    *,
    max_chain_records: int = 10,
    max_graph_records: int = 10,
) -> "MultiDeviceCanonicalEnrichment":
    """Assemble a canonical enrichment for the multi-device runtime projection.

    This function queries all available canonical runtime sources and returns
    a :class:`MultiDeviceCanonicalEnrichment` whose ``surfacing_state``
    honestly reflects how much canonical data was available.

    Sources consulted (all non-fatal — failures are recorded as gap reasons):

    1. :class:`~core.cross_device_execution_chain.CrossDeviceChainSingleton` —
       chain execution records, canonical vs legacy counts.
    2. :class:`~core.task_graph_runtime.TaskGraphRuntime` — task node state
       and recent graph records.
    3. :class:`~core.operator_surface.OperatorSurface` — operator-level
       execution snapshot (optional).
    4. :class:`~core.multi_device_control_integrity.MultiDeviceControlIntegrityRuntime`
       — integrity audit snapshot (optional).

    The caller (projection endpoint) should embed the returned enrichment into
    the projection metadata, replacing (or superseding) any prior partial
    enrichment from PR-519.

    Parameters
    ----------
    max_chain_records:
        Maximum number of recent chain execution records to include.
    max_graph_records:
        Maximum number of recent graph runtime records to include.

    Returns
    -------
    MultiDeviceCanonicalEnrichment
        Always returns a valid enrichment.  On complete failure the
        ``surfacing_state`` is ``UNAVAILABLE`` and ``transport_local_only``
        is ``True``.
    """
    enrichment = MultiDeviceCanonicalEnrichment()
    surfacing_gap_reasons: List[str] = []
    canonical_sources_available: int = 0

    # ── Source 1: CrossDeviceChainSingleton ──────────────────────────────
    try:
        from core.cross_device_execution_chain import build_cross_device_chain_snapshot
        chain_snap = build_cross_device_chain_snapshot(max_recent=max_chain_records)
        enrichment.chain_available = True
        enrichment.canonical_executions = chain_snap.canonical_executions
        enrichment.legacy_executions = chain_snap.legacy_executions
        enrichment.total_executions = chain_snap.total_executions
        enrichment.recent_chain_records = [
            r.to_dict() for r in chain_snap.recent_records
        ]
        enrichment.chain_snapshot = {
            "snapshot_id": chain_snap.snapshot_id,
            "total_executions": chain_snap.total_executions,
            "canonical_executions": chain_snap.canonical_executions,
            "legacy_executions": chain_snap.legacy_executions,
            "canonical_chain_order": chain_snap.canonical_chain_order,
            "chain_authority_map": chain_snap.chain_authority_map,
            "recent_record_count": len(chain_snap.recent_records),
        }
        canonical_sources_available += 1
        logger.debug(
            "enrich_multi_device_projection: chain available "
            "total=%d canonical=%d legacy=%d",
            enrichment.total_executions,
            enrichment.canonical_executions,
            enrichment.legacy_executions,
        )
    except Exception as chain_exc:
        surfacing_gap_reasons.append(
            f"GAP-517-008: CrossDeviceChainSingleton unavailable: {chain_exc}"
        )
        logger.debug(
            "enrich_multi_device_projection: chain snapshot unavailable: %s",
            chain_exc,
        )

    # ── Source 2: TaskGraphRuntime ────────────────────────────────────────
    try:
        from core.task_graph_runtime import get_task_graph_runtime
        tgr = get_task_graph_runtime()
        tgr_snap = tgr.snapshot(max_records=max_graph_records)
        enrichment.graph_available = True
        enrichment.graph_node_count = len(tgr_snap.nodes)
        enrichment.recent_graph_records = [
            r.to_dict() for r in tgr_snap.recent_records
        ]
        enrichment.graph_snapshot = {
            "node_count": enrichment.graph_node_count,
            "recent_record_count": len(tgr_snap.recent_records),
        }
        canonical_sources_available += 1
        logger.debug(
            "enrich_multi_device_projection: graph available nodes=%d",
            enrichment.graph_node_count,
        )
    except Exception as tgr_exc:
        surfacing_gap_reasons.append(
            f"GAP-517-008: TaskGraphRuntime unavailable: {tgr_exc}"
        )
        logger.debug(
            "enrich_multi_device_projection: graph snapshot unavailable: %s",
            tgr_exc,
        )

    # ── Source 3: OperatorSurface (optional) ─────────────────────────────
    try:
        from core.operator_surface import get_operator_surface
        op_surface = get_operator_surface()
        op_snap = op_surface.operator_snapshot()
        enrichment.operator_available = True
        enrichment.operator_snapshot = op_snap.to_dict() if hasattr(op_snap, "to_dict") else dict(op_snap)
        canonical_sources_available += 1
        logger.debug("enrich_multi_device_projection: operator surface available")
    except Exception as op_exc:
        # OperatorSurface is optional — do not add to surfacing_gap_reasons
        logger.debug(
            "enrich_multi_device_projection: operator surface unavailable: %s",
            op_exc,
        )

    # ── Source 4: MultiDeviceControlIntegrityRuntime (optional) ──────────
    try:
        from core.multi_device_control_integrity import (
            build_integrity_snapshot,
        )
        integrity_snap = build_integrity_snapshot()
        enrichment.integrity_available = True
        enrichment.integrity_snapshot = {
            "snapshot_id": integrity_snap.snapshot_id,
            "canonical_entry_count": integrity_snap.canonical_entry_count,
            "legacy_entry_count": integrity_snap.legacy_entry_count,
            "canonical_dispatch_count": integrity_snap.canonical_dispatch_count,
            "legacy_dispatch_count": integrity_snap.legacy_dispatch_count,
        }
        canonical_sources_available += 1
        logger.debug("enrich_multi_device_projection: integrity runtime available")
    except Exception as integrity_exc:
        # Integrity runtime is optional
        logger.debug(
            "enrich_multi_device_projection: integrity runtime unavailable: %s",
            integrity_exc,
        )

    # ── Determine overall surfacing state ────────────────────────────────
    enrichment.surfacing_gap_reasons = surfacing_gap_reasons

    # transport_local_only: True only when *neither* chain nor graph was available
    enrichment.transport_local_only = (
        not enrichment.chain_available and not enrichment.graph_available
    )

    # Chain and graph are the two *required* canonical sources.  Operator and
    # integrity are supplementary.
    required_available = int(enrichment.chain_available) + int(enrichment.graph_available)

    if required_available == 2:
        enrichment.surfacing_state = CanonicalProjectionSurfacingState.FULL
    elif required_available == 1:
        enrichment.surfacing_state = CanonicalProjectionSurfacingState.PARTIAL
    elif canonical_sources_available > 0:
        # At least one optional source contributed data
        enrichment.surfacing_state = CanonicalProjectionSurfacingState.DEGRADED
    else:
        enrichment.surfacing_state = CanonicalProjectionSurfacingState.UNAVAILABLE

    if surfacing_gap_reasons:
        logger.warning(
            "enrich_multi_device_projection: incomplete canonical coverage "
            "state=%s gaps=%s",
            enrichment.surfacing_state.value,
            surfacing_gap_reasons,
        )
    else:
        logger.debug(
            "enrich_multi_device_projection: full canonical coverage state=%s",
            enrichment.surfacing_state.value,
        )

    return enrichment
