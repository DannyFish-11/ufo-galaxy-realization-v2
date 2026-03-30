"""
galaxy_gateway/android/handlers/generic.py

Generic forward handler for message types without specific handlers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_generic_forward(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """通用占位处理器：记录日志并返回 ACK（后续可扩展为实际转发逻辑）"""
    msg_type = message.get("type")
    device_id = message.get("device_id")
    logger.debug("Received %s from %s: forwarding", msg_type, device_id)
    return {
        "type": f"{msg_type}_ack" if msg_type else "ack",
        "device_id": device_id,
        "status": "received",
        "message_id": message.get("message_id"),
    }
