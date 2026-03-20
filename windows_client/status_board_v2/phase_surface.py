"""
windows_client/status_board_v2/phase_surface.py
================================================
PhaseSurface — renders the tri_state_phase field of a RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Displayed fields
----------------
- ``tri_state_phase`` : silent / liminal / manifest
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._ansi import BOLD, RESET, c

# Phase-specific ANSI colours.
_COLOUR_SILENT = "\033[90m"     # dark grey
_COLOUR_LIMINAL = "\033[33m"    # yellow
_COLOUR_MANIFEST = "\033[32m"   # green
_COLOUR_UNKNOWN = "\033[90m"    # grey

# Unicode symbols per phase.
_PHASE_SYMBOLS: Dict[str, str] = {
    "silent": "○",
    "liminal": "◑",
    "manifest": "●",
}

_PHASE_COLOURS: Dict[str, str] = {
    "silent": _COLOUR_SILENT,
    "liminal": _COLOUR_LIMINAL,
    "manifest": _COLOUR_MANIFEST,
}

_PHASE_LABELS: Dict[str, str] = {
    "silent": "SILENT   — native multimodal ingress, minimal footprint",
    "liminal": "LIMINAL  — intent forming, transition zone",
    "manifest": "MANIFEST — structure formed, action in progress",
}


class PhaseSurface:
    """Renders the tri-state phase surface.

    READ-ONLY — this class only produces display strings.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the phase surface.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        phase: str = projection.get("tri_state_phase") or "silent"
        sym = _PHASE_SYMBOLS.get(phase, "?")
        col = _PHASE_COLOURS.get(phase, _COLOUR_UNKNOWN)
        label = _PHASE_LABELS.get(phase, phase.upper())

        lines = [
            c("  ┌─ Phase ──────────────────────────────────────────┐", BOLD),
            f"  │  {c(sym + '  ' + label, col)}",
            c("  └─────────────────────────────────────────────────┘", BOLD),
        ]
        return "\n".join(lines)
