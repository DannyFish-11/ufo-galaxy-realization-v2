"""
windows_client/status_board_v2/app.py
======================================
Status Board V2 — main application entry point.

This is a **read-only** CLI status board that consumes the
:class:`~core.projection.RuntimeProjection` produced by the Galaxy server
and renders it using five lightweight text surfaces:

  PhaseSurface     — tri_state_phase
  DomainSurface    — runtime_domain
  TopologySurface  — primary/support models, weight bars, route reason
  DeviceSurface    — active devices, execution stage, task summary
  MetricsSurface   — presence_intensity, coherence, collapse/retreat tendency

READ-ONLY GUARANTEE
-------------------
This application:
  ✗  Does NOT accept chat input
  ✗  Does NOT send commands
  ✗  Does NOT trigger actions

All command execution lives in::

    windows_aip_client.py → WindowsExecutionArbiter.route_command()

Usage
-----
    # Poll the default local server:
    python -m windows_client.status_board_v2

    # Specify a different server:
    python -m windows_client.status_board_v2 --host 10.0.0.5 --port 8000

    # Read from a JSON file instead of the server:
    python -m windows_client.status_board_v2 --file /tmp/projection.json

    # Read a single projection from stdin:
    cat projection.json | python -m windows_client.status_board_v2 --stdin

    # Adjust poll interval:
    python -m windows_client.status_board_v2 --interval 2.0

    # Disable ANSI colour:
    python -m windows_client.status_board_v2 --no-color
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import _ansi
from .projection_reader import ProjectionReader, ProjectionReadError
from .phase_surface import PhaseSurface
from .domain_surface import DomainSurface
from .topology_surface import TopologySurface
from .device_surface import DeviceSurface
from .metrics_surface import MetricsSurface
from .liminal_surface import LiminalSurface

_RESET = _ansi.RESET
_BOLD = _ansi.BOLD
_COLOUR_ERROR = "\033[31m"
_BOARD_TITLE = "OpenClawd Status Board V2  (read-only)"
_BOARD_SEPARATOR = "─" * 52


class StatusBoardV2App:
    """Orchestrates the Status Board V2 rendering loop.

    READ-ONLY: this class reads projection data and renders surfaces.
    It never sends any command or modifies any state.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        interval: float = 1.0,
        file_path: Optional[str] = None,
        from_stdin: bool = False,
        no_color: bool = False,
    ) -> None:
        _ansi.ANSI_ENABLED = sys.stdout.isatty() and not no_color

        base_url = f"http://{host}:{port}" if (not file_path and not from_stdin) else None
        self._reader = ProjectionReader(
            base_url=base_url,
            file_path=file_path,
            from_stdin=from_stdin,
        )
        self._interval = interval
        self._host = host
        self._port = port

        # Surfaces — each is read-only and produces only display strings.
        self._phase = PhaseSurface()
        self._domain = DomainSurface()
        self._topology = TopologySurface()
        self._device = DeviceSurface()
        self._metrics = MetricsSurface()
        self._liminal = LiminalSurface()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render_once(self, projection: Dict[str, Any]) -> str:
        """Render a complete status board frame from *projection*.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            The full multi-line board string, ready for ``print()``.
        """
        source = (
            f"http://{self._host}:{self._port}/api/v1/projection/runtime"
            if self._reader._base_url
            else (self._reader._file_path or "stdin")
        )
        ts_raw: Optional[float] = projection.get("timestamp")
        ts_str = (
            datetime.datetime.fromtimestamp(ts_raw).strftime("%H:%M:%S")
            if ts_raw
            else "—"
        )

        parts: List[str] = [
            _ansi.c(_BOARD_SEPARATOR, _BOLD),
            _ansi.c(f"  {_BOARD_TITLE}", _BOLD),
            f"  Source  : {source}",
            f"  Updated : {ts_str}",
            _ansi.c(_BOARD_SEPARATOR, _BOLD),
            self._phase.render(projection),
            self._domain.render(projection),
            self._topology.render(projection),
            self._device.render(projection),
            self._metrics.render(projection),
            self._liminal.render(projection),
            _ansi.c(_BOARD_SEPARATOR, _BOLD),
        ]
        return "\n".join(parts)

    def render_offline(self, error: str) -> str:
        """Render an OFFLINE frame when the projection source is unreachable."""
        parts = [
            _ansi.c(_BOARD_SEPARATOR, _BOLD),
            _ansi.c(f"  {_BOARD_TITLE}", _BOLD),
            _ansi.c(_BOARD_SEPARATOR, _BOLD),
            _ansi.c(f"  ✗  OFFLINE — {error}", _COLOUR_ERROR),
            _ansi.c(_BOARD_SEPARATOR, _BOLD),
        ]
        return "\n".join(parts)

    def run(self) -> None:
        """Enter the main polling loop.

        Runs until the user presses Ctrl-C.  On each tick:
        1. Fetch the projection (HTTP / file / stdin).
        2. Clear the terminal.
        3. Render and print the board.
        4. Sleep for ``interval`` seconds.
        """
        print(
            f"OpenClawd Status Board V2 — "
            f"polling every {self._interval}s  (Ctrl-C to quit)\n"
        )
        try:
            while True:
                _clear()
                try:
                    projection = self._reader.read()
                    frame = self.render_once(projection)
                except ProjectionReadError as exc:
                    frame = self.render_offline(str(exc))
                except Exception as exc:  # pragma: no cover
                    frame = self.render_offline(f"Unexpected error: {exc}")
                print(frame)
                time.sleep(self._interval)
        except KeyboardInterrupt:
            print("\nStatus Board V2 stopped.")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _clear() -> None:
    """Clear the terminal screen."""
    if sys.platform == "win32":
        os.system("cls")
    else:
        os.system("clear")


def run(
    host: str = "127.0.0.1",
    port: int = 8000,
    interval: float = 1.0,
    file_path: Optional[str] = None,
    from_stdin: bool = False,
    no_color: bool = False,
) -> None:
    """Convenience function: create and run the status board app.

    READ-ONLY: this function never writes to the server.
    """
    app = StatusBoardV2App(
        host=host,
        port=port,
        interval=interval,
        file_path=file_path,
        from_stdin=from_stdin,
        no_color=no_color,
    )
    app.run()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="status_board_v2",
        description=(
            "OpenClawd read-only Status Board V2.  "
            "Displays RuntimeProjection: phase, domain, model topology, "
            "devices, and metrics.  NO chat input, NO command sending."
        ),
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Galaxy server host (default: 127.0.0.1)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Galaxy server port (default: 8000)",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds (default: 1.0)",
    )
    p.add_argument(
        "--file",
        dest="file_path",
        default=None,
        metavar="PATH",
        help="Read projection from a JSON file instead of the server",
    )
    p.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read a single projection JSON blob from stdin",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI colour output",
    )
    return p


def main() -> None:
    """CLI entry point."""
    args = _build_parser().parse_args()
    run(
        host=args.host,
        port=args.port,
        interval=args.interval,
        file_path=args.file_path,
        from_stdin=args.stdin,
        no_color=args.no_color,
    )


if __name__ == "__main__":
    main()
