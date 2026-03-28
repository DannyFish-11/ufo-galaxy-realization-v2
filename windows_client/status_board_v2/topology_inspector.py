"""
windows_client/status_board_v2/topology_inspector.py
=====================================================
PR-13: Diagnostics and inspection interaction layer.

Provides an **inspection surface** for the desktop topology / status board
that allows operators and client code to drill into topology nodes,
relations, readiness/authority state, routing summary details, and lower-
horizon OneAPI details — safely and without breaking the semantic guarantees
established by PR-4 through PR-12.

Design constraints
------------------
- **Built on the adapter + layout pipeline** — the inspector always operates
  on a :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`
  (the PR-11/12 model) and/or a
  :class:`~core.desktop_consumption_adapter.DesktopClientViewModel` (the PR-9
  adapter output).  It never bypasses these layers to reach raw nested payload
  dicts as its primary source.
- **Safe authority semantics** — the inspection output is always explicit
  about whether a node / relation / readiness state is canonical, degraded,
  partial, or unavailable.  Fallback/degraded data is never presented as
  authoritative truth.
- **OneAPI stays lower-horizon** — OneAPI inspection detail is always
  structurally distinct and carries an explicit ``is_lower_horizon_only=True``
  flag.  It is never returned as a canonical routing peer.
- **Read-only** — the inspector never sends commands or modifies system state.
- **Graceful** — all inspection paths handle ``None`` / missing layouts or
  view-models without raising.

Key classes
-----------
:class:`NodeInspectionDetail`
    Detailed view of a single topology node (kind, readiness, authority,
    provider, model, extra metadata).
:class:`RelationInspectionDetail`
    Detailed view of a directed topology relation (kind, authority, label,
    semantic meaning).
:class:`ReadinessInspectionDetail`
    Authority / readiness interpretation for the whole layout
    (canonical / degraded / partial / unavailable, with reasons).
:class:`RoutingInspectionDetail`
    Routing and provider summary details derived from the adapter view-model.
:class:`OneAPIInspectionDetail`
    Lower-horizon OneAPI integration details (always ``is_lower_horizon_only=True``).
:class:`InspectionReport`
    Complete diagnostics report that bundles all of the above into a single
    inspectable object with ``to_dict()`` / ``to_json()`` serialisation.
:class:`TopologyInspector`
    The main inspection surface.  Provides:

    - :meth:`~TopologyInspector.inspect_layout` — full inspection report from a layout.
    - :meth:`~TopologyInspector.inspect_node` — drill into a specific node by ID.
    - :meth:`~TopologyInspector.inspect_relation` — drill into a specific relation.
    - :meth:`~TopologyInspector.inspect_readiness` — readiness/authority detail only.
    - :meth:`~TopologyInspector.inspect_oneapi` — OneAPI lower-horizon detail only.
    - :meth:`~TopologyInspector.inspect_routing_summary` — routing/provider summary detail.
    - :meth:`~TopologyInspector.inspect_from_view_model` — build full report from a
      :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`.

Usage::

    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from core.desktop_consumption_adapter import adapt_integration_payload

    vm = adapt_integration_payload(payload)
    layout = build_constellation_layout(vm)
    inspector = TopologyInspector()

    # Full report
    report = inspector.inspect_layout(layout)
    print(report.readiness.readiness_label)        # "canonical"
    print(report.readiness.is_authoritative)       # True
    print(report.readiness.is_degraded)            # False

    # Drill into a specific node
    node_detail = inspector.inspect_node("primary_provider_node", layout)
    if node_detail:
        print(node_detail.kind)                    # "primary_provider"
        print(node_detail.is_authoritative)        # True
        print(node_detail.provider_id)             # "openai"

    # Drill into OneAPI
    oneapi_detail = inspector.inspect_oneapi(layout)
    print(oneapi_detail.is_lower_horizon_only)     # always True

    # Inspect from view-model directly (builds layout internally)
    report2 = inspector.inspect_from_view_model(vm)

See ``docs/DIAGNOSTICS_INSPECTION_INTERACTION.md`` for full design rationale.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from .topology_layout import (
    TOPOLOGY_LAYOUT_AUTHORITY,
    TopologyConstellationLayout,
    TopologyLayerKind,
    TopologyLayoutLayer,
    TopologyLayoutNode,
    TopologyLayoutRelation,
    TopologyNodeKind,
    TopologyRelationKind,
    build_constellation_layout,
)

# ---------------------------------------------------------------------------
# PR-13: Inspector authority sentinel
# ---------------------------------------------------------------------------

#: Sentinel string that identifies the diagnostics/inspection layer introduced
#: in PR-13.  Downstream consumers can check this value to confirm that an
#: :class:`InspectionReport` was produced by the canonical PR-13 inspector
#: rather than assembled ad-hoc.
TOPOLOGY_INSPECTOR_AUTHORITY: str = (
    "windows_client.status_board_v2.topology_inspector.TopologyInspector"
)

# ---------------------------------------------------------------------------
# Readiness semantic helpers
# ---------------------------------------------------------------------------

_READINESS_MEANING: Dict[str, str] = {
    "canonical": (
        "Topology is fully authoritative.  All routing decisions are based on "
        "the canonical server-side projection.  No legacy fallback is active."
    ),
    "degraded": (
        "Legacy routing fallback is active.  Topology data is NOT authoritative.  "
        "Routing decisions may be based on stale or approximate information."
    ),
    "partial": (
        "Canonical source is present but some topology components are missing or "
        "incomplete.  Routing may be partially authoritative."
    ),
    "unavailable": (
        "No topology data is available.  Routing status cannot be determined.  "
        "All topology information should be treated as absent."
    ),
    "unknown": (
        "Readiness could not be determined from the available data.  "
        "Treat topology information with caution."
    ),
}

_RELATION_KIND_MEANING: Dict[str, str] = {
    "canonical_route": (
        "Canonical routing relationship — fully authoritative.  "
        "The source node routes to the target via the canonical server-side plan."
    ),
    "support_path": (
        "Support / auxiliary routing path — the target node assists the source "
        "but is not the primary canonical route."
    ),
    "fallback_path": (
        "Legacy or degraded fallback path — NOT authoritative.  "
        "This relation represents a fallback when canonical routing is unavailable."
    ),
    "lower_horizon_link": (
        "Structural link to the OneAPI lower-horizon integration layer.  "
        "OneAPI is accessible but remains a lower-horizon element, "
        "never a canonical routing peer."
    ),
}

_NODE_KIND_MEANING: Dict[str, str] = {
    "primary_provider": (
        "Primary topology / provider node — the canonical root of the routing "
        "constellation.  Only authoritative in canonical or partial readiness states."
    ),
    "routing_peer": (
        "Routing peer — an alternate or support node in the routing layer.  "
        "Participates in routing decisions but is not the primary authority."
    ),
    "support_node": (
        "Support / auxiliary node — assists routing but is not a primary or peer "
        "routing node.  Provides supplemental capabilities."
    ),
    "oneapi_horizon": (
        "OneAPI integration node — always placed in the lower-horizon layer.  "
        "NEVER a canonical routing peer.  Accessible for lower-horizon integration "
        "purposes only."
    ),
}


# ---------------------------------------------------------------------------
# NodeInspectionDetail
# ---------------------------------------------------------------------------

class NodeInspectionDetail:
    """PR-13: Detailed diagnostic view of a single topology node.

    Attributes
    ----------
    node_id:
        Unique node identifier within the layout.
    kind:
        Node kind string (``"primary_provider"`` / ``"routing_peer"`` /
        ``"support_node"`` / ``"oneapi_horizon"``).
    kind_meaning:
        Human-readable description of what this node kind means.
    label:
        Human-readable display label.
    readiness_label:
        Readiness qualifier for this node
        (``"canonical"`` / ``"degraded"`` / ``"partial"`` / ``"unavailable"``).
    is_authoritative:
        ``True`` only when this node is part of a canonical (not degraded /
        fallback) topology.
    is_available:
        Whether the underlying resource reports itself as available.
    is_lower_horizon:
        ``True`` if this node is in the lower-horizon layer (OneAPI nodes only).
    provider_id:
        Optional provider identifier string.
    model_id:
        Optional model identifier string.
    extra:
        Arbitrary additional metadata dict from the layout node.
    authority_note:
        Explicit note about the authority status of this node.  Degraded /
        fallback nodes carry an explicit non-authoritative note.
    inspector_authority:
        Always equals :data:`TOPOLOGY_INSPECTOR_AUTHORITY`.
    """

    def __init__(
        self,
        *,
        node_id: str,
        kind: str,
        label: str,
        readiness_label: str,
        is_authoritative: bool,
        is_available: bool,
        is_lower_horizon: bool,
        provider_id: Optional[str],
        model_id: Optional[str],
        extra: Optional[Dict[str, Any]],
    ) -> None:
        self.node_id = node_id
        self.kind = kind
        self.kind_meaning: str = _NODE_KIND_MEANING.get(kind, f"Node kind: {kind!r}")
        self.label = label
        self.readiness_label = readiness_label
        self.is_authoritative = is_authoritative
        self.is_available = is_available
        self.is_lower_horizon = is_lower_horizon
        self.provider_id = provider_id
        self.model_id = model_id
        self.extra: Dict[str, Any] = extra or {}
        self.inspector_authority: str = TOPOLOGY_INSPECTOR_AUTHORITY

        # Construct an explicit authority note so there is no ambiguity.
        if kind == "oneapi_horizon":
            self.authority_note = (
                "OneAPI node — lower-horizon only.  "
                "Not a canonical routing peer.  "
                "Always inspect separately from primary/support nodes."
            )
        elif is_authoritative:
            self.authority_note = (
                "This node is part of a canonical topology projection "
                "and may be treated as authoritative."
            )
        else:
            self.authority_note = (
                "This node is NOT authoritative.  "
                "Routing data may be from a legacy fallback or incomplete source.  "
                "Do not treat this node's data as canonical truth."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this node inspection detail."""
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "kind_meaning": self.kind_meaning,
            "label": self.label,
            "readiness_label": self.readiness_label,
            "is_authoritative": self.is_authoritative,
            "is_available": self.is_available,
            "is_lower_horizon": self.is_lower_horizon,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "extra": self.extra,
            "authority_note": self.authority_note,
            "inspector_authority": self.inspector_authority,
        }

    def __repr__(self) -> str:
        return (
            f"NodeInspectionDetail(node_id={self.node_id!r}, kind={self.kind!r}, "
            f"readiness_label={self.readiness_label!r}, "
            f"is_authoritative={self.is_authoritative})"
        )


# ---------------------------------------------------------------------------
# RelationInspectionDetail
# ---------------------------------------------------------------------------

class RelationInspectionDetail:
    """PR-13: Detailed diagnostic view of a directed topology relation.

    Attributes
    ----------
    source_id:
        ``node_id`` of the source node.
    target_id:
        ``node_id`` of the target node.
    kind:
        Relation kind string (``"canonical_route"`` / ``"fallback_path"`` /
        ``"support_path"`` / ``"lower_horizon_link"``).
    kind_meaning:
        Human-readable description of what this relation kind means.
    label:
        Human-readable display label.
    is_authoritative:
        ``True`` only for canonical route relations.
    is_fallback:
        ``True`` when this relation represents a legacy/degraded fallback path.
    is_lower_horizon:
        ``True`` when this relation links to the lower-horizon OneAPI node.
    authority_note:
        Explicit note about the authority status of this relation.
    inspector_authority:
        Always equals :data:`TOPOLOGY_INSPECTOR_AUTHORITY`.
    """

    def __init__(
        self,
        *,
        source_id: str,
        target_id: str,
        kind: str,
        label: str,
        is_authoritative: bool,
    ) -> None:
        self.source_id = source_id
        self.target_id = target_id
        self.kind = kind
        self.kind_meaning: str = _RELATION_KIND_MEANING.get(
            kind, f"Relation kind: {kind!r}"
        )
        self.label = label
        self.is_authoritative = is_authoritative
        self.is_fallback: bool = kind == "fallback_path"
        self.is_lower_horizon: bool = kind == "lower_horizon_link"
        self.inspector_authority: str = TOPOLOGY_INSPECTOR_AUTHORITY

        if self.is_lower_horizon:
            self.authority_note = (
                "Lower-horizon link to OneAPI.  "
                "This relation does not represent a canonical routing path."
            )
        elif self.is_fallback:
            self.authority_note = (
                "Fallback / degraded relation — NOT authoritative.  "
                "This route is only active when canonical routing is unavailable."
            )
        elif is_authoritative:
            self.authority_note = (
                "Canonical route — fully authoritative.  "
                "This relation is the primary routing path."
            )
        else:
            self.authority_note = (
                "Non-canonical relation.  "
                "This path is supplemental or support-only; "
                "not the primary authoritative route."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this relation inspection detail."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "kind_meaning": self.kind_meaning,
            "label": self.label,
            "is_authoritative": self.is_authoritative,
            "is_fallback": self.is_fallback,
            "is_lower_horizon": self.is_lower_horizon,
            "authority_note": self.authority_note,
            "inspector_authority": self.inspector_authority,
        }

    def __repr__(self) -> str:
        return (
            f"RelationInspectionDetail({self.source_id!r} "
            f"→[{self.kind}]→ {self.target_id!r}, "
            f"is_authoritative={self.is_authoritative})"
        )


# ---------------------------------------------------------------------------
# ReadinessInspectionDetail
# ---------------------------------------------------------------------------

class ReadinessInspectionDetail:
    """PR-13: Authority / readiness interpretation for a topology layout.

    Attributes
    ----------
    readiness_label:
        One of ``"canonical"``, ``"degraded"``, ``"partial"``,
        ``"unavailable"``, ``"unknown"``.
    is_authoritative:
        ``True`` only when readiness is canonical.
    is_degraded:
        ``True`` when legacy routing fallback is active.
    is_partial:
        ``True`` when canonical source is present but some components are missing.
    is_unavailable:
        ``True`` when no topology data is available.
    meaning:
        Human-readable explanation of this readiness state.
    fallback_active:
        ``True`` when any legacy fallback is active in the layout.
    topology_legacy_fallback_active:
        Topology-specific legacy fallback flag, when inspected from a view-model.
    routing_legacy_fallback_active:
        Routing-specific legacy fallback flag, when inspected from a view-model.
    degraded_reason:
        Explanation of why the topology is degraded or non-authoritative, if
        applicable.  ``None`` when readiness is canonical.
    inspector_authority:
        Always equals :data:`TOPOLOGY_INSPECTOR_AUTHORITY`.
    """

    def __init__(
        self,
        *,
        readiness_label: str,
        is_authoritative: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        fallback_active: bool = False,
        topology_legacy_fallback_active: bool = False,
        routing_legacy_fallback_active: bool = False,
    ) -> None:
        self.readiness_label = readiness_label
        self.is_authoritative = is_authoritative
        self.is_degraded = is_degraded
        self.is_partial = is_partial
        self.is_unavailable = is_unavailable
        self.meaning: str = _READINESS_MEANING.get(
            readiness_label, _READINESS_MEANING["unknown"]
        )
        self.fallback_active = fallback_active
        self.topology_legacy_fallback_active = topology_legacy_fallback_active
        self.routing_legacy_fallback_active = routing_legacy_fallback_active
        self.inspector_authority: str = TOPOLOGY_INSPECTOR_AUTHORITY

        # Degrade reason — explicit only when not canonical.
        if is_degraded:
            self.degraded_reason: Optional[str] = (
                "Legacy routing fallback is active.  Topology projection is "
                "not authoritative.  Data may be stale or approximate."
            )
        elif is_partial:
            self.degraded_reason = (
                "Canonical source is present but some topology components are "
                "missing.  Routing may be only partially authoritative."
            )
        elif is_unavailable:
            self.degraded_reason = (
                "No topology data is available.  All routing information is absent."
            )
        else:
            self.degraded_reason = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this readiness detail."""
        return {
            "readiness_label": self.readiness_label,
            "is_authoritative": self.is_authoritative,
            "is_degraded": self.is_degraded,
            "is_partial": self.is_partial,
            "is_unavailable": self.is_unavailable,
            "meaning": self.meaning,
            "fallback_active": self.fallback_active,
            "topology_legacy_fallback_active": self.topology_legacy_fallback_active,
            "routing_legacy_fallback_active": self.routing_legacy_fallback_active,
            "degraded_reason": self.degraded_reason,
            "inspector_authority": self.inspector_authority,
        }

    def __repr__(self) -> str:
        return (
            f"ReadinessInspectionDetail(readiness_label={self.readiness_label!r}, "
            f"is_authoritative={self.is_authoritative}, "
            f"is_degraded={self.is_degraded})"
        )


# ---------------------------------------------------------------------------
# RoutingInspectionDetail
# ---------------------------------------------------------------------------

class RoutingInspectionDetail:
    """PR-13: Routing and provider summary diagnostics.

    Attributes
    ----------
    provider_id:
        Primary provider identifier from the topology projection.
    model_id:
        Primary model identifier.
    route_reason:
        Routing reason / phase string.
    authority_source:
        Routing authority source string (e.g. ``"TopologyRoutePlan"``).
    integration_health:
        Rolled-up integration health string
        (``"ok"`` / ``"degraded"`` / ``"advisory"`` / ``"critical"`` / ``"unknown"``).
    routing_legacy_fallback_active:
        Whether routing is using a legacy fallback path.
    provider_routing_available:
        Whether provider routing information is available.
    vendor_source:
        Vendor source string from the routing summary, when available.
    active_model_id:
        Active model identifier from the routing summary, when available.
    is_authoritative:
        ``True`` only when this routing detail is from a canonical (non-fallback)
        source.
    authority_note:
        Explicit note about the authority status of this routing detail.
    inspector_authority:
        Always equals :data:`TOPOLOGY_INSPECTOR_AUTHORITY`.
    """

    def __init__(
        self,
        *,
        provider_id: Optional[str],
        model_id: Optional[str],
        route_reason: Optional[str],
        authority_source: Optional[str],
        integration_health: str,
        routing_legacy_fallback_active: bool,
        provider_routing_available: bool,
        vendor_source: Optional[str] = None,
        active_model_id: Optional[str] = None,
        is_authoritative: bool = False,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.route_reason = route_reason
        self.authority_source = authority_source
        self.integration_health = integration_health
        self.routing_legacy_fallback_active = routing_legacy_fallback_active
        self.provider_routing_available = provider_routing_available
        self.vendor_source = vendor_source
        self.active_model_id = active_model_id
        self.is_authoritative = is_authoritative
        self.inspector_authority: str = TOPOLOGY_INSPECTOR_AUTHORITY

        if routing_legacy_fallback_active:
            self.authority_note = (
                "Routing is using a legacy fallback path.  "
                "Provider/model/routing data is NOT from the canonical source.  "
                "Do not treat this routing summary as authoritative truth."
            )
        elif is_authoritative:
            self.authority_note = (
                "Routing is fully canonical.  "
                "Provider, model, and routing authority source are authoritative."
            )
        else:
            self.authority_note = (
                "Routing authority could not be fully confirmed.  "
                "Treat routing data with appropriate caution."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this routing detail."""
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "route_reason": self.route_reason,
            "authority_source": self.authority_source,
            "integration_health": self.integration_health,
            "routing_legacy_fallback_active": self.routing_legacy_fallback_active,
            "provider_routing_available": self.provider_routing_available,
            "vendor_source": self.vendor_source,
            "active_model_id": self.active_model_id,
            "is_authoritative": self.is_authoritative,
            "authority_note": self.authority_note,
            "inspector_authority": self.inspector_authority,
        }

    def __repr__(self) -> str:
        return (
            f"RoutingInspectionDetail(provider_id={self.provider_id!r}, "
            f"is_authoritative={self.is_authoritative}, "
            f"integration_health={self.integration_health!r})"
        )


# ---------------------------------------------------------------------------
# OneAPIInspectionDetail
# ---------------------------------------------------------------------------

class OneAPIInspectionDetail:
    """PR-13: Lower-horizon OneAPI integration diagnostic detail.

    This detail is always structurally distinct from canonical routing
    details.  :attr:`is_lower_horizon_only` is always ``True``.

    Attributes
    ----------
    is_lower_horizon_only:
        Always ``True``.  OneAPI must never be promoted to a canonical peer.
    oneapi_available:
        Whether the OneAPI integration block is available.
    integration_type:
        Integration type string from the OneAPI summary, when available.
    provider_id:
        Provider identifier for the OneAPI horizon node, when available.
    authority_note:
        Explicit note clarifying the lower-horizon status of OneAPI.
    raw_summary:
        Raw dict from the OneAPI horizon summary, for advanced inspection.
    inspector_authority:
        Always equals :data:`TOPOLOGY_INSPECTOR_AUTHORITY`.
    """

    def __init__(
        self,
        *,
        oneapi_available: bool,
        integration_type: Optional[str],
        provider_id: Optional[str],
        raw_summary: Optional[Dict[str, Any]],
    ) -> None:
        self.is_lower_horizon_only: bool = True  # always True — non-negotiable
        self.oneapi_available = oneapi_available
        self.integration_type = integration_type
        self.provider_id = provider_id
        self.raw_summary: Dict[str, Any] = raw_summary or {}
        self.inspector_authority: str = TOPOLOGY_INSPECTOR_AUTHORITY
        self.authority_note: str = (
            "OneAPI is a lower-horizon integration.  "
            "It is NEVER a canonical routing peer.  "
            "Inspect separately from primary and support routing nodes.  "
            "is_lower_horizon_only is always True."
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this OneAPI detail."""
        return {
            "is_lower_horizon_only": self.is_lower_horizon_only,
            "oneapi_available": self.oneapi_available,
            "integration_type": self.integration_type,
            "provider_id": self.provider_id,
            "raw_summary": self.raw_summary,
            "authority_note": self.authority_note,
            "inspector_authority": self.inspector_authority,
        }

    def __repr__(self) -> str:
        return (
            f"OneAPIInspectionDetail(is_lower_horizon_only={self.is_lower_horizon_only}, "
            f"oneapi_available={self.oneapi_available})"
        )


# ---------------------------------------------------------------------------
# InspectionReport
# ---------------------------------------------------------------------------

class InspectionReport:
    """PR-13: Complete diagnostics / inspection report for a topology layout.

    Bundles all diagnostic details into a single inspectable object:

    - :attr:`readiness` — readiness/authority interpretation
    - :attr:`nodes` — list of :class:`NodeInspectionDetail` for all nodes
    - :attr:`relations` — list of :class:`RelationInspectionDetail` for all
      relations
    - :attr:`routing` — routing/provider summary detail
    - :attr:`oneapi` — lower-horizon OneAPI detail
    - :attr:`primary_nodes` — nodes from the primary layer only
    - :attr:`support_nodes` — nodes from the support layer only
    - :attr:`lower_horizon_nodes` — nodes from the lower-horizon layer only

    Attributes
    ----------
    report_id:
        Unique identifier for this report.
    readiness:
        :class:`ReadinessInspectionDetail` — overall readiness/authority.
    nodes:
        All node inspection details.
    relations:
        All relation inspection details.
    routing:
        :class:`RoutingInspectionDetail` — routing and provider summary.
    oneapi:
        :class:`OneAPIInspectionDetail` — OneAPI lower-horizon detail.
    primary_nodes:
        Nodes from the primary layer.
    support_nodes:
        Nodes from the support layer.
    lower_horizon_nodes:
        Nodes from the lower-horizon layer (always OneAPI nodes only).
    layout_authority:
        The authority string from the PR-11 layout that was inspected.
    inspector_authority:
        Always equals :data:`TOPOLOGY_INSPECTOR_AUTHORITY`.
    """

    def __init__(
        self,
        *,
        report_id: str,
        readiness: ReadinessInspectionDetail,
        nodes: List[NodeInspectionDetail],
        relations: List[RelationInspectionDetail],
        routing: RoutingInspectionDetail,
        oneapi: OneAPIInspectionDetail,
        primary_nodes: List[NodeInspectionDetail],
        support_nodes: List[NodeInspectionDetail],
        lower_horizon_nodes: List[NodeInspectionDetail],
        layout_authority: Optional[str] = None,
    ) -> None:
        self.report_id = report_id
        self.readiness = readiness
        self.nodes = nodes
        self.relations = relations
        self.routing = routing
        self.oneapi = oneapi
        self.primary_nodes = primary_nodes
        self.support_nodes = support_nodes
        self.lower_horizon_nodes = lower_horizon_nodes
        self.layout_authority = layout_authority
        self.inspector_authority: str = TOPOLOGY_INSPECTOR_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this inspection report."""
        return {
            "report_id": self.report_id,
            "readiness": self.readiness.to_dict(),
            "nodes": [n.to_dict() for n in self.nodes],
            "relations": [r.to_dict() for r in self.relations],
            "routing": self.routing.to_dict(),
            "oneapi": self.oneapi.to_dict(),
            "primary_nodes": [n.to_dict() for n in self.primary_nodes],
            "support_nodes": [n.to_dict() for n in self.support_nodes],
            "lower_horizon_nodes": [n.to_dict() for n in self.lower_horizon_nodes],
            "layout_authority": self.layout_authority,
            "inspector_authority": self.inspector_authority,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string of this inspection report."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:
        return (
            f"InspectionReport(report_id={self.report_id!r}, "
            f"readiness_label={self.readiness.readiness_label!r}, "
            f"nodes={len(self.nodes)}, relations={len(self.relations)})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _node_to_detail(node: Any, *, is_lower_horizon: bool = False) -> NodeInspectionDetail:
    """Convert a :class:`TopologyLayoutNode` or node-dict to
    :class:`NodeInspectionDetail`."""
    if isinstance(node, dict):
        node_id = str(node.get("node_id") or "")
        kind = str(node.get("kind") or "")
        label = str(node.get("label") or "")
        readiness_label = str(node.get("readiness_label") or "unknown")
        is_authoritative = bool(node.get("is_authoritative", False))
        is_available = bool(node.get("is_available", False))
        provider_id = node.get("provider_id")
        model_id = node.get("model_id")
        extra = node.get("extra") or {}
        # Determine lower-horizon from kind if not explicitly specified
        if not is_lower_horizon:
            is_lower_horizon = kind == TopologyNodeKind.oneapi_horizon.value
    else:
        node_id = str(getattr(node, "node_id", "") or "")
        kind_obj = getattr(node, "kind", None)
        kind = (
            kind_obj.value if hasattr(kind_obj, "value") else str(kind_obj or "")
        )
        label = str(getattr(node, "label", "") or "")
        readiness_label = str(getattr(node, "readiness_label", "unknown") or "unknown")
        is_authoritative = bool(getattr(node, "is_authoritative", False))
        is_available = bool(getattr(node, "is_available", False))
        provider_id = getattr(node, "provider_id", None)
        model_id = getattr(node, "model_id", None)
        extra = dict(getattr(node, "extra", {}) or {})
        if not is_lower_horizon:
            is_lower_horizon = kind == TopologyNodeKind.oneapi_horizon.value

    return NodeInspectionDetail(
        node_id=node_id,
        kind=kind,
        label=label,
        readiness_label=readiness_label,
        is_authoritative=is_authoritative,
        is_available=is_available,
        is_lower_horizon=is_lower_horizon,
        provider_id=provider_id,
        model_id=model_id,
        extra=extra,
    )


def _relation_to_detail(relation: Any) -> RelationInspectionDetail:
    """Convert a :class:`TopologyLayoutRelation` or relation-dict to
    :class:`RelationInspectionDetail`."""
    if isinstance(relation, dict):
        source_id = str(relation.get("source_id") or "")
        target_id = str(relation.get("target_id") or "")
        kind_obj = relation.get("kind", "")
        kind = str(kind_obj) if not isinstance(kind_obj, str) else kind_obj
        label = str(relation.get("label") or "")
        is_authoritative = bool(relation.get("is_authoritative", False))
    else:
        source_id = str(getattr(relation, "source_id", "") or "")
        target_id = str(getattr(relation, "target_id", "") or "")
        kind_obj = getattr(relation, "kind", None)
        kind = (
            kind_obj.value if hasattr(kind_obj, "value") else str(kind_obj or "")
        )
        label = str(getattr(relation, "label", "") or "")
        is_authoritative = bool(getattr(relation, "is_authoritative", False))

    return RelationInspectionDetail(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        label=label,
        is_authoritative=is_authoritative,
    )


def _extract_layer_nodes(
    layer: Any, *, is_lower_horizon: bool = False
) -> List[NodeInspectionDetail]:
    """Extract node details from a layer (object or dict)."""
    if layer is None:
        return []
    if isinstance(layer, dict):
        raw_nodes = layer.get("nodes") or []
        return [
            _node_to_detail(n, is_lower_horizon=is_lower_horizon)
            for n in raw_nodes
            if isinstance(n, dict)
        ]
    raw_nodes = list(getattr(layer, "nodes", []) or [])
    return [_node_to_detail(n, is_lower_horizon=is_lower_horizon) for n in raw_nodes]


# ---------------------------------------------------------------------------
# TopologyInspector
# ---------------------------------------------------------------------------

class TopologyInspector:
    """PR-13: Main diagnostics / inspection surface for the desktop topology.

    Provides drill-down access to:
    - all topology nodes (by layer, by ID, or all at once)
    - all topology relations/edges
    - readiness/authority interpretation
    - routing and provider summary details
    - lower-horizon OneAPI details (always structurally distinct)

    All inspection methods are read-only and gracefully handle ``None`` or
    minimal inputs without raising.

    The inspector always builds on the PR-11/12 layout model and PR-9 adapter
    view-model as its data source, never reaching past them to raw nested
    payload dicts.

    Usage::

        inspector = TopologyInspector()
        report = inspector.inspect_layout(layout)
        node_detail = inspector.inspect_node("my_node_id", layout)
        oneapi = inspector.inspect_oneapi(layout)
    """

    # ------------------------------------------------------------------
    # Full layout inspection
    # ------------------------------------------------------------------

    def inspect_layout(
        self, layout: Any
    ) -> InspectionReport:
        """Build a complete :class:`InspectionReport` from a layout.

        Parameters
        ----------
        layout:
            A :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`
            or its ``to_dict()`` serialisation.  If ``None`` or not a valid
            layout, an unavailable report is returned.

        Returns
        -------
        InspectionReport
            Always returns a report; never raises.
        """
        if layout is None:
            return self._unavailable_report()

        # Normalise to attribute-access-friendly form.
        if isinstance(layout, dict):
            readiness_label = str(layout.get("readiness_label") or "unknown")
            is_authoritative = bool(layout.get("is_authoritative", False))
            is_degraded = bool(layout.get("is_degraded", False))
            is_partial = bool(layout.get("is_partial", False))
            is_unavailable = bool(layout.get("is_unavailable", False))
            layout_authority = layout.get("layout_authority")
            primary_layer = layout.get("primary_layer")
            support_layer = layout.get("support_layer")
            lower_horizon_layer = layout.get("lower_horizon_layer")
            raw_relations = layout.get("relations") or []
        else:
            readiness_label = str(getattr(layout, "readiness_label", "unknown") or "unknown")
            is_authoritative = bool(getattr(layout, "is_authoritative", False))
            is_degraded = bool(getattr(layout, "is_degraded", False))
            is_partial = bool(getattr(layout, "is_partial", False))
            is_unavailable = bool(getattr(layout, "is_unavailable", False))
            layout_authority = getattr(layout, "layout_authority", None)
            primary_layer = getattr(layout, "primary_layer", None)
            support_layer = getattr(layout, "support_layer", None)
            lower_horizon_layer = getattr(layout, "lower_horizon_layer", None)
            raw_relations = list(getattr(layout, "relations", []) or [])

        # Build per-layer node details.
        primary_nodes = _extract_layer_nodes(primary_layer, is_lower_horizon=False)
        support_nodes = _extract_layer_nodes(support_layer, is_lower_horizon=False)
        lower_horizon_nodes = _extract_layer_nodes(
            lower_horizon_layer, is_lower_horizon=True
        )
        all_nodes = primary_nodes + support_nodes + lower_horizon_nodes

        # Build relation details.
        relations = [_relation_to_detail(r) for r in raw_relations]

        # Readiness detail.
        readiness = ReadinessInspectionDetail(
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            fallback_active=is_degraded,
        )

        # Routing detail — derived from primary node info in the layout.
        provider_id: Optional[str] = None
        model_id: Optional[str] = None
        if primary_nodes:
            provider_id = primary_nodes[0].provider_id
            model_id = primary_nodes[0].model_id

        routing = RoutingInspectionDetail(
            provider_id=provider_id,
            model_id=model_id,
            route_reason=None,
            authority_source=layout_authority,
            integration_health="ok" if is_authoritative else "degraded",
            routing_legacy_fallback_active=is_degraded,
            provider_routing_available=bool(primary_nodes),
            is_authoritative=is_authoritative,
        )

        # OneAPI detail — from lower-horizon nodes.
        oneapi_available = bool(lower_horizon_nodes)
        oneapi_provider_id: Optional[str] = None
        if lower_horizon_nodes:
            oneapi_provider_id = lower_horizon_nodes[0].provider_id
        oneapi = OneAPIInspectionDetail(
            oneapi_available=oneapi_available,
            integration_type=None,
            provider_id=oneapi_provider_id,
            raw_summary=None,
        )

        return InspectionReport(
            report_id=str(uuid.uuid4()),
            readiness=readiness,
            nodes=all_nodes,
            relations=relations,
            routing=routing,
            oneapi=oneapi,
            primary_nodes=primary_nodes,
            support_nodes=support_nodes,
            lower_horizon_nodes=lower_horizon_nodes,
            layout_authority=str(layout_authority) if layout_authority else None,
        )

    # ------------------------------------------------------------------
    # Node drill-down
    # ------------------------------------------------------------------

    def inspect_node(
        self, node_id: str, layout: Any
    ) -> Optional[NodeInspectionDetail]:
        """Drill into a specific node by its ID.

        Parameters
        ----------
        node_id:
            The ``node_id`` to look up.
        layout:
            A :class:`TopologyConstellationLayout` or its ``to_dict()`` form.

        Returns
        -------
        NodeInspectionDetail or None
            ``None`` if the node is not found or layout is ``None``.
        """
        if layout is None or not node_id:
            return None
        report = self.inspect_layout(layout)
        for node in report.nodes:
            if node.node_id == node_id:
                return node
        return None

    # ------------------------------------------------------------------
    # Relation drill-down
    # ------------------------------------------------------------------

    def inspect_relation(
        self, source_id: str, target_id: str, layout: Any
    ) -> Optional[RelationInspectionDetail]:
        """Drill into a specific relation by source and target node IDs.

        Parameters
        ----------
        source_id:
            The ``node_id`` of the source node.
        target_id:
            The ``node_id`` of the target node.
        layout:
            A :class:`TopologyConstellationLayout` or its ``to_dict()`` form.

        Returns
        -------
        RelationInspectionDetail or None
            The first matching relation, or ``None`` if not found.
        """
        if layout is None:
            return None
        report = self.inspect_layout(layout)
        for rel in report.relations:
            if rel.source_id == source_id and rel.target_id == target_id:
                return rel
        return None

    # ------------------------------------------------------------------
    # Readiness inspection
    # ------------------------------------------------------------------

    def inspect_readiness(self, layout: Any) -> ReadinessInspectionDetail:
        """Return readiness / authority detail from a layout.

        Parameters
        ----------
        layout:
            A :class:`TopologyConstellationLayout` or its ``to_dict()`` form.
            If ``None``, an unavailable readiness detail is returned.

        Returns
        -------
        ReadinessInspectionDetail
            Always returns a detail object; never raises.
        """
        if layout is None:
            return ReadinessInspectionDetail(
                readiness_label="unavailable",
                is_authoritative=False,
                is_degraded=False,
                is_partial=False,
                is_unavailable=True,
            )
        return self.inspect_layout(layout).readiness

    # ------------------------------------------------------------------
    # OneAPI inspection
    # ------------------------------------------------------------------

    def inspect_oneapi(self, layout: Any) -> OneAPIInspectionDetail:
        """Return lower-horizon OneAPI detail from a layout.

        The returned detail always has ``is_lower_horizon_only=True``.

        Parameters
        ----------
        layout:
            A :class:`TopologyConstellationLayout` or its ``to_dict()`` form.
            If ``None``, an unavailable (but still lower-horizon-only) detail
            is returned.

        Returns
        -------
        OneAPIInspectionDetail
            Always returns a detail object; never raises.
        """
        if layout is None:
            return OneAPIInspectionDetail(
                oneapi_available=False,
                integration_type=None,
                provider_id=None,
                raw_summary=None,
            )
        return self.inspect_layout(layout).oneapi

    # ------------------------------------------------------------------
    # Routing summary inspection
    # ------------------------------------------------------------------

    def inspect_routing_summary(self, layout: Any) -> RoutingInspectionDetail:
        """Return routing/provider summary diagnostic detail from a layout.

        Parameters
        ----------
        layout:
            A :class:`TopologyConstellationLayout` or its ``to_dict()`` form.
            If ``None``, a degraded/unavailable routing detail is returned.

        Returns
        -------
        RoutingInspectionDetail
            Always returns a detail object; never raises.
        """
        if layout is None:
            return RoutingInspectionDetail(
                provider_id=None,
                model_id=None,
                route_reason=None,
                authority_source=None,
                integration_health="unknown",
                routing_legacy_fallback_active=False,
                provider_routing_available=False,
                is_authoritative=False,
            )
        return self.inspect_layout(layout).routing

    # ------------------------------------------------------------------
    # View-model driven inspection
    # ------------------------------------------------------------------

    def inspect_from_view_model(self, vm: Any) -> InspectionReport:
        """Build a complete :class:`InspectionReport` from a
        :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`.

        This is the preferred entry point when starting from the PR-9 adapter
        output rather than from an already-built layout.  It builds the
        PR-11 layout internally and then runs the full inspection pipeline.

        Additional view-model fields (``topology_route_reason``,
        ``routing_authority_source``, ``integration_health``,
        ``topology_legacy_fallback_active``, ``routing_legacy_fallback_active``,
        OneAPI horizon details) are merged into the report so that the
        inspection output reflects all available adapter information.

        Parameters
        ----------
        vm:
            A :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`
            or its ``to_dict()`` form.  If ``None``, an unavailable report is
            returned.

        Returns
        -------
        InspectionReport
            Always returns a report; never raises.
        """
        if vm is None:
            return self._unavailable_report()

        # Build the layout and run the standard inspection pipeline.
        layout = build_constellation_layout(vm)
        report = self.inspect_layout(layout)

        # Enrich readiness with view-model flags.
        topo_fallback = bool(
            getattr(vm, "topology_legacy_fallback_active", False)
            if not isinstance(vm, dict)
            else vm.get("topology_legacy_fallback_active", False)
        )
        routing_fallback = bool(
            getattr(vm, "routing_legacy_fallback_active", False)
            if not isinstance(vm, dict)
            else vm.get("routing_legacy_fallback_active", False)
        )
        report.readiness.topology_legacy_fallback_active = topo_fallback
        report.readiness.routing_legacy_fallback_active = routing_fallback
        report.readiness.fallback_active = topo_fallback or routing_fallback

        # Enrich routing with view-model fields.
        if not isinstance(vm, dict):
            route_reason = getattr(vm, "topology_route_reason", None)
            auth_src = getattr(vm, "routing_authority_source", None)
            int_health = getattr(vm, "integration_health", "unknown")
            vendor_src: Optional[str] = None
            pr = getattr(vm, "provider_routing", None)
            if pr is not None:
                vendor_src = getattr(pr, "vendor_source", None)
                if report.routing.model_id is None:
                    report.routing.active_model_id = getattr(pr, "active_model_id", None)
        else:
            route_reason = vm.get("topology_route_reason")
            auth_src = vm.get("routing_authority_source")
            int_health = vm.get("integration_health", "unknown")
            vendor_src = None
            pr = vm.get("provider_routing")
            if isinstance(pr, dict):
                vendor_src = pr.get("vendor_source")

        report.routing.route_reason = route_reason
        report.routing.authority_source = auth_src
        report.routing.integration_health = str(int_health or "unknown")
        report.routing.vendor_source = vendor_src
        report.routing.routing_legacy_fallback_active = routing_fallback

        # Enrich OneAPI with view-model horizon summary.
        if not isinstance(vm, dict):
            oh = getattr(vm, "oneapi_horizon", None)
        else:
            oh = vm.get("oneapi_horizon")
        if oh is not None:
            if isinstance(oh, dict):
                raw_summary = dict(oh)
                oh_available = bool(oh.get("is_available", False))
                oh_integration_type = oh.get("integration_type")
                oh_provider_id = oh.get("provider_id")
            else:
                oh_dict = oh.to_dict() if hasattr(oh, "to_dict") else {}
                raw_summary = oh_dict
                oh_available = bool(getattr(oh, "is_available", False))
                oh_integration_type = getattr(oh, "integration_type", None)
                oh_provider_id = getattr(oh, "provider_id", None)
            report.oneapi = OneAPIInspectionDetail(
                oneapi_available=oh_available,
                integration_type=oh_integration_type,
                provider_id=oh_provider_id,
                raw_summary=raw_summary,
            )

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _unavailable_report(self) -> InspectionReport:
        """Return a minimal safe report for when no layout is available."""
        readiness = ReadinessInspectionDetail(
            readiness_label="unavailable",
            is_authoritative=False,
            is_degraded=False,
            is_partial=False,
            is_unavailable=True,
        )
        routing = RoutingInspectionDetail(
            provider_id=None,
            model_id=None,
            route_reason=None,
            authority_source=None,
            integration_health="unknown",
            routing_legacy_fallback_active=False,
            provider_routing_available=False,
            is_authoritative=False,
        )
        oneapi = OneAPIInspectionDetail(
            oneapi_available=False,
            integration_type=None,
            provider_id=None,
            raw_summary=None,
        )
        return InspectionReport(
            report_id=str(uuid.uuid4()),
            readiness=readiness,
            nodes=[],
            relations=[],
            routing=routing,
            oneapi=oneapi,
            primary_nodes=[],
            support_nodes=[],
            lower_horizon_nodes=[],
            layout_authority=None,
        )
