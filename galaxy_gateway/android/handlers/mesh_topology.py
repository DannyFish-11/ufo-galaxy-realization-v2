"""
galaxy_gateway/android/handlers/mesh_topology.py
=================================================
PR-8: Canonical stateful handler for MESH_TOPOLOGY messages in the
Android-bridge ingress path.

Replaces the generic-forward placeholder with a handler that integrates
with ``MeshCoordinator`` and returns the full mesh topology — including
peer count, connection types, and probe status — rather than a bare ACK.

Note
----
The WS-transport pre-dispatch path in
``galaxy_gateway.transport.websocket_server.WebSocketManager._handle_mesh_message``
already handles ``mesh_topology`` for the WS-transport layer.  This
module handles the same type when it arrives through the Android-bridge
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

# PR-8 sentinel — canonical handler authority for MESH_TOPOLOGY messages.
MESH_TOPOLOGY_HANDLER_IS_CANONICAL_PR8: str = "MESH_TOPOLOGY_HANDLER::CANONICAL_STATEFUL_PR8"


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


async def handle_mesh_topology(bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
    """Handle a MESH_TOPOLOGY message from an Android device.

    Returns the full mesh topology from ``MeshCoordinator``, including:

    * ``topology`` — raw topology dict (peer entries, connection types).
    * ``peer_count`` — number of known peers.
    * ``coordinator_available`` — whether MeshCoordinator is available.
    * ``lifecycle_state`` — always ``'topology_returned'`` on success.

    This replaces the generic-forward placeholder that previously returned
    a bare ``mesh_topology_ack`` with no MeshCoordinator integration in
    the Android-bridge ingress path.
    """
    device_id = message.get("device_id", "unknown")

    logger.info("MESH_TOPOLOGY request from device_id=%s", device_id)

    mesh = _get_mesh_coordinator()
    topology: Dict = {}
    peer_count: int = 0
    coordinator_available = mesh is not None

    if mesh is not None:
        try:
            topology = mesh.get_topology()
            # Extract peer count from topology for convenience.
            peers = topology.get("peers", {})
            if isinstance(peers, dict):
                peer_count = len(peers)
            elif isinstance(peers, int):
                peer_count = peers
            else:
                peer_count = 0
        except Exception as exc:
            logger.warning(
                "MESH_TOPOLOGY mesh integration failed (non-fatal):" " device_id=%s error=%s",
                device_id,
                exc,
            )

    # 网格镜像:这一份拓扑答复只回给发问的那台设备。镜像上网格,别的节点才能
    # 拿同一时刻的同一份拓扑做对账 —— 拓扑分歧正是网格类故障最难查的一种。
    _mirror_mesh_topology(device_id, message, topology, peer_count)

    return {
        "version": "3.0",
        "type": "mesh_topology",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "topology": topology,
        "peer_count": peer_count,
        "coordinator_available": coordinator_available,
        "lifecycle_state": "topology_returned",
        "correlation_id": message.get("message_id"),
    }


def _mirror_mesh_topology(device_id: str, message: Dict[str, Any], topology: Dict, peer_count: int) -> None:
    """把 MESH_TOPOLOGY 应答镜像到 NATS 网格面。best-effort。"""
    try:
        from core.aip_mesh_mirror import mirror_to_mesh  # noqa: PLC0415
        from core.schemas.aip_v3 import MeshTopologyMsg  # noqa: PLC0415

        mirror_to_mesh(
            MeshTopologyMsg(
                device_id=str(device_id or ""),
                mesh_id=str(message.get("mesh_id") or ""),
                topology=dict(topology) if isinstance(topology, dict) else {},
                peer_count=int(peer_count),
                request_type="update",  # 这是答复,不是发问
                session_id=str(message.get("session_id") or ""),
                trace_id=str(message.get("trace_id") or ""),
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("mesh_topology 网格镜像跳过:%s", exc)
