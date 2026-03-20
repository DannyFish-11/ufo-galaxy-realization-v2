"""
windows_client/status_board_v2/metrics_surface.py
==================================================
MetricsSurface — renders the presence/coherence/tendency metrics from a
RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Displayed fields
----------------
- ``presence_intensity``  : EMA-smoothed overall presence strength [0, 1]
- ``coherence``           : degree to which signals form a coherent intent [0, 1]
- ``collapse_tendency``   : push toward liminal → manifest collapse [0, 1]
- ``retreat_tendency``    : push toward retreat / receding [0, 1]
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._ansi import BOLD, RESET, c

_COLOUR_PRESENCE = "\033[32m"    # green
_COLOUR_COHERENCE = "\033[36m"   # cyan
_COLOUR_COLLAPSE = "\033[33m"    # yellow
_COLOUR_RETREAT = "\033[31m"     # red
_COLOUR_NA = "\033[90m"          # grey

_BAR_WIDTH = 18


def _bar(value: Optional[float], colour: str) -> str:
    """Render an ASCII bar for a [0, 1] metric value.

    Returns an ``(n/a)`` string when *value* is ``None``.
    """
    if value is None:
        return c("(n/a)", _COLOUR_NA)
    v = max(0.0, min(1.0, value))
    filled = int(round(v * _BAR_WIDTH))
    raw = "[" + "█" * filled + "░" * (_BAR_WIDTH - filled) + f"] {v:.3f}"
    return c(raw, colour)


class MetricsSurface:
    """Renders the presence/coherence/tendency metrics surface.

    READ-ONLY — this class only produces display strings.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the metrics surface.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        presence: Optional[float] = projection.get("presence_intensity")
        coherence: Optional[float] = projection.get("coherence")
        collapse: Optional[float] = projection.get("collapse_tendency")
        retreat: Optional[float] = projection.get("retreat_tendency")

        lines = [
            c("  ┌─ Metrics ────────────────────────────────────────┐", BOLD),
            f"  │  {c('Presence   ', BOLD)}{_bar(presence,  _COLOUR_PRESENCE)}",
            f"  │  {c('Coherence  ', BOLD)}{_bar(coherence, _COLOUR_COHERENCE)}",
            f"  │  {c('Collapse ↓ ', BOLD)}{_bar(collapse,  _COLOUR_COLLAPSE)}",
            f"  │  {c('Retreat  ← ', BOLD)}{_bar(retreat,   _COLOUR_RETREAT)}",
            c("  └─────────────────────────────────────────────────┘", BOLD),
        ]
        return "\n".join(lines)
