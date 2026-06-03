"""
galaxy_gateway/android/handlers/peer_exchange.py
=================================================
PR-8: Canonical stateful handlers for PEER_ANNOUNCE and PEER_EXCHANGE
messages in the Android-bridge ingress path.

Replaces the generic-forward placeholder with handlers that integrate
with ``MeshCoordinator`` so that:

* ``handle_peer_announce`` — registers the announcing device as a peer
  and returns the current peer list as a ``peer_exchange`` response.
* ``handle_peer_exchange`` — returns the current peer list to the
  requesting device.

Both handlers carry structured mesh state (peer count, coordinator
availability, session ID) so downstream systems can track mesh topology
rather than ignoring the message.

Note
----
The WS-transport pre-dispatch path in
``galaxy_gateway.transport.websocket_server.WebSocketManager._handle_mesh_message``
already handles these types for the WS-transport layer.  This module
handles the same types when they arrive through the Android-bridge
ingress path (``android_bridge.py`` → handler dispatch table).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-8 sentinel — canonical handler authority for peer exchange messages.
PEER_EXCHANGE_HANDLER_IS_CANONICAL_PR8: str = (
    "PEER_EXCHANGE_HANDLER::CANONICAL_STATEFUL_PR8"
)


def _get_mesh_coordinator() -> Optional[Any]:
    """Return the MeshCoordinator singleton, or ``None`` if unavailable."""
    try:
        from core.mesh_coordinator import get_mesh_coordinator
        return get_mesh_coordinator()
    except ImportError:
        logger.debug("MeshCoordinator not available")
        return None
    except Exception as exc:
        logger.debug("Failed to obtain MeshCoordinator: %s", exc)
        return None


async def handle_peer_announce(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle a PEER_ANNOUNCE message from an Android device.

    Registers the device as a peer in ``MeshCoordinator`` and returns the
    current peer list so the device can start building its direct-connect
    table.

    This replaces the generic-forward placeholder that previously returned
    a bare ``peer_announce_ack`` with no mesh coordinator integration.
    """
    device_id = message.get("device_id", "unknown")
    payload = message.get("payload") or {}

    logger.info(
        "PEER_ANNOUNCE from device_id=%s local_ip=%s local_port=%s",
        device_id,
        payload.get("local_ip") or message.get("local_ip", ""),
        payload.get("local_port") or message.get("local_port", 0),
    )

    mesh = _get_mesh_coordinator()
    peer_list: list = []
    your_peer: Optional[Dict] = None
    coordinator_available = mesh is not None

    if mesh is not None:
        try:
            # PR-28: Extract tailscale_ip from payload if present
            payload = message.get("payload") or {}
            ts_ip = payload.get("tailscale_ip") or message.get("tailscale_ip", "")
            if ts_ip and "tailscale_ip" not in str(message):
                # Ensure tailscale_ip is in the message dict for handle_peer_announce
                message["tailscale_ip"] = ts_ip
            # Register / update the peer entry.
            peer = mesh.handle_peer_announce(device_id, message)
            # Build the peer list excluding the announcing device.
            peer_list = mesh.build_peer_exchange(exclude_device=device_id)
            if hasattr(peer, "to_dict"):
                your_peer = peer.to_dict()
        except Exception as exc:
            logger.warning(
                "PEER_ANNOUNCE mesh integration failed (non-fatal):"
                " device_id=%s error=%s",
                device_id,
                exc,
            )

    return {
        "version": "3.0",
        "type": "peer_exchange",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "peers": peer_list,
        "peer_count": len(peer_list),
        "your_peer": your_peer,
        "coordinator_available": coordinator_available,
        "lifecycle_state": "peer_registered",
        "correlation_id": message.get("message_id"),
    }


async def handle_peer_exchange(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle a PEER_EXCHANGE message from an Android device.

    Returns the current peer list from ``MeshCoordinator`` so the device
    can refresh its direct-connect table.

    This replaces the generic-forward placeholder that previously returned
    a bare ``peer_exchange_ack`` with no mesh coordinator integration.
    """
    device_id = message.get("device_id", "unknown")

    logger.info("PEER_EXCHANGE request from device_id=%s", device_id)

    mesh = _get_mesh_coordinator()
    peer_list: list = []
    coordinator_available = mesh is not None

    if mesh is not None:
        try:
            peer_list = mesh.build_peer_exchange(exclude_device=device_id)
        except Exception as exc:
            logger.warning(
                "PEER_EXCHANGE mesh integration failed (non-fatal):"
                " device_id=%s error=%s",
                device_id,
                exc,
            )

    return {
        "version": "3.0",
        "type": "peer_exchange",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "peers": peer_list,
        "peer_count": len(peer_list),
        "coordinator_available": coordinator_available,
        "lifecycle_state": "peers_refreshed",
        "correlation_id": message.get("message_id"),
    }
