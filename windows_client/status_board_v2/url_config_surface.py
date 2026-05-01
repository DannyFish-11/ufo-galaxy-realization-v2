"""
windows_client/status_board_v2/url_config_surface.py
=====================================================
URL Configuration Surface — interactive endpoint fill-in for the status board.

Renders a compact summary of all network endpoint URLs that need to be
configured for the integrated dual-repo system to operate, and provides
CLI arguments to set them.

This surface addresses the operator concern:

    "there are no convenient fill-in places for URLs (gateway URL, NATS URL,
     ATS URL, Android gateway URL, …) — many places are incomplete"

The surface shows:
  - Current value of each URL (or [NOT SET] if absent)
  - Whether each URL is required for specific features
  - CLI instructions for setting missing URLs

Usage (inside status board)
----------------------------
::

    python -m windows_client.status_board_v2 --set-url gateway_url=ws://10.0.0.1:8765

    python -m windows_client.status_board_v2 --set-url nats_url=nats://10.0.0.1:4222

    python -m windows_client.status_board_v2 --set-url ats_url=https://10.0.0.1:8443

    python -m windows_client.status_board_v2 --set-url android_gateway_url=ws://10.0.0.1:8765

    python -m windows_client.status_board_v2 --set-url webrtc_stun_url=stun:stun.l.google.com:19302

    # Set Android inference mode (center = no local llama.cpp/NCNN needed)
    python -m windows_client.status_board_v2 --set-android-inference-mode center

    # Set a provider API key
    python -m windows_client.status_board_v2 --set-api-key openai=sk-...

All writes go through the canonical ConfigService path:
    ConfigControlSurface → ConfigService → ConfigStore → runtime/config.json
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import _ansi


# ---------------------------------------------------------------------------
# URL metadata
# ---------------------------------------------------------------------------

_URL_META: List[Dict[str, Any]] = [
    {
        "key":      "gateway_url",
        "label":    "Gateway URL",
        "required": True,
        "feature":  "cross-device dispatch, Android connection",
        "example":  "ws://YOUR_SERVER_IP:8765",
        "note":     "Main WebSocket gateway.  Both V2 and Android must use this.",
    },
    {
        "key":      "android_gateway_url",
        "label":    "Android Gateway URL",
        "required": False,
        "feature":  "Android connection (overrides gateway_url for Android)",
        "example":  "ws://YOUR_SERVER_IP:8765",
        "note":     "If blank, Android uses gateway_url.",
    },
    {
        "key":      "nats_url",
        "label":    "NATS URL",
        "required": False,
        "feature":  "NATS control-plane bus (optional)",
        "example":  "nats://YOUR_SERVER_IP:4222",
        "note":     "Required only when NATS-based message bus is enabled.",
    },
    {
        "key":      "ats_url",
        "label":    "ATS URL",
        "required": False,
        "feature":  "ATS (Adaptive Transport Service) endpoint",
        "example":  "https://YOUR_SERVER_IP:8443",
        "note":     "Required when ATS routing is enabled for long-run transport.",
    },
    {
        "key":      "webrtc_stun_url",
        "label":    "WebRTC STUN URL",
        "required": False,
        "feature":  "WebRTC peer-to-peer connections",
        "example":  "stun:stun.l.google.com:19302",
        "note":     "Used for NAT traversal in WebRTC signalling.  Optional.",
    },
]


# ---------------------------------------------------------------------------
# Surface renderer
# ---------------------------------------------------------------------------

class URLConfigSurface:
    """
    Renders the URL configuration status panel for the status board.

    Shows each network URL, its current value, and whether it is set.
    Provides operator guidance for filling in missing values.
    """

    def render(self, _projection: Optional[Dict[str, Any]] = None) -> str:
        """
        Render the URL configuration panel.

        Parameters
        ----------
        _projection:
            Ignored — this surface reads config directly from ConfigService.

        Returns
        -------
        str
            Multi-line display string ready for ``print()``.
        """
        url_states = self._read_url_states()
        android_mode = self._read_android_mode()
        lines: List[str] = []

        lines.append(_ansi.c("  ── Network URLs ──", _ansi.BOLD))
        for meta in _URL_META:
            key = meta["key"]
            label = meta["label"]
            value = url_states.get(key, "")
            required = meta["required"]
            if value:
                display = _ansi.c(f"  ✓  {label:<28} {value}", "\033[32m")
            else:
                req_tag = "[required]" if required else "[optional]"
                display = _ansi.c(
                    f"  ✗  {label:<28} [NOT SET]  {req_tag}  → "
                    f"--set-url {key}={meta['example']}",
                    "\033[33m",
                )
            lines.append(display)

        lines.append("")
        lines.append(_ansi.c("  ── Android Inference Mode ──", _ansi.BOLD))
        mode_colour = "\033[32m" if android_mode == "center" else "\033[33m"
        lines.append(
            _ansi.c(
                f"  {'✓' if android_mode else '✗'}  inference_mode"
                f"                 {android_mode or '[NOT SET]'}",
                mode_colour,
            )
        )
        if android_mode == "center":
            lines.append(
                "     → Android uses center-side VLM (no llama.cpp/NCNN needed)"
            )
        elif android_mode == "local":
            lines.append(
                "     ⚠  Android uses local inference (llama.cpp + NCNN required in APK)"
            )
        elif android_mode == "hybrid":
            lines.append(
                "     → Android tries local inference first, falls back to center"
            )
        else:
            lines.append(
                "     → --set-android-inference-mode center|local|hybrid"
            )

        # Show missing required URLs summary
        missing_required = [
            meta["key"] for meta in _URL_META
            if meta["required"] and not url_states.get(meta["key"])
        ]
        if missing_required:
            lines.append("")
            lines.append(
                _ansi.c(
                    f"  ⚠  {len(missing_required)} required URL(s) not set — "
                    "system may not connect correctly.",
                    "\033[31m",
                )
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_url_states(self) -> Dict[str, str]:
        """Read all network URLs from ConfigService."""
        states: Dict[str, str] = {}
        try:
            from core.config_service import get_config_service
            svc = get_config_service()
            for meta in _URL_META:
                try:
                    states[meta["key"]] = svc.get_network_url(meta["key"])
                except Exception:
                    states[meta["key"]] = ""
        except Exception:
            pass
        return states

    def _read_android_mode(self) -> str:
        """Read the Android inference mode from ConfigService."""
        try:
            from core.config_service import get_config_service
            cfg = get_config_service()._store.read_config()
            return cfg.get("android", {}).get("inference_mode", "")
        except Exception:
            return ""
