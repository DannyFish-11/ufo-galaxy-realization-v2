"""
windows_client/status_board_v2/topology_surface.py
===================================================
TopologySurface — renders the model topology fields of a RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Topology structure (native-multimodal-first)
--------------------------------------------
This surface renders the model routing topology with the following layered
structure, as defined in ``docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md``:

1. **MAIN ROUTE** — the primary model, emphasised as native-multimodal when
   ``is_native_multimodal`` is ``True``.  Vendor/source label shown when
   ``vendor_source`` is available.
2. **SUPPORT** — ordered supporting/auxiliary models with weight bars and
   vendor labels.
3. **Reason / routing authority** — the human-readable route rationale and
   the canonical routing authority source.
4. **ONEAPI AGGREGATOR** (lower row, separated by a rule) — rendered only when
   ``oneapi_source`` data is present in the projection.  OneAPI is never mixed
   into the main direct-provider layer.

Displayed fields
----------------
- ``primary_model_id``    : the top-ranked model node (MAIN ROUTE)
- ``is_native_multimodal``: ``[MM]`` label on the primary entry when ``True``
- ``vendor_source``       : per-model vendor/provider label when available
- ``topology_role``       : role hint per model (primary/support/specialist)
- ``support_model_ids``   : ordered supporting models (SUPPORT layer)
- ``active_weights``      : top-N models by combined weight (bar chart)
- ``route_reason``        : human-readable routing rationale (if present)
- ``routing_authority``   : which authority populated the routing fields
- ``oneapi_source``       : OneAPI aggregator metadata for the lower row
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ._ansi import BOLD, RESET, c

_COLOUR_PRIMARY = "\033[32m"    # green
_COLOUR_SUPPORT = "\033[36m"    # cyan
_COLOUR_WEIGHT = "\033[33m"     # yellow
_COLOUR_REASON = "\033[90m"     # grey
_COLOUR_ONEAPI = "\033[35m"     # magenta
_COLOUR_DIM = "\033[90m"        # dim grey
_COLOUR_MM = "\033[96m"         # bright cyan for native-multimodal badge

_TOP_N = 5          # Maximum number of weight rows to display.
_BAR_WIDTH = 16     # Width of the weight progress bar.
_RULE_WIDTH = 48    # Width of the horizontal rule separating topology sections.
_MAX_AUTHORITY_LEN = 40   # Maximum authority string length before truncation.
_AUTHORITY_TRIM_LEN = 37  # Trimmed length used when authority string is too long.

_RULE = "  │  " + "─" * _RULE_WIDTH


def _weight_bar(value: float) -> str:
    """Render a compact ASCII bar for a weight value in [0, 1]."""
    # Clamp to [0, 1] defensively.
    v = max(0.0, min(1.0, value))
    filled = int(round(v * _BAR_WIDTH))
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
    return f"[{bar}] {v:.3f}"


def _vendor_tag(vendor: Optional[str]) -> str:
    """Return a formatted vendor/source tag, or empty string."""
    if not vendor:
        return ""
    return f"  [{vendor}]"


class TopologySurface:
    """Renders the model topology surface.

    READ-ONLY — this class only produces display strings.

    The topology is displayed as a **native-multimodal-first** layered
    structure: main route first (primary model with optional [MM] badge and
    vendor tag), then the support layer, then an optional lower OneAPI
    aggregator row.  See ``docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`` for
    the full semantics.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the topology surface.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.  New optional
            fields consumed by this surface:

            - ``is_native_multimodal`` (bool, default ``False``) — when
              ``True`` the primary model receives a ``[MM]`` badge.
            - ``vendor_source`` (str | None) — vendor/provider label for the
              primary model (e.g. ``"openai"``, ``"anthropic"``).
            - ``topology_role`` (str | None) — role hint for the primary
              model (e.g. ``"primary"``, ``"support"``, ``"specialist"``).
            - ``oneapi_source`` (dict | None) — when present, the surface
              renders a lower OneAPI aggregator row.  Expected keys:
              ``base_url`` (str), ``status`` (str), ``model_count`` (int).

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        primary: Optional[str] = projection.get("primary_model_id")
        support: List[str] = projection.get("support_model_ids") or []
        weights: Dict[str, float] = projection.get("active_weights") or {}
        reason: Optional[str] = projection.get("route_reason")
        is_native_mm: bool = bool(projection.get("is_native_multimodal", False))
        vendor_source: Optional[str] = projection.get("vendor_source")
        topology_role: Optional[str] = projection.get("topology_role")
        routing_auth: Optional[str] = projection.get("routing_authority")
        oneapi_source: Optional[Dict[str, Any]] = projection.get("oneapi_source")

        lines: List[str] = [
            c(
                "  ┌─ Model Topology — Native-Multimodal First ──────┐",
                BOLD,
            ),
        ]

        # ── MAIN ROUTE layer ──────────────────────────────────────────────
        lines.append(
            f"  │  {c('MAIN ROUTE', BOLD)}"
            f"  {c('(direct / native-multimodal first)', _COLOUR_DIM)}"
        )

        if primary:
            mm_badge = f"  {c('[MM]', _COLOUR_MM)}" if is_native_mm else ""
            role_badge = (
                f"  {c('[' + topology_role + ']', _COLOUR_DIM)}"
                if topology_role
                else ""
            )
            vtag = _vendor_tag(vendor_source)
            lines.append(
                f"  │   {c('★', _COLOUR_PRIMARY)} {c(primary, _COLOUR_PRIMARY)}"
                f"{mm_badge}{role_badge}{c(vtag, _COLOUR_DIM)}"
            )
        else:
            lines.append(
                f"  │   {c('★', _COLOUR_REASON)} {c('(no primary model)', _COLOUR_REASON)}"
            )

        # ── SUPPORT layer ─────────────────────────────────────────────────
        lines.append(f"  │")
        lines.append(f"  │  {c('SUPPORT', BOLD)}")

        if support:
            for s_id in support:
                lines.append(f"  │    {c('·', _COLOUR_SUPPORT)} {c(s_id, _COLOUR_SUPPORT)}")
        else:
            lines.append(
                f"  │    {c('(none)', _COLOUR_REASON)}"
            )

        # ── Weight bars (top-N across all models) ─────────────────────────
        lines.append(f"  │")
        if weights:
            lines.append(f"  │  {c(f'Weights (top {_TOP_N}) :', BOLD)}")
            sorted_weights: List[Tuple[str, float]] = sorted(
                weights.items(), key=lambda kv: kv[1], reverse=True
            )[:_TOP_N]
            for model_id, wt in sorted_weights:
                bar = _weight_bar(wt)
                is_primary = model_id == primary
                col = _COLOUR_PRIMARY if is_primary else _COLOUR_WEIGHT
                marker = " ★" if is_primary else "  "
                lines.append(f"  │   {marker}{c(bar, col)}  {model_id}")
        else:
            lines.append(
                f"  │  {c('Weights :', BOLD)} {c('(no topology data)', _COLOUR_REASON)}"
            )

        # ── Route reason ──────────────────────────────────────────────────
        if reason:
            # Truncate long reason strings to fit the board width.
            truncated = reason if len(reason) <= 50 else reason[:47] + "..."
            lines.append(f"  │  {c('Reason  : ' + truncated, _COLOUR_REASON)}")

        # ── Routing authority ─────────────────────────────────────────────
        if routing_auth and routing_auth not in ("none", ""):
            auth_str = routing_auth
            if len(auth_str) > _MAX_AUTHORITY_LEN:
                auth_str = "…" + auth_str[-_AUTHORITY_TRIM_LEN:]
            lines.append(
                f"  │  {c('Authority: ' + auth_str, _COLOUR_DIM)}"
            )

        # ── OneAPI aggregator row (lower, always separated) ───────────────
        if oneapi_source is not None:
            lines.append(_RULE)
            lines.append(
                f"  │  {c('ONEAPI AGGREGATOR', BOLD)}"
                f"  {c('(lower-layer / not a direct provider)', _COLOUR_DIM)}"
            )
            base_url: str = oneapi_source.get("base_url") or "(not configured)"
            status_str: str = oneapi_source.get("status") or "unknown"
            model_count = oneapi_source.get("model_count")
            count_str = (
                f"  {c(str(model_count) + ' models', _COLOUR_DIM)}"
                if model_count is not None
                else ""
            )
            lines.append(
                f"  │    {c(base_url, _COLOUR_ONEAPI)}"
                f"  {c('[' + status_str + ']', _COLOUR_ONEAPI)}"
                f"{count_str}"
            )

        lines.append(
            c("  └─────────────────────────────────────────────────┘", BOLD)
        )
        return "\n".join(lines)
