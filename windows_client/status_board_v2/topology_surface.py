"""
windows_client/status_board_v2/topology_surface.py
===================================================
TopologySurface — renders the model topology fields of a RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Displayed fields
----------------
- ``primary_model_id``  : the top-ranked model node
- ``support_model_ids`` : ordered supporting models
- ``active_weights``    : top-N models by combined weight (as bar chart)
- ``route_reason``      : human-readable routing rationale (if present)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ._ansi import BOLD, RESET, c

_COLOUR_PRIMARY = "\033[32m"    # green
_COLOUR_SUPPORT = "\033[36m"    # cyan
_COLOUR_WEIGHT = "\033[33m"     # yellow
_COLOUR_REASON = "\033[90m"     # grey

_TOP_N = 5          # Maximum number of weight rows to display.
_BAR_WIDTH = 16     # Width of the weight progress bar.


def _weight_bar(value: float) -> str:
    """Render a compact ASCII bar for a weight value in [0, 1]."""
    # Clamp to [0, 1] defensively.
    v = max(0.0, min(1.0, value))
    filled = int(round(v * _BAR_WIDTH))
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
    return f"[{bar}] {v:.3f}"


class TopologySurface:
    """Renders the model topology surface.

    READ-ONLY — this class only produces display strings.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the topology surface.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        primary: Optional[str] = projection.get("primary_model_id")
        support: List[str] = projection.get("support_model_ids") or []
        weights: Dict[str, float] = projection.get("active_weights") or {}
        reason: Optional[str] = projection.get("route_reason")

        lines: List[str] = [
            c("  ┌─ Model Topology ─────────────────────────────────┐", BOLD),
        ]

        # Primary model.
        if primary:
            lines.append(f"  │  {c('Primary :', BOLD)} {c(primary, _COLOUR_PRIMARY)}")
        else:
            lines.append(f"  │  {c('Primary :', BOLD)} {c('(none)', _COLOUR_REASON)}")

        # Support models.
        if support:
            support_str = ", ".join(support)
            lines.append(f"  │  {c('Support :', BOLD)} {c(support_str, _COLOUR_SUPPORT)}")
        else:
            lines.append(f"  │  {c('Support :', BOLD)} {c('(none)', _COLOUR_REASON)}")

        # Top-N weight bars.
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

        # Route reason.
        if reason:
            # Truncate long reason strings to fit the board width.
            truncated = reason if len(reason) <= 50 else reason[:47] + "..."
            lines.append(f"  │  {c('Reason  : ' + truncated, _COLOUR_REASON)}")

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)
