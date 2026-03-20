"""
windows_client/status_board_v2/domain_surface.py
=================================================
DomainSurface — renders the runtime_domain field of a RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Displayed fields
----------------
- ``runtime_domain`` : local / cross_device / transition / unknown
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._ansi import BOLD, RESET, c

_COLOUR_LOCAL = "\033[36m"       # cyan
_COLOUR_CROSS = "\033[35m"       # magenta
_COLOUR_TRANSITION = "\033[33m"  # yellow
_COLOUR_UNKNOWN = "\033[90m"     # grey

_DOMAIN_COLOURS: Dict[str, str] = {
    "local": _COLOUR_LOCAL,
    "cross_device": _COLOUR_CROSS,
    "transition": _COLOUR_TRANSITION,
}

_DOMAIN_LABELS: Dict[str, str] = {
    "local": "LOCAL        — confined to this device",
    "cross_device": "CROSS_DEVICE — spanning multiple devices",
    "transition": "TRANSITION   — resolving local ↔ cross-device",
}


class DomainSurface:
    """Renders the runtime domain surface.

    READ-ONLY — this class only produces display strings.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the domain surface.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        domain: Optional[str] = projection.get("runtime_domain")
        if domain is None:
            col = _COLOUR_UNKNOWN
            label = "UNKNOWN      — domain not yet resolved"
        else:
            col = _DOMAIN_COLOURS.get(domain, _COLOUR_UNKNOWN)
            label = _DOMAIN_LABELS.get(domain, domain.upper())

        lines = [
            c("  ┌─ Runtime Domain ─────────────────────────────────┐", BOLD),
            f"  │  {c(label, col)}",
            c("  └─────────────────────────────────────────────────┘", BOLD),
        ]
        return "\n".join(lines)
