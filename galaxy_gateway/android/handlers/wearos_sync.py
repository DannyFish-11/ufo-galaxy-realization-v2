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

    # Compressed format for Wear OS (minimal fields)
    wear_msg = {
        "t": "se",  # type: state_event (compressed)
        "cat": "ph",  # category: phase (compressed)
        "act": phase[:3],  # action: first 3 chars of phase
        "ts": payload.get("timestamp", 0),
        "src": "dpr",  # source: desktop_presence_runtime (compressed)
    }

    try:
        await device.websocket.send_json(wear_msg)
        logger.debug("WearOS sync: phase=%s sent to %s", phase, device_id)
    except Exception as exc:
        logger.debug("WearOS sync: send failed: %s", exc)


def is_wearos_device(device_type: str) -> bool:
    """Check if device type indicates Wear OS."""
    return device_type.lower() in {
        "wear_os", "wearos", "watch", "galaxy_watch",
    }
