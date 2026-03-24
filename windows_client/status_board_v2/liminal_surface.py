"""
windows_client/status_board_v2/liminal_surface.py
==================================================
LiminalSurface — renders the liminal projection engine output as part of
Status Board V2.

READ-ONLY surface: displays information only, never sends commands.

Display boundary
----------------
This surface is part of the **liminal middle-state space** — a spatial
execution field, NOT a second status board.  It must carry only:

1. Local execution chain
2. Cross-device execution chain
3. Sandbox simulation / speculative execution field

It must NOT carry: provider list cards, dashboard-style model panels, full
metrics/status-board panels, or generic operator information blocks.
Those belong exclusively to the right-side desktop status board.

See ``docs/DESKTOP_DISPLAY_BOUNDARIES.md`` for the canonical boundary contract.

Architecture
------------
This surface is an integration adapter between the
:class:`~desktop_projection.LiminalSpaceEngine` and the Status Board V2
rendering loop.  It reads the four spatial dimensions from a
:class:`~desktop_projection.LiminalSpaceState` and renders them as compact
ASCII bars.

Displayed fields
----------------
- ``depth_factor``         : spatial depth of the projection
- ``topology_visibility``  : how visible the model-topology layer is
- ``domain_path_emphasis`` : prominence of the runtime-domain path
- ``ambient_intensity``    : ambient field strength
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from ._ansi import BOLD, RESET, c

# Colour coding per phase.
_COLOUR_SILENT = "\033[90m"     # dark grey
_COLOUR_LIMINAL = "\033[33m"    # yellow / amber
_COLOUR_MANIFEST = "\033[32m"   # green
_COLOUR_DIM = "\033[2m"         # dim

_BAR_WIDTH = 18

_PHASE_COLOURS: Dict[str, str] = {
    "silent": _COLOUR_SILENT,
    "liminal": _COLOUR_LIMINAL,
    "manifest": _COLOUR_MANIFEST,
}


def _bar(value: float, width: int = _BAR_WIDTH, colour: str = "") -> str:
    """Render an ASCII progress bar for *value* ∈ [0, 1]."""
    filled = round(max(0.0, min(1.0, value)) * width)
    inner = "█" * filled + "░" * (width - filled)
    bar = f"[{inner}]"
    return c(bar, colour) if colour else bar


class LiminalSurface:
    """Renders the liminal projection dimensions.

    READ-ONLY — this class only produces display strings.

    This surface integrates with :class:`~desktop_projection.LiminalSpaceEngine`
    to show the four spatial dimensions that drive the desktop transition layer.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the liminal projection surface.

        Parameters
        ----------
        projection:
            A dict conforming to the ``RuntimeProjection`` schema (the same
            projection dict used by all other surfaces).  The mapper is called
            internally to derive liminal dimensions.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        # Import here to avoid circular imports and keep the surface lightweight.
        try:
            from desktop_projection import StateSpaceMapper
            liminal = StateSpaceMapper().map(projection)
        except Exception:  # pragma: no cover
            # Graceful degradation: if the desktop_projection package is not
            # available, render a minimal placeholder.
            return self._render_unavailable()

        phase = liminal.source_phase
        domain = liminal.source_domain or "—"
        col = _PHASE_COLOURS.get(phase, _COLOUR_DIM)

        d_bar = _bar(liminal.depth_factor, colour=col)
        t_bar = _bar(liminal.topology_visibility, colour=col)
        p_bar = _bar(liminal.domain_path_emphasis, colour=col)
        a_bar = _bar(liminal.ambient_intensity, colour=col)

        lines = [
            c("  ┌─ Liminal Projection ─────────────────────────────┐", BOLD),
            f"  │  Phase        : {c(phase, col)}  Domain: {c(domain, col)}",
            f"  │  Depth        : {d_bar}  {liminal.depth_factor:.3f}",
            f"  │  Topology     : {t_bar}  {liminal.topology_visibility:.3f}",
            f"  │  Domain Path  : {p_bar}  {liminal.domain_path_emphasis:.3f}",
            f"  │  Ambient      : {a_bar}  {liminal.ambient_intensity:.3f}",
            c("  └─────────────────────────────────────────────────┘", BOLD),
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_unavailable() -> str:
        """Render a graceful degradation placeholder."""
        return (
            c("  ┌─ Liminal Projection ─────────────────────────────┐", BOLD) + "\n"
            "  │  (desktop_projection package not available)\n"
            + c("  └─────────────────────────────────────────────────┘", BOLD)
        )
