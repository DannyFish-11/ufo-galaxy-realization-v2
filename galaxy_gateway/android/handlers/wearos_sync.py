"""
galaxy_gateway/android/handlers/wearos_sync.py

PR-WEAR-SYNC: Wear OS State Synchronization Handler

Handles state sync for Wear OS devices, which use a simplified
protocol subset optimized for watch constraints (small screen,
limited bandwidth, intermittent connectivity).

Wear OS devices receive the same state_event messages as Android
phones but only process phase changes (not full task state).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


# M2 fixed: explicit short-code mapping table for phase → WearOS action codes
_PHASE_CODE_MAP: Dict[str, str] = {
    "silent": "sil",
    "liminal": "lim",
    "manifest": "man",
    # Add new phases here with explicit codes to avoid collision
}


async def handle_wearos_state_sync(
    bridge: "AndroidBridge",
    device_id: str,
    phase: str,
    payload: Dict[str, Any],
) -> None:
    """Send state sync to Wear OS device.

    Wear OS uses a compressed message format to minimize
    bandwidth usage on the watch's limited connection.
    """
    device = bridge._devices.get(device_id)
    if device is None or device.websocket is None:
        logger.debug("WearOS sync: device %s not connected", device_id)
        return

    # M2 fixed: use explicit mapping table instead of fragile phase[:3]
    phase_code = _PHASE_CODE_MAP.get(phase.lower(), phase[:3])
    wear_msg = {
        "t": "se",  # type: state_event (compressed)
        "cat": "ph",  # category: phase (compressed)
        "act": phase_code,  # M2 fixed: explicit mapped short code
        "ts": payload.get("timestamp", 0),
        "src": "dpr",  # source: desktop_presence_runtime (compressed)
        "v": 1,  # M2 fixed: add version for protocol negotiation
    }

    try:
        # PR-AIP-UNIFIED: Route through AIPTransport instead of direct WS
        from core.aip_transport import get_aip_transport
        msg = {
            **wear_msg,
            "_transport": "auto",
            "version": "3.0",
        }
        result = await get_aip_transport().send(msg, device_id)
        if result.get("success"):
            logger.debug("WearOS sync: phase=%s sent to %s", phase, device_id)
        else:
            # Fallback: direct WS
            await device.websocket.send_json(wear_msg)
    except Exception as exc:
        logger.debug("WearOS sync: send failed: %s", exc)


def is_wearos_device(device_type: str) -> bool:
    """Check if device type indicates Wear OS."""
    return device_type.lower() in {
        "wear_os", "wearos", "watch", "galaxy_watch",
    }
