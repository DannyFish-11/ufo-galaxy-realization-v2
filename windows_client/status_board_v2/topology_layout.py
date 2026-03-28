"""
windows_client/status_board_v2/topology_layout.py
==================================================
PR-11: Topology / constellation layout foundation.

Builds a **topology-aware layout** from the adapter-driven
:class:`~core.desktop_consumption_adapter.DesktopClientViewModel` introduced
in PR-9 and surfaced in PR-10.  This module transforms the flat view-model
into a structured constellation of *layers*, *nodes*, and *relations* that
express topology / provider / routing relationships rather than only flat
textual sections.

Design constraints
------------------
- **Adapter-driven only** — the layout is always built from a
  :class:`DesktopClientViewModel` (or an equivalent plain dict); it never
  bypasses the PR-9/PR-10 adapter layer to reconstruct truth from raw nested
  integration payload dicts.
- **OneAPI always lower-horizon** — the OneAPI block is always placed in a
  distinct :attr:`~TopologyLayerKind.lower_horizon` layer and never promoted
  to a canonical routing peer in the primary or support layer.
- **Readiness-aware** — every layout element reflects the readiness state
  (``canonical`` / ``degraded`` / ``partial`` / ``unavailable``) coming from
  the view-model; degraded / partial / unavailable states are never rendered as
  fully authoritative structure.
- **Read-only** — this module only produces layout data structures; it never
  sends commands or modifies system state.
- **Graceful** — all builder paths handle ``None`` / minimal view-models
  without raising.

Layer model
-----------
The layout is organised into three layers::

    ┌──────────────────────────────────────────────┐
    │  PRIMARY LAYER                               │
    │  (canonical provider / topology root node)   │
    ├──────────────────────────────────────────────┤
    │  SUPPORT LAYER                               │
    │  (routing peers / support paths)             │
    ├──────────────────────────────────────────────┤
    │  LOWER-HORIZON LAYER                         │
    │  (OneAPI integration — not a routing peer)   │
    └──────────────────────────────────────────────┘

Each layer holds zero or more :class:`TopologyLayoutNode` objects.
Cross-layer and intra-layer relationships are captured in
:class:`TopologyLayoutRelation` objects attached to the enclosing
:class:`TopologyConstellationLayout`.

Usage::

    from windows_client.status_board_v2.topology_layout import (
        build_constellation_layout,
        TopologyConstellationLayout,
        TOPOLOGY_LAYOUT_AUTHORITY,
    )
    from core.desktop_consumption_adapter import adapt_integration_payload

    vm = adapt_integration_payload(payload)
    layout = build_constellation_layout(vm)

    print(layout.readiness_label)         # e.g. "canonical"
    print(layout.is_authoritative)        # True when canonical
    for node in layout.primary_layer.nodes:
        print(node.node_id, node.kind.value, node.is_authoritative)
    for rel in layout.relations:
        print(rel.source_id, "→", rel.target_id, rel.kind.value)

See ``docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`` for full design rationale.
"""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# PR-11: Layout authority sentinel
# ---------------------------------------------------------------------------

#: Sentinel string that identifies the topology/constellation layout builder
#: introduced in PR-11.  Downstream consumers can check this value to confirm
#: that a :class:`TopologyConstellationLayout` was produced by the canonical
#: PR-11 builder rather than assembled ad-hoc.
TOPOLOGY_LAYOUT_AUTHORITY: str = (
    "windows_client.status_board_v2.topology_layout.build_constellation_layout"
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TopologyNodeKind(str, Enum):
    """PR-11: Kind of a node in the topology/constellation layout.

    Values
    ------
    primary_provider
        The canonical primary topology/provider node (e.g. main LLM provider).
    routing_peer
        A peer in the routing layer (e.g. an alternate or support routing node).
    support_node
        A support / auxiliary node that assists routing but is not the primary.
    oneapi_horizon
        The OneAPI integration node — always placed in the lower-horizon layer;
        never a canonical routing peer.
    """

    primary_provider = "primary_provider"
    routing_peer = "routing_peer"
    support_node = "support_node"
    oneapi_horizon = "oneapi_horizon"


class TopologyRelationKind(str, Enum):
    """PR-11: Kind of a relationship between topology nodes.

    Values
    ------
    canonical_route
        A canonical routing relationship from primary topology to its authority
        source (fully authoritative).
    support_path
        A support / auxiliary routing path (not the primary canonical route).
    fallback_path
        A legacy or degraded fallback path (not authoritative).
    lower_horizon_link
        A structural link from the primary layer to the OneAPI lower-horizon
        node, indicating OneAPI is accessible but remains a lower-horizon
        integration layer, not a routing peer.
    """

    canonical_route = "canonical_route"
    support_path = "support_path"
    fallback_path = "fallback_path"
    lower_horizon_link = "lower_horizon_link"


class TopologyLayerKind(str, Enum):
    """PR-11: Layer kind in the topology constellation.

    Values
    ------
    primary
        Top layer — holds the canonical primary provider / topology root node.
    support
        Middle layer — holds routing peers and support nodes.
    lower_horizon
        Bottom layer — holds the OneAPI integration node.  Nodes here are never
        promoted to the primary or support layers.
    """

    primary = "primary"
    support = "support"
    lower_horizon = "lower_horizon"


# ---------------------------------------------------------------------------
# Layout node
# ---------------------------------------------------------------------------

class TopologyLayoutNode:
    """PR-11: A single node in the topology constellation layout.

    Attributes
    ----------
    node_id:
        Unique identifier for this node within the layout.
    kind:
        :class:`TopologyNodeKind` — what role this node plays.
    label:
        Human-readable label for display purposes.
    readiness_label:
        Readiness qualifier from the view-model
        (``"canonical"`` / ``"degraded"`` / ``"partial"`` / ``"unavailable"``).
    is_available:
        Whether the underlying resource reports itself as available.
    is_authoritative:
        ``True`` only when this node is part of a canonical (not degraded /
        fallback) topology.  Must not be ``True`` for nodes in degraded,
        partial, or unavailable layouts.
    provider_id:
        Optional provider identifier string (e.g. ``"openai"``).
    model_id:
        Optional model identifier string.
    extra:
        Arbitrary additional metadata dict for future extension.
    """

    def __init__(
        self,
        *,
        node_id: str,
        kind: TopologyNodeKind,
        label: str,
        readiness_label: str = "unknown",
        is_available: bool = False,
        is_authoritative: bool = False,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.node_id = node_id
        self.kind = kind
        self.label = label
        self.readiness_label = readiness_label
        self.is_available = is_available
        self.is_authoritative = is_authoritative
        self.provider_id = provider_id
        self.model_id = model_id
        self.extra: Dict[str, Any] = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this node."""
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "label": self.label,
            "readiness_label": self.readiness_label,
            "is_available": self.is_available,
            "is_authoritative": self.is_authoritative,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "extra": self.extra,
        }

    def __repr__(self) -> str:
        return (
            f"TopologyLayoutNode(node_id={self.node_id!r}, kind={self.kind.value!r}, "
            f"label={self.label!r}, readiness_label={self.readiness_label!r}, "
            f"is_authoritative={self.is_authoritative})"
        )


# ---------------------------------------------------------------------------
# Layout relation
# ---------------------------------------------------------------------------

class TopologyLayoutRelation:
    """PR-11: A directed relationship between two nodes in the layout.

    Attributes
    ----------
    source_id:
        ``node_id`` of the source node.
    target_id:
        ``node_id`` of the target node.
    kind:
        :class:`TopologyRelationKind` — what kind of relationship this is.
    label:
        Human-readable label for display purposes.
    is_authoritative:
        ``True`` only for canonical route relations; ``False`` for fallback /
        lower-horizon / support relations.
    """

    def __init__(
        self,
        *,
        source_id: str,
        target_id: str,
        kind: TopologyRelationKind,
        label: str = "",
        is_authoritative: bool = False,
    ) -> None:
        self.source_id = source_id
        self.target_id = target_id
        self.kind = kind
        self.label = label
        self.is_authoritative = is_authoritative

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this relation."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "label": self.label,
            "is_authoritative": self.is_authoritative,
        }

    def __repr__(self) -> str:
        return (
            f"TopologyLayoutRelation({self.source_id!r} →[{self.kind.value}]→ "
            f"{self.target_id!r}, is_authoritative={self.is_authoritative})"
        )


# ---------------------------------------------------------------------------
# Layout layer
# ---------------------------------------------------------------------------

class TopologyLayoutLayer:
    """PR-11: A layer in the topology constellation layout.

    Each layout has exactly three layers: :attr:`~TopologyLayerKind.primary`,
    :attr:`~TopologyLayerKind.support`, and
    :attr:`~TopologyLayerKind.lower_horizon`.

    Attributes
    ----------
    layer_kind:
        :class:`TopologyLayerKind` for this layer.
    label:
        Human-readable layer label.
    is_lower_horizon:
        ``True`` only for the :attr:`~TopologyLayerKind.lower_horizon` layer.
        Consumers must use this flag to keep OneAPI visually and structurally
        separate from primary/support layers.
    nodes:
        Ordered list of :class:`TopologyLayoutNode` objects in this layer.
    """

    def __init__(
        self,
        *,
        layer_kind: TopologyLayerKind,
        label: str,
        is_lower_horizon: bool = False,
    ) -> None:
        self.layer_kind = layer_kind
        self.label = label
        self.is_lower_horizon = is_lower_horizon
        self.nodes: List[TopologyLayoutNode] = []

    def add_node(self, node: TopologyLayoutNode) -> None:
        """Append *node* to this layer."""
        self.nodes.append(node)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this layer."""
        return {
            "layer_kind": self.layer_kind.value,
            "label": self.label,
            "is_lower_horizon": self.is_lower_horizon,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    def __repr__(self) -> str:
        return (
            f"TopologyLayoutLayer(layer_kind={self.layer_kind.value!r}, "
            f"label={self.label!r}, nodes={len(self.nodes)})"
        )


# ---------------------------------------------------------------------------
# Constellation layout (top-level structure)
# ---------------------------------------------------------------------------

class TopologyConstellationLayout:
    """PR-11: Top-level topology / constellation layout.

    Produced by :func:`build_constellation_layout` from a
    :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`.

    Attributes
    ----------
    layout_id:
        Unique identifier for this layout instance.
    layout_authority:
        Always :data:`TOPOLOGY_LAYOUT_AUTHORITY` — identifies the canonical
        PR-11 builder.
    readiness_label:
        Readiness qualifier from the view-model
        (``"canonical"`` / ``"degraded"`` / ``"partial"`` / ``"unavailable"``).
    is_authoritative:
        ``True`` only when the underlying view-model is canonical.  Callers
        must not treat a non-authoritative layout as representing confirmed
        topology state.
    is_degraded:
        ``True`` when the underlying readiness is ``degraded``.
    is_partial:
        ``True`` when the underlying readiness is ``partial``.
    is_unavailable:
        ``True`` when the underlying readiness is ``unavailable``.
    primary_layer:
        The :attr:`~TopologyLayerKind.primary` layer holding the canonical
        provider / topology root node.
    support_layer:
        The :attr:`~TopologyLayerKind.support` layer holding routing peers and
        support nodes.
    lower_horizon_layer:
        The :attr:`~TopologyLayerKind.lower_horizon` layer holding the OneAPI
        integration node.  Always present and always structurally separate.
    relations:
        List of :class:`TopologyLayoutRelation` objects expressing relationships
        between nodes across all layers.
    """

    def __init__(
        self,
        *,
        layout_id: str,
        readiness_label: str,
        is_authoritative: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        primary_layer: TopologyLayoutLayer,
        support_layer: TopologyLayoutLayer,
        lower_horizon_layer: TopologyLayoutLayer,
        relations: Optional[List[TopologyLayoutRelation]] = None,
    ) -> None:
        self.layout_id = layout_id
        self.layout_authority: str = TOPOLOGY_LAYOUT_AUTHORITY
        self.readiness_label = readiness_label
        self.is_authoritative = is_authoritative
        self.is_degraded = is_degraded
        self.is_partial = is_partial
        self.is_unavailable = is_unavailable
        self.primary_layer = primary_layer
        self.support_layer = support_layer
        self.lower_horizon_layer = lower_horizon_layer
        self.relations: List[TopologyLayoutRelation] = relations or []

    @property
    def layers(self) -> List[TopologyLayoutLayer]:
        """Return all three layers in top-to-bottom display order."""
        return [self.primary_layer, self.support_layer, self.lower_horizon_layer]

    @property
    def all_nodes(self) -> List[TopologyLayoutNode]:
        """Return every node across all layers in layer order."""
        result: List[TopologyLayoutNode] = []
        for layer in self.layers:
            result.extend(layer.nodes)
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the full layout."""
        return {
            "layout_id": self.layout_id,
            "layout_authority": self.layout_authority,
            "readiness_label": self.readiness_label,
            "is_authoritative": self.is_authoritative,
            "is_degraded": self.is_degraded,
            "is_partial": self.is_partial,
            "is_unavailable": self.is_unavailable,
            "primary_layer": self.primary_layer.to_dict(),
            "support_layer": self.support_layer.to_dict(),
            "lower_horizon_layer": self.lower_horizon_layer.to_dict(),
            "relations": [r.to_dict() for r in self.relations],
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string of the full layout."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:
        return (
            f"TopologyConstellationLayout("
            f"readiness_label={self.readiness_label!r}, "
            f"is_authoritative={self.is_authoritative}, "
            f"primary_nodes={len(self.primary_layer.nodes)}, "
            f"support_nodes={len(self.support_layer.nodes)}, "
            f"lower_horizon_nodes={len(self.lower_horizon_layer.nodes)}, "
            f"relations={len(self.relations)})"
        )


# ---------------------------------------------------------------------------
# Internal builder helpers
# ---------------------------------------------------------------------------

def _safe_str(val: Any) -> Optional[str]:
    """Return *val* as a string, or ``None`` if it is falsy."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _readiness_from_vm(vm: Any) -> str:
    """Extract a canonical readiness label string from a view-model."""
    state = getattr(vm, "readiness_state", None)
    if state is None:
        return "unknown"
    if hasattr(state, "value"):
        return str(state.value)
    return str(state)


def _readiness_from_dict(d: Dict[str, Any]) -> str:
    """Extract readiness label from a plain dict view-model."""
    state = d.get("readiness_state", "unknown")
    if hasattr(state, "value"):
        return str(state.value)
    return str(state) if state else "unknown"


def _build_primary_layer(
    *,
    readiness_label: str,
    is_authoritative: bool,
    provider_id: Optional[str],
    model_id: Optional[str],
    route_reason: Optional[str],
    routing_authority: Optional[str],
    legacy_fallback: bool,
) -> TopologyLayoutLayer:
    """Build the primary topology layer from extracted view-model fields."""
    layer = TopologyLayoutLayer(
        layer_kind=TopologyLayerKind.primary,
        label="Primary Topology / Provider",
        is_lower_horizon=False,
    )

    if provider_id or model_id:
        label_parts = []
        if provider_id:
            label_parts.append(provider_id)
        if model_id:
            label_parts.append(model_id)
        node_label = " / ".join(label_parts) if label_parts else "primary-provider"

        node = TopologyLayoutNode(
            node_id="primary_provider_node",
            kind=TopologyNodeKind.primary_provider,
            label=node_label,
            readiness_label=readiness_label,
            is_available=(readiness_label in ("canonical", "partial")),
            is_authoritative=is_authoritative and not legacy_fallback,
            provider_id=provider_id,
            model_id=model_id,
            extra={
                "route_reason": route_reason,
                "routing_authority_source": routing_authority,
                "legacy_fallback": legacy_fallback,
            },
        )
        layer.add_node(node)
    # If neither provider_id nor model_id is available, primary layer is empty
    # (topology unavailable / partial with no data) — callers should check
    # ``not layer.nodes`` to detect this case.
    return layer


def _build_support_layer(
    *,
    readiness_label: str,
    is_authoritative: bool,
    provider_routing: Any,
) -> TopologyLayoutLayer:
    """Build the support/routing-peer layer from provider routing summary."""
    layer = TopologyLayoutLayer(
        layer_kind=TopologyLayerKind.support,
        label="Routing / Support Path",
        is_lower_horizon=False,
    )

    if provider_routing is None:
        return layer

    # provider_routing may be a DesktopProviderRoutingSummary or plain dict
    if hasattr(provider_routing, "selected_provider"):
        selected = _safe_str(provider_routing.selected_provider)
        vendor = _safe_str(getattr(provider_routing, "vendor_source", None))
        legacy = bool(getattr(provider_routing, "legacy_routing_fallback_active", False))
        available = bool(getattr(provider_routing, "provider_available", False))
        route_reason = _safe_str(getattr(provider_routing, "route_reason", None))
    else:
        _d = dict(provider_routing) if hasattr(provider_routing, "keys") else {}
        selected = _safe_str(_d.get("selected_provider"))
        vendor = _safe_str(_d.get("vendor_source"))
        legacy = bool(_d.get("legacy_routing_fallback_active", False))
        available = bool(_d.get("provider_available", False))
        route_reason = _safe_str(_d.get("route_reason"))

    if selected or vendor:
        label_parts = []
        if selected:
            label_parts.append(selected)
        if vendor and vendor != selected:
            label_parts.append(f"[{vendor}]")
        node_label = " ".join(label_parts) if label_parts else "routing-peer"

        kind = (
            TopologyNodeKind.routing_peer
            if not legacy
            else TopologyNodeKind.support_node
        )
        node = TopologyLayoutNode(
            node_id="routing_peer_node",
            kind=kind,
            label=node_label,
            readiness_label=readiness_label,
            is_available=available,
            is_authoritative=is_authoritative and not legacy,
            provider_id=selected,
            model_id=None,
            extra={
                "vendor_source": vendor,
                "legacy_routing_fallback_active": legacy,
                "route_reason": route_reason,
            },
        )
        layer.add_node(node)

    return layer


def _build_lower_horizon_layer(*, oneapi_horizon: Any) -> TopologyLayoutLayer:
    """Build the OneAPI lower-horizon layer.

    This layer is always present and always marked ``is_lower_horizon=True``.
    The node placed here is never authoritative in the topology / routing sense.
    """
    layer = TopologyLayoutLayer(
        layer_kind=TopologyLayerKind.lower_horizon,
        label="OneAPI Lower-Horizon Integration",
        is_lower_horizon=True,
    )

    if oneapi_horizon is None:
        # Always add a placeholder lower-horizon node so the layer is never empty
        layer.add_node(TopologyLayoutNode(
            node_id="oneapi_horizon_node",
            kind=TopologyNodeKind.oneapi_horizon,
            label="OneAPI (lower-horizon)",
            readiness_label="lower_horizon",
            is_available=False,
            is_authoritative=False,  # always False — OneAPI is never a routing peer
            provider_id=None,
            model_id=None,
        ))
        return layer

    # Unpack DesktopOneAPIHorizonSummary or plain dict
    if hasattr(oneapi_horizon, "provider_id"):
        provider_id = _safe_str(oneapi_horizon.provider_id)
        system_layer = _safe_str(getattr(oneapi_horizon, "system_layer", None))
        available = bool(getattr(oneapi_horizon, "available", False))
        is_lower_horizon_only = bool(
            getattr(oneapi_horizon, "is_lower_horizon_only", True)
        )
    else:
        _d = dict(oneapi_horizon) if hasattr(oneapi_horizon, "keys") else {}
        provider_id = _safe_str(_d.get("provider_id"))
        system_layer = _safe_str(_d.get("system_layer"))
        available = bool(_d.get("available", False))
        is_lower_horizon_only = bool(_d.get("is_lower_horizon_only", True))

    label_parts = ["OneAPI"]
    if provider_id:
        label_parts.append(f"({provider_id})")
    label_parts.append("[lower-horizon]")
    node_label = " ".join(label_parts)

    node = TopologyLayoutNode(
        node_id="oneapi_horizon_node",
        kind=TopologyNodeKind.oneapi_horizon,
        label=node_label,
        readiness_label="lower_horizon",
        is_available=available,
        is_authoritative=False,  # always False — OneAPI is NEVER a routing peer
        provider_id=provider_id,
        model_id=None,
        extra={
            "system_layer": system_layer,
            "is_lower_horizon_only": is_lower_horizon_only,
        },
    )
    layer.add_node(node)
    return layer


def _build_relations(
    *,
    is_authoritative: bool,
    is_degraded: bool,
    primary_layer: TopologyLayoutLayer,
    support_layer: TopologyLayoutLayer,
    lower_horizon_layer: TopologyLayoutLayer,
) -> List[TopologyLayoutRelation]:
    """Build the relationship list linking nodes across layers."""
    relations: List[TopologyLayoutRelation] = []

    primary_nodes = primary_layer.nodes
    support_nodes = support_layer.nodes
    lower_horizon_nodes = lower_horizon_layer.nodes

    # Primary → routing peer relation
    if primary_nodes and support_nodes:
        rel_kind = (
            TopologyRelationKind.canonical_route
            if is_authoritative and not is_degraded
            else TopologyRelationKind.fallback_path
            if is_degraded
            else TopologyRelationKind.support_path
        )
        label = (
            "canonical route"
            if rel_kind == TopologyRelationKind.canonical_route
            else "legacy fallback"
            if rel_kind == TopologyRelationKind.fallback_path
            else "support path"
        )
        relations.append(TopologyLayoutRelation(
            source_id=primary_nodes[0].node_id,
            target_id=support_nodes[0].node_id,
            kind=rel_kind,
            label=label,
            is_authoritative=(rel_kind == TopologyRelationKind.canonical_route),
        ))

    # Primary → lower-horizon (OneAPI) link
    # This link is always present and always lower_horizon_link (never canonical)
    if primary_nodes and lower_horizon_nodes:
        relations.append(TopologyLayoutRelation(
            source_id=primary_nodes[0].node_id,
            target_id=lower_horizon_nodes[0].node_id,
            kind=TopologyRelationKind.lower_horizon_link,
            label="lower-horizon integration (not a routing peer)",
            is_authoritative=False,
        ))
    elif lower_horizon_nodes:
        # If no primary node, still record the lower-horizon node as standalone
        # but without a relation (it is structurally isolated)
        pass

    return relations


# ---------------------------------------------------------------------------
# Public builder — main entry point
# ---------------------------------------------------------------------------

def build_constellation_layout(vm: Any) -> TopologyConstellationLayout:
    """Build a :class:`TopologyConstellationLayout` from a view-model.

    Parameters
    ----------
    vm:
        A :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`
        instance, or a plain ``dict`` produced by
        :meth:`~core.desktop_consumption_adapter.DesktopClientViewModel.to_dict`,
        or ``None`` for a safe unavailable layout.

    Returns
    -------
    TopologyConstellationLayout
        A fully-populated constellation layout.  Never raises.

    Readiness semantics
    -------------------
    - ``canonical`` → primary node is authoritative; relations use
      :attr:`~TopologyRelationKind.canonical_route`.
    - ``degraded`` → primary node is NOT authoritative; relations use
      :attr:`~TopologyRelationKind.fallback_path`; ``is_degraded=True``.
    - ``partial`` → primary node may exist but partial data; marked not
      fully authoritative.
    - ``unavailable`` → primary layer is empty; all nodes unavailable.
    """
    layout_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Handle None / missing view-model
    # ------------------------------------------------------------------
    if vm is None:
        primary = TopologyLayoutLayer(
            layer_kind=TopologyLayerKind.primary,
            label="Primary Topology / Provider",
            is_lower_horizon=False,
        )
        support = TopologyLayoutLayer(
            layer_kind=TopologyLayerKind.support,
            label="Routing / Support Path",
            is_lower_horizon=False,
        )
        lower = _build_lower_horizon_layer(oneapi_horizon=None)
        return TopologyConstellationLayout(
            layout_id=layout_id,
            readiness_label="unavailable",
            is_authoritative=False,
            is_degraded=False,
            is_partial=False,
            is_unavailable=True,
            primary_layer=primary,
            support_layer=support,
            lower_horizon_layer=lower,
            relations=[],
        )

    # ------------------------------------------------------------------
    # Extract fields from view-model (supports both attribute and dict)
    # ------------------------------------------------------------------
    if hasattr(vm, "readiness_state"):
        # DesktopClientViewModel instance
        readiness_label = _readiness_from_vm(vm)
        is_canonical: bool = bool(getattr(vm, "is_canonical", False))
        is_degraded: bool = bool(getattr(vm, "is_degraded", False))
        is_partial: bool = bool(getattr(vm, "is_partial", False))
        is_unavailable: bool = bool(getattr(vm, "is_unavailable", False))
        provider_id = _safe_str(getattr(vm, "topology_provider_id", None))
        model_id = _safe_str(getattr(vm, "topology_primary_model_id", None))
        route_reason = _safe_str(getattr(vm, "topology_route_reason", None))
        routing_auth = _safe_str(getattr(vm, "routing_authority_source", None))
        topology_legacy = bool(getattr(vm, "topology_legacy_fallback_active", False))
        provider_routing = getattr(vm, "provider_routing", None)
        oneapi_horizon = getattr(vm, "oneapi_horizon", None)
    else:
        # Plain dict view-model
        _d: Dict[str, Any] = dict(vm) if hasattr(vm, "keys") else {}
        readiness_label = _readiness_from_dict(_d)
        is_canonical = bool(_d.get("is_canonical", False))
        is_degraded = bool(_d.get("is_degraded", False))
        is_partial = bool(_d.get("is_partial", False))
        is_unavailable = bool(_d.get("is_unavailable", False))
        provider_id = _safe_str(_d.get("topology_provider_id"))
        model_id = _safe_str(_d.get("topology_primary_model_id"))
        route_reason = _safe_str(_d.get("topology_route_reason"))
        routing_auth = _safe_str(_d.get("routing_authority_source"))
        topology_legacy = bool(_d.get("topology_legacy_fallback_active", False))
        provider_routing = _d.get("provider_routing")
        oneapi_horizon = _d.get("oneapi_horizon")

    # ------------------------------------------------------------------
    # Determine authoritative flag: canonical AND not any legacy fallback
    # ------------------------------------------------------------------
    is_authoritative = is_canonical and not topology_legacy and not is_degraded

    # ------------------------------------------------------------------
    # Build layers
    # ------------------------------------------------------------------
    primary_layer = _build_primary_layer(
        readiness_label=readiness_label,
        is_authoritative=is_authoritative,
        provider_id=provider_id,
        model_id=model_id,
        route_reason=route_reason,
        routing_authority=routing_auth,
        legacy_fallback=topology_legacy,
    )
    support_layer = _build_support_layer(
        readiness_label=readiness_label,
        is_authoritative=is_authoritative,
        provider_routing=provider_routing,
    )
    lower_horizon_layer = _build_lower_horizon_layer(oneapi_horizon=oneapi_horizon)

    # ------------------------------------------------------------------
    # Build relations
    # ------------------------------------------------------------------
    relations = _build_relations(
        is_authoritative=is_authoritative,
        is_degraded=is_degraded,
        primary_layer=primary_layer,
        support_layer=support_layer,
        lower_horizon_layer=lower_horizon_layer,
    )

    return TopologyConstellationLayout(
        layout_id=layout_id,
        readiness_label=readiness_label,
        is_authoritative=is_authoritative,
        is_degraded=is_degraded,
        is_partial=is_partial,
        is_unavailable=is_unavailable,
        primary_layer=primary_layer,
        support_layer=support_layer,
        lower_horizon_layer=lower_horizon_layer,
        relations=relations,
    )
