"""
windows_client/status_board_v2/app.py
======================================
Status Board V2 — main application entry point.

This is a CLI status board that consumes the
:class:`~core.projection.RuntimeProjection` produced by the Galaxy server
and renders it using lightweight text surfaces:

  PhaseSurface         — tri_state_phase
  DomainSurface        — runtime_domain
  TopologySurface      — primary/support models, weight bars, route reason
  DeviceSurface        — active devices, execution stage, task summary
  MetricsSurface       — presence_intensity, coherence, collapse/retreat tendency
  LiminalSurface       — liminal spatial projection dimensions (PR-5)
  ManifestSurface      — manifest-stage 显现台 execution surface (PR-6)
  ReturnSurface        — return-intelligence summary (PR-10)
  UrlConfigSurface     — URL / API-key configuration panel (operator-facing)
  DeviceChainSurface   — multi-device and cross-device task chain display

PR-15 adds a bounded, canonical configuration control surface
(``ConfigControlSurface``) with CLI arguments for one-shot config
operations and a control feedback panel rendered inside the board.

CONTROL OPERATIONS (PR-15 +)
-----------------------------
Apply a provider enable/disable toggle before entering monitor mode::

    python -m windows_client.status_board_v2 --apply-toggle openai=true

Apply a routing policy before entering monitor mode::

    python -m windows_client.status_board_v2 --apply-routing-policy prefer

Set a server/endpoint URL::

    python -m windows_client.status_board_v2 --set-url android_ws_url=ws://100.x.x.x:8765/ws/device/{device_id}
    python -m windows_client.status_board_v2 --set-url galaxy_gateway_url=http://localhost:9000
    python -m windows_client.status_board_v2 --set-url nats_url=nats://localhost:4222

Set a provider API key::

    python -m windows_client.status_board_v2 --set-api-key openai=sk-...
    python -m windows_client.status_board_v2 --set-api-key anthropic=sk-ant-...

All control arguments can be combined with all existing arguments.  The
board renders control feedback in the first frames after an apply action.

ALL WRITES GO THROUGH CANONICAL CONFIG AUTHORITY:
    ConfigControlSurface → ConfigService → ConfigStore → runtime/config.json
    (API keys → runtime/secrets.env via credential vault)

EXECUTION
---------
All task execution remains in::

    windows_aip_client.py → WindowsExecutionArbiter.route_command()

Usage
-----
    # Poll the default local server:
    python -m windows_client.status_board_v2

    # Specify a different server:
    python -m windows_client.status_board_v2 --host 10.0.0.5 --port 8299

    # Read from a JSON file instead of the server:
    python -m windows_client.status_board_v2 --file /tmp/projection.json

    # Read a single projection from stdin:
    cat projection.json | python -m windows_client.status_board_v2 --stdin

    # Adjust poll interval:
    python -m windows_client.status_board_v2 --interval 2.0

    # Disable ANSI colour:
    python -m windows_client.status_board_v2 --no-color

    # Apply a provider toggle then enter monitor mode:
    python -m windows_client.status_board_v2 --apply-toggle openai=true

    # Apply a routing policy then enter monitor mode:
    python -m windows_client.status_board_v2 --apply-routing-policy prefer

    # Set the Android WebSocket endpoint URL:
    python -m windows_client.status_board_v2 --set-url android_ws_url=ws://100.x.x.x:8765/ws/device/{device_id}

    # Set the NATS URL:
    python -m windows_client.status_board_v2 --set-url nats_url=nats://localhost:4222

    # Store an OpenAI API key:
    python -m windows_client.status_board_v2 --set-api-key openai=sk-...

    # Show URL/API-key config panel in every frame:
    python -m windows_client.status_board_v2 --show-url-config

    # Show device chain panel in every frame:
    python -m windows_client.status_board_v2 --show-device-chain
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
from .manifest_surface import ManifestSurface
from .return_surface import ReturnSurface
from .config_control import ConfigControlSurface, ControlApplyResult, ControlOperation
from .url_config_surface import UrlConfigSurface
from .device_chain_surface import DeviceChainSurface

_RESET = _ansi.RESET
_BOLD = _ansi.BOLD
_COLOUR_ERROR = "\033[31m"
_COLOUR_OK = "\033[32m"
_COLOUR_WARN = "\033[33m"
_BOARD_TITLE = "OpenClawd Status Board V2"
_BOARD_SEPARATOR = "─" * 52


class StatusBoardV2App:
    """Orchestrates the Status Board V2 rendering loop.

    As of PR-15 this class optionally accepts a :class:`ConfigControlSurface`
    and renders its feedback panel when a control operation has been applied.
    All projection/monitoring behaviour is unchanged.

    The ``show_url_config`` and ``show_device_chain`` flags activate the
    additional operator panels for URL/key configuration and cross-device
    task chain display.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8299,
        interval: float = 1.0,
        file_path: Optional[str] = None,
        from_stdin: bool = False,
        no_color: bool = False,
        control_surface: Optional[ConfigControlSurface] = None,
        show_url_config: bool = False,
        show_device_chain: bool = False,
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
        self._manifest = ManifestSurface()
        self._return = ReturnSurface()

        # PR-15: optional control surface for config feedback rendering
        self._control: Optional[ConfigControlSurface] = control_surface

        # Additional operator panels
        self._url_config: Optional[UrlConfigSurface] = (
            UrlConfigSurface() if show_url_config else None
        )
        self._device_chain: Optional[DeviceChainSurface] = (
            DeviceChainSurface() if show_device_chain else None
        )

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
            f"http://{self._host}:{self._port}"
            f"{self._reader.last_http_endpoint or self._reader.default_http_endpoint}"
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
            self._manifest.render(projection),
            self._return.render(projection),
        ]

        # Device chain panel (cross-device / multi-device task chain display)
        if self._device_chain is not None:
            parts.append(_ansi.c(_BOARD_SEPARATOR, _BOLD))
            parts.append(self._device_chain.render(projection))

        # URL / API-key configuration panel
        if self._url_config is not None:
            parts.append(_ansi.c(_BOARD_SEPARATOR, _BOLD))
            parts.append(self._url_config.render(projection))

        # PR-15: config control feedback panel (shown when a recent apply result exists)
        if self._control is not None:
            feedback = self._control.render_feedback()
            if feedback:
                last = self._control.last_result
                succeeded = last is not None and last.succeeded
                colour = _COLOUR_OK if succeeded else _COLOUR_WARN
                parts.append(_ansi.c(_BOARD_SEPARATOR, _BOLD))
                parts.append(_ansi.c("  ── Config Control ──", _BOLD))
                parts.append(_ansi.c(feedback, colour))

        parts.append(_ansi.c(_BOARD_SEPARATOR, _BOLD))
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


def _apply_toggle_arg(control: ConfigControlSurface, arg: str):
    """Parse ``PROVIDER=BOOL`` and call ``control.apply_toggle``."""
    if "=" not in arg:
        return ControlApplyResult(
            succeeded=False,
            operation="toggle_provider",
            error=f"--apply-toggle expects PROVIDER=BOOL format, got '{arg}'",
        )
    provider, _, raw_bool = arg.partition("=")
    enabled = raw_bool.strip().lower() in ("true", "1", "yes", "on")
    return control.apply_toggle(provider.strip(), enabled)


def _apply_set_url_arg(control: ConfigControlSurface, arg: str):
    """Parse ``ENDPOINT_NAME=URL`` and call ``control.apply_server_url``."""
    if "=" not in arg:
        return ControlApplyResult(
            succeeded=False,
            operation=ControlOperation.SET_SERVER_URL.value,
            error=f"--set-url expects ENDPOINT_NAME=URL format, got '{arg}'",
        )
    # Use split with maxsplit=1 so URLs containing '=' are preserved intact.
    endpoint_name, _, url = arg.partition("=")
    return control.apply_server_url(endpoint_name.strip(), url.strip())


def _apply_set_api_key_arg(control: ConfigControlSurface, arg: str):
    """Parse ``PROVIDER=KEY`` and call ``control.apply_api_key``."""
    if "=" not in arg:
        return ControlApplyResult(
            succeeded=False,
            operation=ControlOperation.SET_API_KEY.value,
            error=f"--set-api-key expects PROVIDER=KEY format, got '{arg}'",
        )
    provider, _, api_key = arg.partition("=")
    return control.apply_api_key(provider.strip(), api_key.strip())


def _format_control_result(result) -> str:
    """Format a ControlApplyResult for immediate CLI output."""
    lines = result.render_lines()
    return "\n".join(lines)


def run(
    host: str = "127.0.0.1",
    port: int = 8299,
    interval: float = 1.0,
    file_path: Optional[str] = None,
    from_stdin: bool = False,
    no_color: bool = False,
    apply_toggle: Optional[str] = None,
    apply_routing_policy: Optional[str] = None,
    set_url: Optional[str] = None,
    set_api_key: Optional[str] = None,
    show_url_config: bool = False,
    show_device_chain: bool = False,
) -> None:
    """Convenience function: create and run the status board app.

    Parameters
    ----------
    apply_toggle:
        Optional one-shot provider toggle in ``PROVIDER=BOOL`` form
        (e.g. ``"openai=true"``).  Applied before entering the monitor loop.
    apply_routing_policy:
        Optional one-shot routing policy (e.g. ``"prefer"``).
        Applied before entering the monitor loop.
    set_url:
        Optional one-shot endpoint URL in ``ENDPOINT_NAME=URL`` form
        (e.g. ``"android_ws_url=ws://100.x.x.x:8765/ws/device/{device_id}"``).
        Applied before entering the monitor loop.
    set_api_key:
        Optional one-shot API key in ``PROVIDER=KEY`` form
        (e.g. ``"openai=sk-..."``).
        Applied before entering the monitor loop.  Value is never echoed.
    show_url_config:
        When ``True``, render the URL/API-key configuration panel in every
        frame.
    show_device_chain:
        When ``True``, render the multi-device task chain panel in every
        frame.
    """
    control: Optional[ConfigControlSurface] = None

    # Apply any one-shot control operations before entering the monitor loop.
    if apply_toggle or apply_routing_policy or set_url or set_api_key:
        control = ConfigControlSurface()
        if apply_toggle:
            result = _apply_toggle_arg(control, apply_toggle)
            print(_format_control_result(result))
        if apply_routing_policy:
            result = control.apply_routing_policy(apply_routing_policy.strip())
            print(_format_control_result(result))
        if set_url:
            result = _apply_set_url_arg(control, set_url)
            print(_format_control_result(result))
        if set_api_key:
            result = _apply_set_api_key_arg(control, set_api_key)
            print(_format_control_result(result))

    app = StatusBoardV2App(
        host=host,
        port=port,
        interval=interval,
        file_path=file_path,
        from_stdin=from_stdin,
        no_color=no_color,
        control_surface=control,
        show_url_config=show_url_config,
        show_device_chain=show_device_chain,
    )
    app.run()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="status_board_v2",
        description=(
            "OpenClawd Status Board V2 — integrated operator console.  "
            "Displays RuntimeProjection: phase, domain, model topology, "
            "devices, task chains, URL/key config, and metrics.  "
            "Supports bounded config control, URL/key setup, and "
            "multi-device chain display."
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
        default=8299,
        help="Galaxy server port (default: 8299)",
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
    # PR-15: bounded config control arguments
    p.add_argument(
        "--apply-toggle",
        default=None,
        metavar="PROVIDER=BOOL",
        help=(
            "Apply a provider enable/disable toggle before entering monitor mode.  "
            "Format: PROVIDER=true|false  (e.g. openai=true).  "
            "Writes through canonical ConfigService to runtime/config.json."
        ),
    )
    p.add_argument(
        "--apply-routing-policy",
        default=None,
        metavar="MODE",
        help=(
            "Apply a routing policy before entering monitor mode.  "
            "Accepted values: strict | prefer | allow_fallback.  "
            "Writes through canonical ConfigService to runtime/config.json."
        ),
    )
    # Endpoint URL and API-key setup arguments
    p.add_argument(
        "--set-url",
        default=None,
        metavar="ENDPOINT_NAME=URL",
        help=(
            "Set a server/endpoint URL before entering monitor mode.  "
            "Format: ENDPOINT_NAME=URL  "
            "e.g. android_ws_url=ws://100.x.x.x:8765/ws/device/{device_id} "
            "or galaxy_gateway_url=http://localhost:9000 "
            "or nats_url=nats://localhost:4222.  "
            "Writes to runtime/config.json via ConfigService."
        ),
    )
    p.add_argument(
        "--set-api-key",
        default=None,
        metavar="PROVIDER=KEY",
        help=(
            "Store an API key for a provider before entering monitor mode.  "
            "Format: PROVIDER=KEY  e.g. openai=sk-... or anthropic=sk-ant-...  "
            "Key is stored in runtime/secrets.env and never echoed."
        ),
    )
    # Panel visibility flags
    p.add_argument(
        "--show-url-config",
        action="store_true",
        default=False,
        help=(
            "Show the URL / API-key configuration panel in every frame.  "
            "Useful for initial setup to verify which endpoints and keys are configured."
        ),
    )
    p.add_argument(
        "--show-device-chain",
        action="store_true",
        default=False,
        help=(
            "Show the multi-device and cross-device task chain panel in every frame."
        ),
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
        apply_toggle=args.apply_toggle,
        apply_routing_policy=args.apply_routing_policy,
        set_url=args.set_url,
        set_api_key=args.set_api_key,
        show_url_config=args.show_url_config,
        show_device_chain=args.show_device_chain,
    )


if __name__ == "__main__":
    main()
