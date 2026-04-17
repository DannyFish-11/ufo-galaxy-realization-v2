#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/multi_device_truth_convergence.py
========================================
PR-4: Multi-Device Truth and Projection Convergence.

Architecture role
-----------------
This module is the **single convergence point** for multi-device runtime
truth across the five key distributed-state domains:

  1. **Formation** — device grouping, role assignment, formation health.
  2. **Readiness** — per-device registered/online/connected/routable state.
  3. **Participation** — per-device orchestration eligibility and tier.
  4. **Topology** — network reachability, path state, and edge health.
  5. **Session context** — active mesh session lifecycle and continuity.

Problem addressed
-----------------
Before this module, each of these domains could be assembled independently
by downstream consumers reading from overlapping partial sources (compat
cache, session registry, device registry, formation resolver, topology
runtime).  That multi-source assembly creates ambiguity:

  * No single place declares which source wins for each domain.
  * Downstream consumers can construct conflicting truths by combining
    different subsets of sources.
  * The ``MultiDeviceRuntimeProjection`` cannot guarantee that
    formation / readiness / topology data came from canonical sources.

After this module:

  * ``converge_multi_device_truth()`` is the **single compilation function**
    that assembles a :class:`MultiDeviceTruthConvergenceSnapshot`.
  * Each domain facet carries an explicit ``authority_source`` string that
    names the canonical source used.
  * Downstream consumers (``MultiDeviceRuntimeProjection``,
    ``OutwardRuntimeTruthSnapshot``) embed the convergence snapshot rather
    than re-assembling truth from raw subsystems.

Authority precedence
--------------------
Within each domain the authority hierarchy is fixed:

Formation
    ``DeviceFormationGroup`` from
    ``core.device_formation.formation_resolver.resolve_formation`` is the
    primary authority.  ``FormationRuntimeCoordinator`` state is secondary.
    Raw session registry data is tertiary (transport-local only).

Readiness
    ``TruthIntegrationLayer`` (UCM + UDM) is the primary authority.
    ``DeviceReadinessSummary`` from ``core.device_readiness`` is secondary.
    Compat-cache data is never presented as authoritative.

Participation
    ``ParticipationSummary`` from ``core.device_participation`` is the primary
    authority.  It builds on Layer-1 readiness so the precedence chain is
    preserved.

Topology
    ``NetworkTopologyRuntime`` snapshot is the primary authority.
    Transport-hierarchy data is secondary.

Session context
    ``AttachedSessionRegistry`` is the primary authority for active session
    state.  ``MeshSessionPersistenceStore`` is the primary authority for
    recoverable/durable session state.  Session registry data from
    ``registered_devices`` is excluded.

Governance sentinels
--------------------
``MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY``
    Identifies this module as the canonical convergence layer.

``MULTI_DEVICE_TRUTH_CONVERGENCE_LAYER_POSITION``
    Layer 14 — sits above projection canonicalization (Layer 13) and
    below outward truth (Layer 15).

``FORMATION_TRUTH_SOURCE_PRECEDENCE_POLICY``
    Documents formation domain authority hierarchy.

``READINESS_TRUTH_SOURCE_PRECEDENCE_POLICY``
    Documents readiness domain authority hierarchy.

``PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_POLICY``
    Documents participation domain authority hierarchy.

``TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_POLICY``
    Documents topology domain authority hierarchy.

``SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_POLICY``
    Documents session context domain authority hierarchy.

``DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_POLICY``
    Downstream consumers must source multi-device truth from this module's
    convergence snapshot rather than assembling their own from raw sources.

Public API
----------
Enums::

    MultiDeviceTruthDomain

Dataclasses::

    MultiDeviceTruthDomainFacet
    MultiDeviceTruthConvergenceSnapshot

Functions::

    converge_multi_device_truth() -> MultiDeviceTruthConvergenceSnapshot
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MultiDeviceTruthConvergence")

__all__ = [
    # Sentinels
    "MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY",
    "MULTI_DEVICE_TRUTH_CONVERGENCE_LAYER_POSITION",
    "MULTI_DEVICE_TRUTH_CONVERGENCE_PR4_SENTINEL",
    "FORMATION_TRUTH_SOURCE_PRECEDENCE_POLICY",
    "READINESS_TRUTH_SOURCE_PRECEDENCE_POLICY",
    "PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_POLICY",
    "TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_POLICY",
    "SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_POLICY",
    "DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_POLICY",
    # Enums
    "MultiDeviceTruthDomain",
    # Dataclasses
    "MultiDeviceTruthDomainFacet",
    "MultiDeviceTruthConvergenceSnapshot",
    # Functions
    "converge_multi_device_truth",
]

# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY: str = (
    "MULTI_DEVICE_TRUTH_CONVERGENCE::PR4_CONVERGENCE_AUTHORITY_V1: "
    "core/multi_device_truth_convergence.py is the canonical single "
    "convergence point for multi-device runtime truth across formation, "
    "readiness, participation, topology, and session context domains.  "
    "Layer 14.5."
)

MULTI_DEVICE_TRUTH_CONVERGENCE_LAYER_POSITION: int = 14
"""Architectural layer position — sits above projection canonicalization
(Layer 13) and below outward truth (Layer 15)."""

MULTI_DEVICE_TRUTH_CONVERGENCE_PR4_SENTINEL: str = (
    "MULTI_DEVICE_TRUTH_CONVERGENCE::PR4_SENTINEL_V1: "
    "PR-4 Multi-Device Truth and Projection Convergence is implemented. "
    "formation / readiness / participation / topology / session-context "
    "truth domains are converged through a single snapshot that downstream "
    "projection surfaces must prefer over independent raw-source assembly."
)

FORMATION_TRUTH_SOURCE_PRECEDENCE_POLICY: str = (
    "FORMATION_TRUTH_SOURCE_PRECEDENCE_V1: "
    "Formation domain authority hierarchy: "
    "(1) DeviceFormationGroup from formation_resolver [primary]; "
    "(2) FormationRuntimeCoordinator state [secondary]; "
    "(3) raw session registry data [transport-local, excluded from canonical truth]."
)

READINESS_TRUTH_SOURCE_PRECEDENCE_POLICY: str = (
    "READINESS_TRUTH_SOURCE_PRECEDENCE_V1: "
    "Readiness domain authority hierarchy: "
    "(1) TruthIntegrationLayer (UCM+UDM) [primary]; "
    "(2) DeviceReadinessSummary from device_readiness [secondary]; "
    "(3) compat cache [excluded from authoritative truth]."
)

PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_POLICY: str = (
    "PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_V1: "
    "Participation domain authority hierarchy: "
    "(1) ParticipationSummary from device_participation [primary, "
    "built on Layer-1 readiness]; "
    "(2) orchestration eligibility from canonical device selector [secondary]; "
    "(3) mesh membership enrichment [enrichment only, not authority]."
)

TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_POLICY: str = (
    "TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_V1: "
    "Topology domain authority hierarchy: "
    "(1) NetworkTopologyRuntime snapshot [primary]; "
    "(2) transport hierarchy role data [secondary]; "
    "(3) scattered per-device connection summaries [excluded from outward topology truth]."
)

SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_POLICY: str = (
    "SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_V1: "
    "Session context authority hierarchy: "
    "(1) AttachedSessionRegistry [primary, active session lifecycle]; "
    "(2) MeshSessionPersistenceStore [primary, durable/recoverable sessions]; "
    "(3) raw session registry data from registered_devices [excluded]."
)

DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_POLICY: str = (
    "DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_V1: "
    "Downstream projection surfaces (MultiDeviceRuntimeProjection, "
    "OutwardRuntimeTruthSnapshot) MUST source multi-device truth from "
    "converge_multi_device_truth() rather than independently assembling "
    "formation / readiness / participation / topology / session-context "
    "from raw subsystem sources.  Violating this policy creates ambiguous "
    "or conflicting outward truth for downstream consumers."
)


# ===========================================================================
# Enums
# ===========================================================================


class MultiDeviceTruthDomain(str, Enum):
    """The five key distributed-state domains covered by this convergence layer."""

    FORMATION = "formation"
    """Device grouping, role assignment, and formation health."""

    READINESS = "readiness"
    """Per-device registered / online / connected / routable state."""

    PARTICIPATION = "participation"
    """Per-device orchestration eligibility and participant tier."""

    TOPOLOGY = "topology"
    """Network reachability, path state, and edge health."""

    SESSION_CONTEXT = "session_context"
    """Active mesh session lifecycle and durable session continuity."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class MultiDeviceTruthDomainFacet:
    """Canonical truth facet for one multi-device state domain.

    Each instance is assembled by ``converge_multi_device_truth()`` from
    the highest-authority source available for that domain.

    Attributes
    ----------
    domain:
        Which of the five domains this facet represents.
    authority_source:
        Human-readable name of the canonical source that was used to
        populate this facet (e.g. ``"TruthIntegrationLayer"``).
    authority_tier:
        ``"primary"`` when the highest-priority source responded,
        ``"secondary"`` when only a fallback source was used,
        ``"unavailable"`` when no source responded.
    data:
        The canonical data dict for this domain.  Structure is
        domain-specific but always serialisable.  ``None`` when
        ``authority_tier == "unavailable"``.
    gap_reasons:
        Machine-readable list of reasons why canonical coverage is
        incomplete (empty when ``authority_tier == "primary"``).
    latency_ms:
        Round-trip latency to assemble this facet.
    """

    domain: MultiDeviceTruthDomain
    authority_source: str = "unknown"
    authority_tier: str = "unavailable"
    data: Optional[Dict[str, Any]] = None
    gap_reasons: List[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "authority_source": self.authority_source,
            "authority_tier": self.authority_tier,
            "data": self.data,
            "gap_reasons": list(self.gap_reasons),
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class MultiDeviceTruthConvergenceSnapshot:
    """Canonical convergence snapshot of all five multi-device truth domains.

    This is the stable output object that downstream projection surfaces
    (:class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`,
    :class:`~core.outward_runtime_truth.OutwardRuntimeTruthSnapshot`) should
    embed rather than assembling equivalent state from raw sources.

    Attributes
    ----------
    convergence_id:
        Unique identifier for this snapshot (UUID4).
    assembled_at:
        Unix epoch timestamp when this snapshot was assembled.
    authority:
        Always equals :data:`MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY`.
    formation:
        Canonical formation domain facet.
    readiness:
        Canonical readiness domain facet.
    participation:
        Canonical participation domain facet.
    topology:
        Canonical topology domain facet.
    session_context:
        Canonical session context domain facet.
    fully_canonical:
        ``True`` when all five domains have ``authority_tier == "primary"``.
    partial_domains:
        List of domain names where the facet fell back to secondary sources
        or was unavailable.
    convergence_notes:
        Human-readable summary notes (surfacing gaps, degraded sources, etc.).
    """

    convergence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    assembled_at: float = field(default_factory=time.time)
    authority: str = MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY

    formation: MultiDeviceTruthDomainFacet = field(
        default_factory=lambda: MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.FORMATION
        )
    )
    readiness: MultiDeviceTruthDomainFacet = field(
        default_factory=lambda: MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.READINESS
        )
    )
    participation: MultiDeviceTruthDomainFacet = field(
        default_factory=lambda: MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.PARTICIPATION
        )
    )
    topology: MultiDeviceTruthDomainFacet = field(
        default_factory=lambda: MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.TOPOLOGY
        )
    )
    session_context: MultiDeviceTruthDomainFacet = field(
        default_factory=lambda: MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.SESSION_CONTEXT
        )
    )

    fully_canonical: bool = False
    partial_domains: List[str] = field(default_factory=list)
    convergence_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict suitable for embedding in projection contracts."""
        return {
            "convergence_id": self.convergence_id,
            "assembled_at": self.assembled_at,
            "authority": self.authority,
            "fully_canonical": self.fully_canonical,
            "partial_domains": list(self.partial_domains),
            "convergence_notes": list(self.convergence_notes),
            "formation": self.formation.to_dict(),
            "readiness": self.readiness.to_dict(),
            "participation": self.participation.to_dict(),
            "topology": self.topology.to_dict(),
            "session_context": self.session_context.to_dict(),
        }


# ===========================================================================
# Internal domain assemblers
# ===========================================================================


def _assemble_formation_facet() -> MultiDeviceTruthDomainFacet:
    """Assemble the formation truth facet from the highest-authority source.

    Authority order: formation_resolver (primary) → compat fallback (secondary).
    """
    t0 = time.monotonic()
    gap_reasons: List[str] = []

    # ── Primary: DeviceFormationGroup from formation_resolver ────────────
    try:
        from core.device_formation.formation_resolver import resolve_formation  # type: ignore

        formation_group = resolve_formation()
        if formation_group is not None:
            if hasattr(formation_group, "to_dict"):
                data = formation_group.to_dict()
            elif hasattr(formation_group, "model_dump"):
                data = formation_group.model_dump(mode="json")
            elif isinstance(formation_group, dict):
                data = formation_group
            else:
                data = {"formation_id": str(getattr(formation_group, "formation_id", "unknown"))}

            # Normalise keys for canonical outward contract
            canonical_data: Dict[str, Any] = {
                "formation_id": data.get("formation_id", "unknown"),
                "device_count": data.get("device_count", len(data.get("devices", []))),
                "role_map": data.get("role_map", data.get("roles", {})),
                "health_score": data.get("health_score", data.get("health", None)),
                "status": data.get("status", "active"),
                "authority_source": "formation_resolver.resolve_formation",
            }
            return MultiDeviceTruthDomainFacet(
                domain=MultiDeviceTruthDomain.FORMATION,
                authority_source="formation_resolver",
                authority_tier="primary",
                data=canonical_data,
                gap_reasons=[],
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        gap_reasons.append("formation_resolver.resolve_formation returned None")
    except Exception as exc:
        gap_reasons.append(f"formation_resolver unavailable: {exc}")

    # ── Secondary: formation summary via harness ─────────────────────────
    try:
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness  # type: ignore

        harness = MultiDeviceRuntimeHarness()
        # harness doesn't hold state in isolation; just note availability
        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.FORMATION,
            authority_source="MultiDeviceRuntimeHarness",
            authority_tier="secondary",
            data={
                "authority_source": "MultiDeviceRuntimeHarness",
                "note": "formation_resolver unavailable; harness-level formation truth only",
            },
            gap_reasons=gap_reasons,
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as harness_exc:
        gap_reasons.append(f"MultiDeviceRuntimeHarness unavailable: {harness_exc}")

    return MultiDeviceTruthDomainFacet(
        domain=MultiDeviceTruthDomain.FORMATION,
        authority_source="none",
        authority_tier="unavailable",
        data=None,
        gap_reasons=gap_reasons,
        latency_ms=(time.monotonic() - t0) * 1000,
    )


def _assemble_readiness_facet() -> MultiDeviceTruthDomainFacet:
    """Assemble the readiness truth facet.

    Authority order: TruthIntegrationLayer (primary) → DeviceReadinessSummary (secondary).
    """
    t0 = time.monotonic()
    gap_reasons: List[str] = []

    # ── Primary: TruthIntegrationLayer ──────────────────────────────────
    try:
        from core.truth_integration_layer import resolve_all_device_truth  # type: ignore

        all_truth = resolve_all_device_truth()
        device_summaries = [t.to_dict() for t in all_truth]
        available_count = sum(1 for t in all_truth if t.is_available)
        authority_count = sum(1 for t in all_truth if t.authority_available)

        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.READINESS,
            authority_source="TruthIntegrationLayer",
            authority_tier="primary",
            data={
                "device_count": len(device_summaries),
                "available_device_count": available_count,
                "authority_device_count": authority_count,
                "device_truths": device_summaries,
                "authority_source": "truth_integration_layer.resolve_all_device_truth",
            },
            gap_reasons=[],
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc:
        gap_reasons.append(f"TruthIntegrationLayer unavailable: {exc}")

    # ── Secondary: DeviceReadinessSummary ────────────────────────────────
    try:
        from core.device_readiness import get_cross_device_ready_devices  # type: ignore

        ready_devices = get_cross_device_ready_devices()
        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.READINESS,
            authority_source="device_readiness",
            authority_tier="secondary",
            data={
                "ready_device_count": len(ready_devices),
                "device_ids": [
                    getattr(d, "device_id", str(d)) for d in ready_devices
                ],
                "authority_source": "device_readiness.get_cross_device_ready_devices",
            },
            gap_reasons=gap_reasons,
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc2:
        gap_reasons.append(f"device_readiness unavailable: {exc2}")

    return MultiDeviceTruthDomainFacet(
        domain=MultiDeviceTruthDomain.READINESS,
        authority_source="none",
        authority_tier="unavailable",
        data=None,
        gap_reasons=gap_reasons,
        latency_ms=(time.monotonic() - t0) * 1000,
    )


def _assemble_participation_facet() -> MultiDeviceTruthDomainFacet:
    """Assemble the participation truth facet.

    Authority: ParticipationSummary from device_participation (primary).
    """
    t0 = time.monotonic()
    gap_reasons: List[str] = []

    try:
        from core.device_participation import get_orchestration_ready_devices  # type: ignore

        orch_ready = get_orchestration_ready_devices()
        summaries = []
        for p in orch_ready:
            if hasattr(p, "to_dict"):
                summaries.append(p.to_dict())
            elif isinstance(p, dict):
                summaries.append(p)
            else:
                summaries.append(
                    {
                        "device_id": getattr(p, "device_id", "unknown"),
                        "orchestration_eligible": getattr(
                            p, "orchestration_eligible", False
                        ),
                    }
                )

        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.PARTICIPATION,
            authority_source="device_participation",
            authority_tier="primary",
            data={
                "orchestration_ready_count": len(summaries),
                "participant_summaries": summaries,
                "authority_source": "device_participation.get_orchestration_ready_devices",
            },
            gap_reasons=[],
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc:
        gap_reasons.append(f"device_participation unavailable: {exc}")

    return MultiDeviceTruthDomainFacet(
        domain=MultiDeviceTruthDomain.PARTICIPATION,
        authority_source="none",
        authority_tier="unavailable",
        data=None,
        gap_reasons=gap_reasons,
        latency_ms=(time.monotonic() - t0) * 1000,
    )


def _assemble_topology_facet() -> MultiDeviceTruthDomainFacet:
    """Assemble the topology truth facet.

    Authority: NetworkTopologyRuntime snapshot (primary).
    """
    t0 = time.monotonic()
    gap_reasons: List[str] = []

    # ── Primary: NetworkTopologyRuntime ─────────────────────────────────
    try:
        from core.network_topology_runtime import get_network_topology_runtime  # type: ignore

        ntr = get_network_topology_runtime()
        snap = ntr.snapshot()
        if hasattr(snap, "to_dict"):
            snap_dict = snap.to_dict()
        elif isinstance(snap, dict):
            snap_dict = snap
        else:
            snap_dict = {
                "node_count": getattr(snap, "node_count", 0),
                "edge_count": getattr(snap, "edge_count", 0),
            }

        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.TOPOLOGY,
            authority_source="NetworkTopologyRuntime",
            authority_tier="primary",
            data={
                "topology_snapshot": snap_dict,
                "authority_source": "network_topology_runtime.get_network_topology_runtime",
            },
            gap_reasons=[],
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc:
        gap_reasons.append(f"NetworkTopologyRuntime unavailable: {exc}")

    # ── Secondary: network graph runtime ────────────────────────────────
    try:
        from core.network_graph_runtime import get_network_graph_runtime  # type: ignore

        ngr = get_network_graph_runtime()
        snap = ngr.snapshot() if hasattr(ngr, "snapshot") else {}
        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.TOPOLOGY,
            authority_source="NetworkGraphRuntime",
            authority_tier="secondary",
            data={
                "graph_snapshot": snap if isinstance(snap, dict) else {},
                "authority_source": "network_graph_runtime",
            },
            gap_reasons=gap_reasons,
            latency_ms=(time.monotonic() - t0) * 1000,
        )
    except Exception as exc2:
        gap_reasons.append(f"NetworkGraphRuntime unavailable: {exc2}")

    return MultiDeviceTruthDomainFacet(
        domain=MultiDeviceTruthDomain.TOPOLOGY,
        authority_source="none",
        authority_tier="unavailable",
        data=None,
        gap_reasons=gap_reasons,
        latency_ms=(time.monotonic() - t0) * 1000,
    )


def _assemble_session_context_facet() -> MultiDeviceTruthDomainFacet:
    """Assemble the session context truth facet.

    Authority: AttachedSessionRegistry (active sessions, primary) plus
    MeshSessionPersistenceStore (durable sessions, primary).
    """
    t0 = time.monotonic()
    gap_reasons: List[str] = []
    session_data: Dict[str, Any] = {}
    authority_tier = "unavailable"
    sources_hit: List[str] = []

    # ── Primary: AttachedSessionRegistry ────────────────────────────────
    try:
        from core.attached_runtime_session_registry import (  # type: ignore
            AttachedSessionRegistry,
        )

        registry = AttachedSessionRegistry()
        active = registry.list_active() if hasattr(registry, "list_active") else []
        session_ids = [
            getattr(s, "session_id", str(s)) for s in active
        ]
        session_data["active_session_count"] = len(session_ids)
        session_data["active_session_ids"] = session_ids
        sources_hit.append("AttachedSessionRegistry")
        authority_tier = "primary"
        logger.debug(
            "converge_session_context: active sessions=%d",
            len(session_ids),
        )
    except Exception as exc:
        gap_reasons.append(f"AttachedSessionRegistry unavailable: {exc}")

    # ── Primary (durable): MeshSessionPersistenceStore ──────────────────
    try:
        from core.mesh.mesh_session_persistence import (  # type: ignore
            recover_mesh_sessions,
        )

        recoverable = recover_mesh_sessions()
        recoverable_ids = [r.session_id for r in recoverable]
        session_data["recoverable_session_count"] = len(recoverable_ids)
        session_data["recoverable_session_ids"] = recoverable_ids
        session_data["status_breakdown"] = {
            r.session_id: r.overall_status for r in recoverable
        }
        sources_hit.append("MeshSessionPersistenceStore")
        if authority_tier == "unavailable":
            authority_tier = "primary"
        logger.debug(
            "converge_session_context: recoverable sessions=%d",
            len(recoverable_ids),
        )
    except Exception as exc:
        gap_reasons.append(f"MeshSessionPersistenceStore unavailable: {exc}")

    if not sources_hit:
        return MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.SESSION_CONTEXT,
            authority_source="none",
            authority_tier="unavailable",
            data=None,
            gap_reasons=gap_reasons,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    session_data["authority_sources"] = sources_hit
    session_data["authority_source"] = "+".join(sources_hit)

    return MultiDeviceTruthDomainFacet(
        domain=MultiDeviceTruthDomain.SESSION_CONTEXT,
        authority_source="+".join(sources_hit),
        authority_tier=authority_tier,
        data=session_data,
        gap_reasons=gap_reasons,
        latency_ms=(time.monotonic() - t0) * 1000,
    )


# ===========================================================================
# Public API
# ===========================================================================


def converge_multi_device_truth() -> MultiDeviceTruthConvergenceSnapshot:
    """Assemble and return the canonical multi-device truth convergence snapshot.

    This is the **single compilation function** for multi-device distributed
    state truth.  It:

    1. Queries each of the five domain assemblers in turn (all non-fatal).
    2. Determines ``fully_canonical`` and ``partial_domains``.
    3. Returns a :class:`MultiDeviceTruthConvergenceSnapshot` that downstream
       projection surfaces must embed rather than re-assembling raw truth.

    All domain queries are *read-only* and *soft-fail*: if a source is
    unavailable the facet is produced with ``authority_tier="unavailable"``
    and an explanatory gap reason rather than raising.

    Returns
    -------
    MultiDeviceTruthConvergenceSnapshot
        The converged snapshot.  Never raises.
    """
    t_start = time.monotonic()
    notes: List[str] = []

    formation = _assemble_formation_facet()
    readiness = _assemble_readiness_facet()
    participation = _assemble_participation_facet()
    topology = _assemble_topology_facet()
    session_context = _assemble_session_context_facet()

    all_facets = [formation, readiness, participation, topology, session_context]
    partial_domains = [
        f.domain.value
        for f in all_facets
        if f.authority_tier != "primary"
    ]
    fully_canonical = len(partial_domains) == 0

    for facet in all_facets:
        for reason in facet.gap_reasons:
            notes.append(f"[{facet.domain.value}] {reason}")

    if not fully_canonical:
        notes.append(
            f"Convergence is partial: {len(partial_domains)} domain(s) "
            f"below primary authority: {partial_domains}"
        )

    total_ms = (time.monotonic() - t_start) * 1000
    logger.debug(
        "converge_multi_device_truth: assembled in %.1f ms — "
        "fully_canonical=%s partial_domains=%s",
        total_ms,
        fully_canonical,
        partial_domains,
    )

    return MultiDeviceTruthConvergenceSnapshot(
        formation=formation,
        readiness=readiness,
        participation=participation,
        topology=topology,
        session_context=session_context,
        fully_canonical=fully_canonical,
        partial_domains=partial_domains,
        convergence_notes=notes,
    )
