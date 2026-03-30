"""
galaxy_gateway/android/handlers/diagnostics.py

Handles diagnostics_payload messages from Android devices.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_diagnostics_payload(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理诊断数据上报"""
    device_id = message.get("device_id")
    error_type = message.get("error_type")
    error_context = message.get("error_context")
    task_id = message.get("task_id")
    node_name = message.get("node_name")
    logger.warning(
        "Diagnostics from %s: error_type=%s, task_id=%s, node=%s, context=%s",
        device_id, error_type, task_id, node_name, error_context,
    )

    return MessageBuilder.diagnostics_payload_ack(
        device_id=device_id or "unknown",
        accepted=True,
        message="diagnostics_payload accepted",
    )
