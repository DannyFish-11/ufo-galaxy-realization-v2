"""
windows_client/status_board_v2/topology_renderer.py
====================================================
PR-12: Topology rendering and visual semantics polish.

Consumes the :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`
produced by the PR-11 builder and renders it as a polished, readable
ASCII/ANSI output surface with clear visual semantics.

Design constraints
------------------
- **Layout-driven only** — the renderer always consumes a
  :class:`TopologyConstellationLayout` (or an equivalent plain dict from
  :meth:`~TopologyConstellationLayout.to_dict`); it never bypasses the
  PR-11 layout model to access the underlying view-model or raw integration
  payload directly.
- **Visually distinct readiness states** — ``canonical``, ``degraded``,
  ``partial``, and ``unavailable`` must be unambiguously distinguishable
  at a glance.  Degraded/fallback nodes must not look like canonical
  authority.
- **OneAPI always lower-horizon** — the OneAPI block is rendered in a
  structurally and visually isolated section, never elevated to look like
  a canonical routing peer.
- **Node-kind-aware** — each node kind has its own symbol and colour:
  ``primary_provider`` (★), ``routing_peer`` (✧), ``support_node`` (◇),
  ``oneapi_horizon`` (⬡).
- **Relation-kind-aware** — each relation kind has its own edge symbol:
  ``canonical_route`` (━━▶), ``fallback_path`` (╌╌▷), ``support_path``
  (──▷), ``lower_horizon_link`` (╌╌⬡).
- **Read-only** — this renderer never sends commands or modifies state.
- **Graceful** — all rendering paths handle ``None`` / minimal layouts
  without raising.

Visual structure
----------------
::

    ╔═ Topology Constellation ══════════════════════════╗
    ║  ● CANONICAL — fully authoritative topology       ║
    ╠═ PRIMARY ══════════════════════════════════════════╣
    ║  ★  primary_provider  provider-x  canonical       ║
    ╠═ SUPPORT ══════════════════════════════════════════╣
    ║  ✧  routing_peer  provider-y  canonical            ║
    ╠═ RELATIONS ════════════════════════════════════════╣
    ║  node-0 ━━▶ node-1  canonical route               ║
    ╠─ LOWER-HORIZON ────────────────────────────────────╣
    ║  ⬡  oneapi_horizon  lower-horizon  [not a peer]   ║
    ╚════════════════════════════════════════════════════╝

Readiness visual key
--------------------
``●``  canonical   — green  — fully authoritative
``◑``  degraded    — yellow — legacy fallback active, NOT authoritative
``◔``  partial     — cyan   — canonical source but incomplete data
``○``  unavailable — red    — no topology data available

Usage
-----
::

    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from core.desktop_consumption_adapter import adapt_integration_payload

    vm = adapt_integration_payload(payload)
    layout = build_constellation_layout(vm)
    renderer = TopologyRenderer()
    print(renderer.render_layout(layout))

See ``docs/TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md`` for full design rationale.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ._ansi import BOLD, DIM, RESET, c
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
# PR-12: Renderer authority sentinel
# ---------------------------------------------------------------------------

#: Sentinel string that identifies the topology renderer introduced in PR-12.
#: Downstream consumers can check this value to confirm that a rendered
#: surface was produced by the canonical PR-12 renderer rather than an ad-hoc
#: formatter.
TOPOLOGY_RENDERER_AUTHORITY: str = (
    "windows_client.status_board_v2.topology_renderer.TopologyRenderer"
)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_C_CANONICAL = "\033[32m"       # green  — canonical / healthy
_C_DEGRADED = "\033[33m"        # yellow — degraded / legacy fallback
_C_PARTIAL = "\033[36m"         # cyan   — partial / incomplete
_C_UNAVAILABLE = "\033[31m"     # red    — unavailable / no data
_C_UNKNOWN = "\033[90m"         # grey   — unknown / unrecognised
_C_FALLBACK_WARN = "\033[33m"   # yellow — legacy fallback warning label
_C_ONEAPI = "\033[35m"          # magenta — OneAPI lower-horizon block
_C_DIM = "\033[90m"             # dim grey — secondary / metadata
_C_LABEL = "\033[37m"           # white  — field labels
_C_SUPPORT = "\033[34m"         # blue   — support / routing-peer nodes
_C_EDGE_CANON = "\033[32m"      # green  — canonical-route edge
_C_EDGE_FALLBACK = "\033[33m"   # yellow — fallback-path edge
_C_EDGE_SUPPORT = "\033[34m"    # blue   — support-path edge
_C_EDGE_HORIZON = "\033[35m"    # magenta — lower-horizon-link edge

# ---------------------------------------------------------------------------
# Readiness display metadata
# ---------------------------------------------------------------------------

#: Symbol for each readiness label.
_READINESS_SYMBOL: Dict[str, str] = {
    "canonical":   "●",
    "degraded":    "◑",
    "partial":     "◔",
    "unavailable": "○",
    "lower_horizon": "⬡",
    "unknown":     "?",
}

#: ANSI colour code for each readiness label.
_READINESS_COLOUR: Dict[str, str] = {
    "canonical":   _C_CANONICAL,
    "degraded":    _C_DEGRADED,
    "partial":     _C_PARTIAL,
    "unavailable": _C_UNAVAILABLE,
    "lower_horizon": _C_ONEAPI,
    "unknown":     _C_UNKNOWN,
}

#: One-line description for each readiness label.
_READINESS_DESCRIPTION: Dict[str, str] = {
    "canonical":   "CANONICAL   — fully authoritative topology",
    "degraded":    "DEGRADED    — legacy fallback active (NOT authoritative)",
    "partial":     "PARTIAL     — canonical source present, some components missing",
    "unavailable": "UNAVAILABLE — no topology data available",
    "unknown":     "UNKNOWN     — readiness could not be determined",
}

# ---------------------------------------------------------------------------
# Node-kind symbols and colours
# ---------------------------------------------------------------------------

#: Symbol shown next to each node kind.
_NODE_KIND_SYMBOL: Dict[str, str] = {
    TopologyNodeKind.primary_provider.value: "★",
    TopologyNodeKind.routing_peer.value:     "✧",
    TopologyNodeKind.support_node.value:     "◇",
    TopologyNodeKind.oneapi_horizon.value:   "⬡",
}

#: Colour used to render the symbol/label for each node kind.
_NODE_KIND_COLOUR: Dict[str, str] = {
    TopologyNodeKind.primary_provider.value: _C_CANONICAL,
    TopologyNodeKind.routing_peer.value:     _C_SUPPORT,
    TopologyNodeKind.support_node.value:     _C_SUPPORT,
    TopologyNodeKind.oneapi_horizon.value:   _C_ONEAPI,
}

# ---------------------------------------------------------------------------
# Relation-kind symbols and colours
# ---------------------------------------------------------------------------

#: ASCII edge symbol for each relation kind.
_RELATION_EDGE: Dict[str, str] = {
    TopologyRelationKind.canonical_route.value:    "━━▶",
    TopologyRelationKind.fallback_path.value:      "╌╌▷",
    TopologyRelationKind.support_path.value:       "──▷",
    TopologyRelationKind.lower_horizon_link.value: "╌╌⬡",
}

#: Colour for each relation kind's edge rendering.
_RELATION_COLOUR: Dict[str, str] = {
    TopologyRelationKind.canonical_route.value:    _C_EDGE_CANON,
    TopologyRelationKind.fallback_path.value:      _C_EDGE_FALLBACK,
    TopologyRelationKind.support_path.value:       _C_EDGE_SUPPORT,
    TopologyRelationKind.lower_horizon_link.value: _C_EDGE_HORIZON,
}

# Layout width constant for box-drawing
_BOX_WIDTH = 52


def _rule_top(title: str = "") -> str:
    fill = _BOX_WIDTH - len(title) - 4
    return f"  ╔═ {title} {'═' * max(fill, 1)}╗"


def _rule_sep(title: str = "", heavy: bool = True) -> str:
    ch = "═" if heavy else "─"
    eq = "╠" if heavy else "╟"
    fill = _BOX_WIDTH - len(title) - 4
    return f"  {eq}{ch} {title} {ch * max(fill, 1)}╣"


def _rule_bot(heavy: bool = True) -> str:
    ch = "═" if heavy else "─"
    end = "╝" if heavy else "╜"
    return f"  ╚{ch * (_BOX_WIDTH - 1)}{end}"


def _box_line(content: str) -> str:
    return f"  ║  {content}"


def _trunc(s: Optional[str], maxlen: int = 36) -> str:
    if not s:
        return "(none)"
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _node_readiness_colour(node: Any) -> str:
    """Return the ANSI colour appropriate for *node* based on readiness and authority."""
    readiness = str(getattr(node, "readiness_label", "") or "")
    # Override to degraded colour if not authoritative (applies to any non-canonical node)
    if not bool(getattr(node, "is_authoritative", False)):
        if readiness == "canonical":
            # Partial override — canonical label but not fully authoritative (e.g. partial)
            return _C_PARTIAL
        return _READINESS_COLOUR.get(readiness, _C_UNKNOWN)
    return _READINESS_COLOUR.get(readiness, _C_UNKNOWN)


def _render_node_line(node: Any) -> str:
    """Render a single node as a display line.

    The node may be a :class:`TopologyLayoutNode` instance or a plain dict.
    """
    if isinstance(node, dict):
        kind_val = str(node.get("kind", ""))
        label = str(node.get("label", ""))
        readiness_label = str(node.get("readiness_label", "unknown"))
        is_auth = bool(node.get("is_authoritative", False))
        provider_id = node.get("provider_id")
        node_id = str(node.get("node_id", ""))
    else:
        kind_val = str(getattr(node, "kind", {}) or "")
        if hasattr(node.kind, "value"):
            kind_val = node.kind.value
        label = str(getattr(node, "label", "") or "")
        readiness_label = str(getattr(node, "readiness_label", "unknown") or "unknown")
        is_auth = bool(getattr(node, "is_authoritative", False))
        provider_id = getattr(node, "provider_id", None)
        node_id = str(getattr(node, "node_id", "") or "")

    sym = _NODE_KIND_SYMBOL.get(kind_val, "·")
    kind_col = _NODE_KIND_COLOUR.get(kind_val, _C_DIM)

    # Readiness badge
    r_sym = _READINESS_SYMBOL.get(readiness_label, "?")
    r_col = _READINESS_COLOUR.get(readiness_label, _C_UNKNOWN)

    # Authority tag — make it visually obvious when NOT authoritative
    if is_auth:
        auth_tag = c("[auth]", _C_CANONICAL)
    else:
        if readiness_label == "lower_horizon":
            auth_tag = c("[lower-horizon]", _C_ONEAPI)
        elif readiness_label in ("degraded", "unavailable"):
            auth_tag = c("[NOT-auth]", _C_FALLBACK_WARN)
        else:
            auth_tag = c("[not-auth]", _C_DIM)

    pid_str = f"  {c(_trunc(provider_id, 20), _C_DIM)}" if provider_id else ""
    label_str = _trunc(label, 28)

    return (
        _box_line(
            f"{c(sym, kind_col)}  "
            f"{c(label_str, kind_col)}{pid_str}  "
            f"{c(r_sym, r_col)}  {auth_tag}"
        )
    )


def _render_relation_line(rel: Any) -> str:
    """Render a single relation as a display line."""
    if isinstance(rel, dict):
        kind_val = str(rel.get("kind", ""))
        source_id = str(rel.get("source_id", ""))
        target_id = str(rel.get("target_id", ""))
        label = str(rel.get("label", ""))
        is_auth = bool(rel.get("is_authoritative", False))
    else:
        kind_val = str(getattr(rel, "kind", {}) or "")
        if hasattr(rel.kind, "value"):
            kind_val = rel.kind.value
        source_id = str(getattr(rel, "source_id", "") or "")
        target_id = str(getattr(rel, "target_id", "") or "")
        label = str(getattr(rel, "label", "") or "")
        is_auth = bool(getattr(rel, "is_authoritative", False))

    edge = _RELATION_EDGE.get(kind_val, "──▷")
    edge_col = _RELATION_COLOUR.get(kind_val, _C_DIM)

    auth_mark = c("✓", _C_CANONICAL) if is_auth else c("✗", _C_DIM)
    label_str = _trunc(label, 26)

    return _box_line(
        f"{c(_trunc(source_id, 14), _C_DIM)}  "
        f"{c(edge, edge_col)}  "
        f"{c(_trunc(target_id, 14), _C_DIM)}  "
        f"{c(label_str, edge_col)}  "
        f"{auth_mark}"
    )


class TopologyRenderer:
    """PR-12: Topology constellation renderer.

    Renders a :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`
    (produced by the PR-11 builder) as a polished ASCII/ANSI surface.

    Visual semantics
    ----------------
    - Readiness states ``canonical``, ``degraded``, ``partial``, and
      ``unavailable`` are rendered with distinct symbols, colours, and labels
      so they are unambiguous at a glance.
    - ``degraded`` / ``fallback`` nodes are explicitly labelled
      ``[NOT-auth]`` to prevent them from being mistaken for canonical
      authority.
    - ``OneAPI`` nodes are always rendered in the ``LOWER-HORIZON`` section
      with a distinct magenta colour and ``[lower-horizon]`` tag; they are
      never elevated or styled like canonical routing peers.
    - Each node kind has a unique symbol: ★ primary, ✧ routing-peer,
      ◇ support, ⬡ OneAPI.
    - Each relation kind has a unique edge: ━━▶ canonical, ╌╌▷ fallback,
      ──▷ support, ╌╌⬡ lower-horizon.

    READ-ONLY — this class only produces display strings.
    """

    # ------------------------------------------------------------------
    # Primary entry points
    # ------------------------------------------------------------------

    def render_layout(self, layout: Any) -> str:
        """Render a :class:`TopologyConstellationLayout` to a display string.

        Parameters
        ----------
        layout:
            A :class:`TopologyConstellationLayout` instance, or ``None``
            to produce a safe unavailable frame.

        Returns
        -------
        str
            Multi-line string ready for ``print()``.
        """
        if layout is None:
            return self._render_unavailable_frame("no layout available")

        # Extract top-level fields (supports both attribute and dict access)
        if hasattr(layout, "readiness_label"):
            readiness_label = str(getattr(layout, "readiness_label", "unknown") or "unknown")
            is_authoritative = bool(getattr(layout, "is_authoritative", False))
            is_degraded = bool(getattr(layout, "is_degraded", False))
            is_partial = bool(getattr(layout, "is_partial", False))
            is_unavailable = bool(getattr(layout, "is_unavailable", False))
            layout_authority = str(getattr(layout, "layout_authority", "") or "")
            layout_id = str(getattr(layout, "layout_id", "") or "")
            primary_layer = getattr(layout, "primary_layer", None)
            support_layer = getattr(layout, "support_layer", None)
            lower_horizon_layer = getattr(layout, "lower_horizon_layer", None)
            relations = list(getattr(layout, "relations", []) or [])
        elif isinstance(layout, dict):
            return self.render_layout_dict(layout)
        else:
            return self._render_unavailable_frame("unrecognised layout object")

        return self._render(
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            layout_authority=layout_authority,
            layout_id=layout_id,
            primary_layer=primary_layer,
            support_layer=support_layer,
            lower_horizon_layer=lower_horizon_layer,
            relations=relations,
        )

    def render_layout_dict(self, layout_dict: Dict[str, Any]) -> str:
        """Render from a plain dict (e.g. output of ``layout.to_dict()``).

        Parameters
        ----------
        layout_dict:
            A dict as returned by
            :meth:`~TopologyConstellationLayout.to_dict`.

        Returns
        -------
        str
            Multi-line string ready for ``print()``.
        """
        if not layout_dict:
            return self._render_unavailable_frame("empty layout dict")

        readiness_label = str(layout_dict.get("readiness_label") or "unknown")
        is_authoritative = bool(layout_dict.get("is_authoritative", False))
        is_degraded = bool(layout_dict.get("is_degraded", False))
        is_partial = bool(layout_dict.get("is_partial", False))
        is_unavailable = bool(layout_dict.get("is_unavailable", False))
        layout_authority = str(layout_dict.get("layout_authority") or "")
        layout_id = str(layout_dict.get("layout_id") or "")

        # Build lightweight proxy layers from nested dicts
        primary_layer = _LayerDictProxy(layout_dict.get("primary_layer") or {})
        support_layer = _LayerDictProxy(layout_dict.get("support_layer") or {})
        lower_horizon_layer = _LayerDictProxy(
            layout_dict.get("lower_horizon_layer") or {}
        )
        relations_raw = layout_dict.get("relations") or []
        relations = [
            _RelationDictProxy(r) for r in relations_raw if isinstance(r, dict)
        ]

        return self._render(
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            layout_authority=layout_authority,
            layout_id=layout_id,
            primary_layer=primary_layer,
            support_layer=support_layer,
            lower_horizon_layer=lower_horizon_layer,
            relations=relations,
        )

    # ------------------------------------------------------------------
    # Internal rendering
    # ------------------------------------------------------------------

    def _render(  # noqa: PLR0912
        self,
        *,
        readiness_label: str,
        is_authoritative: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        layout_authority: str,
        layout_id: str,
        primary_layer: Any,
        support_layer: Any,
        lower_horizon_layer: Any,
        relations: List[Any],
    ) -> str:
        """Core rendering logic for a topology constellation layout."""
        sym = _READINESS_SYMBOL.get(readiness_label, "?")
        col = _READINESS_COLOUR.get(readiness_label, _C_UNKNOWN)
        desc = _READINESS_DESCRIPTION.get(
            readiness_label, readiness_label.upper()
        )

        lines: List[str] = []

        # ── Outer frame top ───────────────────────────────────────────
        lines.append(c(_rule_top("Topology Constellation"), BOLD))

        # ── Readiness banner ─────────────────────────────────────────
        lines.append(_box_line(c(f"{sym}  {desc}", col)))

        # ── Degraded/partial warning banner ──────────────────────────
        if is_degraded:
            lines.append(
                _box_line(
                    c(
                        "  ⚠  DEGRADED — legacy fallback active; "
                        "topology is NOT authoritative",
                        _C_FALLBACK_WARN,
                    )
                )
            )
        elif is_partial:
            lines.append(
                _box_line(
                    c(
                        "  ⚠  PARTIAL — canonical source present but "
                        "some components are missing",
                        _C_PARTIAL,
                    )
                )
            )
        elif is_unavailable:
            lines.append(
                _box_line(c("  ✗  UNAVAILABLE — no topology data", _C_UNAVAILABLE))
            )

        # ── PRIMARY layer ─────────────────────────────────────────────
        lines.append(c(_rule_sep("PRIMARY", heavy=True), BOLD))
        primary_nodes = _get_nodes(primary_layer)
        if primary_nodes:
            for node in primary_nodes:
                lines.append(_render_node_line(node))
        else:
            lines.append(_box_line(c("  (no primary provider node)", _C_UNKNOWN)))

        # ── SUPPORT layer ─────────────────────────────────────────────
        lines.append(c(_rule_sep("SUPPORT", heavy=True), BOLD))
        support_nodes = _get_nodes(support_layer)
        if support_nodes:
            for node in support_nodes:
                lines.append(_render_node_line(node))
        else:
            lines.append(_box_line(c("  (no support / routing-peer nodes)", _C_DIM)))

        # ── RELATIONS ─────────────────────────────────────────────────
        if relations:
            lines.append(c(_rule_sep("RELATIONS", heavy=False), _C_DIM))
            for rel in relations:
                lines.append(_render_relation_line(rel))

        # ── LOWER-HORIZON section (always present, always distinct) ───
        lines.append(
            c(
                _rule_sep("LOWER-HORIZON  ·  OneAPI  ·  not a routing peer", heavy=False),
                _C_ONEAPI,
            )
        )
        lower_nodes = _get_nodes(lower_horizon_layer)
        if lower_nodes:
            for node in lower_nodes:
                lines.append(_render_node_line(node))
        else:
            lines.append(_box_line(c("  (no OneAPI horizon data)", _C_DIM)))

        # ── Footer ────────────────────────────────────────────────────
        lines.append(c(_rule_bot(heavy=True), BOLD))

        # Authority / ID footer lines
        if layout_authority:
            lines.append(_box_line(c(f"Layout authority : {layout_authority}", _C_DIM)))
        if layout_id:
            lines.append(_box_line(c(f"Layout ID        : {layout_id}", _C_DIM)))
        lines.append(_box_line(c(f"Renderer         : {TOPOLOGY_RENDERER_AUTHORITY}", _C_DIM)))

        return "\n".join(lines)

    def _render_unavailable_frame(self, reason: str) -> str:
        """Return a minimal safe 'unavailable' frame."""
        sym = _READINESS_SYMBOL["unavailable"]
        col = _C_UNAVAILABLE
        lines = [
            c(_rule_top("Topology Constellation"), BOLD),
            _box_line(c(f"{sym}  UNAVAILABLE — {reason}", col)),
            _box_line(c("  (no TopologyConstellationLayout available)", _C_DIM)),
            _box_line(c(f"Renderer : {TOPOLOGY_RENDERER_AUTHORITY}", _C_DIM)),
            c(_rule_bot(), BOLD),
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal proxy helpers for dict-based access
# ---------------------------------------------------------------------------


class _KindProxy:
    """Named proxy that holds a ``value`` attribute for a kind enum string.

    Used by :class:`_NodeDictProxy` and :class:`_RelationDictProxy` to
    provide the same ``.kind.value`` access pattern as real enum instances.
    """

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class _NodeDictProxy:
    """Lightweight proxy that wraps a node dict for use in rendering."""

    def __init__(self, d: Dict[str, Any]) -> None:
        self.node_id: str = str(d.get("node_id") or "")
        self.kind: _KindProxy = _KindProxy(str(d.get("kind") or ""))
        self.label: str = str(d.get("label") or "")
        self.readiness_label: str = str(d.get("readiness_label") or "unknown")
        self.is_authoritative: bool = bool(d.get("is_authoritative", False))
        self.provider_id: Optional[str] = d.get("provider_id")
        self.model_id: Optional[str] = d.get("model_id")
        self.is_available: bool = bool(d.get("is_available", False))


class _RelationDictProxy:
    """Lightweight proxy that wraps a relation dict for use in rendering."""

    def __init__(self, d: Dict[str, Any]) -> None:
        self.source_id: str = str(d.get("source_id") or "")
        self.target_id: str = str(d.get("target_id") or "")
        self.kind: _KindProxy = _KindProxy(str(d.get("kind") or ""))
        self.label: str = str(d.get("label") or "")
        self.is_authoritative: bool = bool(d.get("is_authoritative", False))


class _LayerDictProxy:
    """Lightweight proxy that wraps a layer dict for use in rendering."""

    def __init__(self, d: Dict[str, Any]) -> None:
        self.layer_kind: str = str(d.get("layer_kind") or "")
        self.label: str = str(d.get("label") or "")
        self.is_lower_horizon: bool = bool(d.get("is_lower_horizon", False))
        raw_nodes = d.get("nodes") or []
        self.nodes: List[_NodeDictProxy] = [
            _NodeDictProxy(n) for n in raw_nodes if isinstance(n, dict)
        ]


def _get_nodes(layer: Any) -> List[Any]:
    """Safely extract a node list from a layer (attribute or proxy)."""
    if layer is None:
        return []
    if isinstance(layer, _LayerDictProxy):
        return layer.nodes
    return list(getattr(layer, "nodes", []) or [])
