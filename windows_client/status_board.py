"""
windows_client/status_board.py — Minimal Read-Only Desktop Status Board
=========================================================================

.. deprecated:: PR-8  LEGACY STATUS BOARD
   This module is a **legacy status board** superseded by
   ``windows_client/status_board_v2/`` (PR-8).

   **Why it is legacy:** It polls ``/api/v1/continuum/state`` which is an
   ad-hoc non-projection endpoint.  The canonical replacement,
   ``status_board_v2/``, consumes the official projection contract from::

       GET /api/v1/projection/runtime
       contract: contracts.desktop_status_projection.DesktopStatusProjection

   Do not extend this module.  Extend ``status_board_v2/`` instead.

Displays the current OpenClawd state continuum at a glance:

  - ``tri_state_phase``  (silent / liminal / manifest)
  - ``runtime_domain``   (local / cross_device / transition / unknown)
  - Optional presence summary: presence_intensity, coherence

This is a **read-only** status board.  It does NOT accept chat input and does
NOT send any commands to the system.  All command execution goes through::

    windows_aip_client.py → WindowsExecutionArbiter.route_command()

Usage
------
    # Poll a running Galaxy server (default: http://127.0.0.1:8000)
    python windows_client/status_board.py

    # Specify server address
    python windows_client/status_board.py --host 10.0.0.5 --port 8000

    # Adjust poll interval (seconds)
    python windows_client/status_board.py --interval 2.0

    # Disable ANSI colour output (e.g. for plain terminals / log files)
    python windows_client/status_board.py --no-color

Data Source
-----------
The board polls the REST endpoint::

    GET <host>:<port>/api/v1/continuum/state

Expected response schema (subset)::

    {
      "tri_state_phase": "silent" | "liminal" | "manifest",
      "runtime_domain":  "local" | "cross_device" | "transition" | null,
      "presence_intensity": 0.0 – 1.0,
      "coherence": 0.0 – 1.0
    }

If the endpoint is unreachable the board shows ``OFFLINE`` and retries at the
configured interval.

Related Documents
-----------------
- docs/WINDOWS_STATUS_BOARD.md
- docs/OPENCLAWD_STATE_CONTINUUM.md
- docs/windows_mcp_server.md  (Windows execution pipeline)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# ANSI colour helpers (gracefully disabled when --no-color is set or stdout
# is not a TTY)
# ---------------------------------------------------------------------------

_ANSI_ENABLED = sys.stdout.isatty()

_RESET = "\033[0m"
_BOLD = "\033[1m"

# Phase colours
_COLOUR_SILENT = "\033[90m"     # dark grey
_COLOUR_LIMINAL = "\033[33m"    # yellow
_COLOUR_MANIFEST = "\033[32m"   # green

# Domain colours
_COLOUR_LOCAL = "\033[36m"       # cyan
_COLOUR_CROSS = "\033[35m"       # magenta
_COLOUR_TRANSITION = "\033[33m"  # yellow
_COLOUR_UNKNOWN = "\033[90m"     # grey

_COLOUR_ERROR = "\033[31m"       # red


def _c(text: str, code: str) -> str:
    """Wrap *text* in an ANSI colour escape if colour is enabled."""
    if not _ANSI_ENABLED:
        return text
    return f"{code}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Phase / domain display helpers
# ---------------------------------------------------------------------------

_PHASE_SYMBOLS = {
    "silent": "○",
    "liminal": "◑",
    "manifest": "●",
}

_PHASE_COLOURS = {
    "silent": _COLOUR_SILENT,
    "liminal": _COLOUR_LIMINAL,
    "manifest": _COLOUR_MANIFEST,
}

_DOMAIN_COLOURS = {
    "local": _COLOUR_LOCAL,
    "cross_device": _COLOUR_CROSS,
    "transition": _COLOUR_TRANSITION,
}


def _fmt_phase(phase: str) -> str:
    sym = _PHASE_SYMBOLS.get(phase, "?")
    col = _PHASE_COLOURS.get(phase, "")
    return _c(f"{sym} {phase.upper()}", col)


def _fmt_domain(domain: Optional[str]) -> str:
    if domain is None:
        return _c("unknown", _COLOUR_UNKNOWN)
    col = _DOMAIN_COLOURS.get(domain, _COLOUR_UNKNOWN)
    return _c(domain, col)


def _bar(value: float, width: int = 20) -> str:
    """Render a simple ASCII progress bar for a 0.0–1.0 value."""
    filled = int(round(value * width))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {value:.2f}"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_state(base_url: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Fetch the current ContinuumState from the server.

    Returns a dict on success.  Raises ``urllib.error.URLError`` or
    ``json.JSONDecodeError`` on failure.
    """
    url = f"{base_url}/api/v1/continuum/state"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_BOARD_WIDTH = 52


def _divider() -> str:
    return "─" * _BOARD_WIDTH


def render_board(state: Dict[str, Any], server_url: str) -> str:
    """Return a multi-line string representing the current status board."""
    phase = state.get("tri_state_phase", "silent")
    domain = state.get("runtime_domain")  # may be None
    presence = state.get("presence_intensity", 0.0)
    coherence = state.get("coherence", 0.0)
    ts = state.get("timestamp")
    degraded = state.get("degraded", False)

    lines = [
        _divider(),
        _c("  OpenClawd Status Board  (read-only)", _BOLD),
        f"  Server : {server_url}",
        _divider(),
        f"  Phase  : {_fmt_phase(phase)}",
        f"  Domain : {_fmt_domain(domain)}",
        _divider(),
        f"  Presence  {_bar(presence)}",
        f"  Coherence {_bar(coherence)}",
    ]
    if degraded:
        reason = state.get("degrade_reason", "")
        lines.append(_c(f"  ⚠  DEGRADED — {reason}", _COLOUR_ERROR))
    if ts:
        t = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        lines.append(f"  Updated : {t}")
    lines.append(_divider())
    return "\n".join(lines)


def render_offline(server_url: str, error: str) -> str:
    return "\n".join([
        _divider(),
        _c("  OpenClawd Status Board  (read-only)", _BOLD),
        f"  Server : {server_url}",
        _divider(),
        _c("  ✗  OFFLINE — " + error, _COLOUR_ERROR),
        _divider(),
    ])


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _clear() -> None:
    """Clear the terminal screen."""
    if sys.platform == "win32":
        os.system("cls")
    else:
        os.system("clear")


def run(host: str, port: int, interval: float, no_color: bool) -> None:
    """Main polling loop.  Runs until the user presses Ctrl-C."""
    global _ANSI_ENABLED
    if no_color:
        _ANSI_ENABLED = False

    base_url = f"http://{host}:{port}"

    print(f"OpenClawd Status Board — polling {base_url} every {interval}s")
    print("Press Ctrl-C to quit.\n")

    try:
        while True:
            _clear()
            try:
                state = fetch_state(base_url)
                board = render_board(state, base_url)
            except Exception as exc:
                board = render_offline(base_url, str(exc))
            print(board)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStatus board stopped.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="status_board",
        description=(
            "OpenClawd read-only desktop status board.  "
            "Displays tri_state_phase and runtime_domain by polling the server."
        ),
    )
    p.add_argument("--host", default="127.0.0.1", help="Galaxy server host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Galaxy server port (default: 8000)")
    p.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds (default: 1.0)",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI colour output",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    run(
        host=args.host,
        port=args.port,
        interval=args.interval,
        no_color=args.no_color,
    )


if __name__ == "__main__":
    main()
