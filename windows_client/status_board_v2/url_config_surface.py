"""
windows_client/status_board_v2/url_config_surface.py
======================================================
Operator URL and API-key configuration surface for Status Board V2.

Shows the current state of every required URL endpoint and provider
API key so the operator can immediately see what is missing and fill
it in via ``--set-url`` / ``--set-api-key`` CLI arguments.

Design constraints
------------------
- **Read-only rendering** — this surface never writes anything itself;
  all writes go through ``ConfigControlSurface``.
- **No secret leakage** — API key values are never rendered; only
  presence/absence is shown (``[set]`` vs ``[missing]``).
- **Graceful degradation** — if the ``ConfigService`` is unavailable
  the surface renders a minimal offline placeholder.
- **Complete at a glance** — shows every URL endpoint and every
  supported API provider in a single compact panel.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from . import _ansi

logger = logging.getLogger("Galaxy.UrlConfigSurface")

_SECTION = "─" * 52
_BOLD = _ansi.BOLD
_RESET = _ansi.RESET
_COLOUR_OK = "\033[32m"
_COLOUR_WARN = "\033[33m"
_COLOUR_ERROR = "\033[31m"

URL_CONFIG_SURFACE_AUTHORITY: str = (
    "URL_CONFIG_SURFACE_AUTHORITY_V1: "
    "windows_client.status_board_v2.url_config_surface renders the "
    "operator-visible URL and API-key configuration panel.  "
    "All writes flow through ConfigControlSurface → ConfigService."
)


class UrlConfigSurface:
    """
    Operator URL and API-key configuration panel.

    Renders a compact summary of:
    - All required server/endpoint URLs (galaxy_gateway_url, android_ws_url,
      nats_url) with ``[set]`` / ``[missing]`` status.
    - All supported LLM provider API keys with ``[set]`` / ``[missing]``
      status (value is never shown).
    - Inline instructions for filling missing values via CLI.

    Usage
    -----
    ::

        surface = UrlConfigSurface()
        print(surface.render({}))          # projection dict is ignored; reads directly

    Reading from ConfigService
    --------------------------
    The surface reads from ``core.config_service.ConfigService`` on each
    render call.  If the service is unavailable it renders an OFFLINE
    placeholder.
    """

    def render(self, projection: Dict[str, Any]) -> str:  # noqa: ARG002
        """
        Render the URL and API-key configuration panel.

        Parameters
        ----------
        projection:
            RuntimeProjection dict (not used; present for surface API
            consistency).

        Returns
        -------
        str
            Multi-line panel string ready for ``print()``.
        """
        try:
            from core.config_service import get_config_service  # noqa: PLC0415
            svc = get_config_service()
            return self._render_from_service(svc)
        except Exception as exc:  # pragma: no cover
            return self._render_offline(str(exc))

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _render_from_service(self, svc) -> str:
        lines = [
            _ansi.c("  ── Endpoint URLs ──", _BOLD),
        ]
        # Endpoint URLs
        try:
            urls = svc.get_all_endpoint_urls()
        except Exception:  # pragma: no cover
            urls = {}

        endpoint_labels = {
            "galaxy_gateway_url": "V2 Gateway (HTTP)",
            "android_ws_url":     "Android WS endpoint",
            "nats_url":           "NATS control-plane",
            "status_board_port":  "Status board port",
        }
        for key, label in endpoint_labels.items():
            val = urls.get(key, "")
            if val:
                status = _ansi.c("[set]", _COLOUR_OK)
                display = f"{val}"
            else:
                status = _ansi.c("[missing]", _COLOUR_WARN)
                display = f"not configured — use --set-url {key}=<value>"
            lines.append(f"  {label:<26} {status}  {display}")

        # API keys
        lines.append("")
        lines.append(_ansi.c("  ── Provider API Keys ──", _BOLD))
        try:
            provider_statuses = svc.get_provider_statuses()
        except Exception:  # pragma: no cover
            provider_statuses = []

        for ps in provider_statuses:
            enabled_label = _ansi.c("on ", _COLOUR_OK) if ps.enabled else _ansi.c("off", _COLOUR_WARN)
            if ps.has_key:
                key_label = _ansi.c("[set]    ", _COLOUR_OK)
            else:
                key_label = _ansi.c("[missing]", _COLOUR_WARN)
            hint = "" if ps.has_key else f"  ← --set-api-key {ps.provider_id}=<key>"
            lines.append(
                f"  {ps.provider_id:<14} enabled={enabled_label}  key={key_label}{hint}"
            )

        # CLI hints summary
        lines.append("")
        lines.append(_ansi.c("  ── Quick-fill commands ──", _BOLD))
        lines.append(
            "  --set-url android_ws_url=ws://<host>:8765/ws/device/{device_id}"
        )
        lines.append(
            "  --set-url galaxy_gateway_url=http://<host>:9000"
        )
        lines.append(
            "  --set-url nats_url=nats://<host>:4222"
        )
        lines.append(
            "  --set-api-key openai=sk-..."
        )
        lines.append(
            "  --apply-toggle openai=true"
        )

        return "\n".join(lines)

    def _render_offline(self, error: str) -> str:
        return _ansi.c(
            f"  ── URL Config ──  [OFFLINE: {error}]",
            _COLOUR_ERROR,
        )
