"""
windows_client/status_board_v2/_ansi.py
========================================
Internal ANSI colour helpers for the Status Board V2 surfaces.

These helpers are internal to the package and should not be imported
from outside ``windows_client/status_board_v2/``.
"""

from __future__ import annotations

import sys

# Module-level flag; can be overridden by the app before surface rendering.
ANSI_ENABLED: bool = sys.stdout.isatty()

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def c(text: str, code: str) -> str:
    """Wrap *text* in an ANSI escape code if ANSI is enabled.

    Parameters
    ----------
    text:
        The string to colorise.
    code:
        ANSI escape code to apply (e.g. ``"\\033[32m"`` for green).

    Returns
    -------
    str
        Wrapped string, or *text* unchanged when ANSI is disabled.
    """
    if not ANSI_ENABLED:
        return text
    return f"{code}{text}{RESET}"
