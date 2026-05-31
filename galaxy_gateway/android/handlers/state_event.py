"""
galaxy_gateway/android/handlers/state_event.py

PR-CROSS-DEVICE-SYNC: State Event Handler

Handles STATE_EVENT messages from DesktopPresenceRuntime (Windows → Android).
These are proactive cross-device phase broadcasts, not request-response.

Message format (AIP v3):
    {
        "type": "state_event",
        "event_category": "phase",
        "event_action": "manifest|liminal|silent",
        "device_id": "v2_desktop",
        "timestamp": 1700000000000,
        "session_id": "...",
        "trace_id": "...",
        "aip_version": "3.0",
        "payload": {
            "from_phase": "silent",
            "to_phase": "manifest",
            "source": "desktop_presence_runtime",
            "sync_type": "cross_device_broadcast"
        },
        "phase": "manifest"  # legacy backward-compatible
    }
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_state_event(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle STATE_EVENT from Windows — update Android device phase.

    This is the receiving end of PR-CROSS-DEVICE-SYNC. When Windows
    DesktopPresenceRuntime transitions phase, it proactively pushes
    a state_event to all connected Android devices. This handler
    receives and processes those events.
    """
    device_id = message.get("device_id", "unknown")
    event_category = message.get("event_category", "unknown")
    event_action = message.get("event_action", "")
    payload = message.get("payload", {}) if isinstance(message.get("payload"), dict) else {}

    # Log the state event
    logger.info(
        "StateEvent: received %s/%s from %s (session=%s)",
        event_category,
        event_action,
        device_id,
        message.get("session_id", "")[:8],
    )

    # Handle phase category
    if event_category == "phase":
        phase = event_action or message.get("phase", "")
        if phase:
            # Store the cross-device phase on the bridge for the device
            # This allows the Android device to query its synced phase
            _update_device_synced_phase(bridge, device_id, phase, payload)

    # Acknowledge receipt
    return {
        "type": "state_event_ack",
        "device_id": device_id,
        "status": "received",
        "event_category": event_category,
        "event_action": event_action,
        "message_id": message.get("message_id"),
        "trace_id": message.get("trace_id", ""),
    }


def _update_device_synced_phase(
    bridge: "AndroidBridge",
    source_device_id: str,
    phase: str,
    payload: Dict[str, Any],
) -> None:
    """Update the synced phase state for the desktop device.

    Args:
        bridge: AndroidBridge instance
        source_device_id: The Windows desktop device ID
        phase: The new phase (silent/liminal/manifest)
        payload: Full state_event payload
    """
    try:
        # Store phase in device metadata for introspection
        # Use a well-known key for cross-device phase tracking
        device = bridge._devices.get(source_device_id)
        if device is not None:
            if not hasattr(device, "synced_phase"):
                device.synced_phase = {}
            device.synced_phase["current"] = phase.lower()
            device.synced_phase["from_phase"] = payload.get("from_phase", "")
            device.synced_phase["timestamp"] = payload.get("timestamp", 0)
            device.synced_phase["source"] = payload.get("source", "")

            logger.info(
                "CrossDeviceSync: Android device now tracking desktop phase=%s "
                "(was=%s, source=%s)",
                phase.lower(),
                payload.get("from_phase", ""),
                payload.get("source", ""),
            )
        else:
            logger.debug(
                "CrossDeviceSync: desktop device %s not in _devices, "
                "skipping phase state update",
                source_device_id,
            )
    except Exception as exc:
        logger.warning("CrossDeviceSync: phase state update failed: %s", exc)
