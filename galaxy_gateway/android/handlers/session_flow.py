"""Android session-flow protocol handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_session_migrate(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle Android session migration via the canonical session migration helper."""
    del bridge, websocket

    device_id = str(message.get("device_id") or "")
    correlation_id = message.get("message_id")
    payload = message.get("payload") or {}
    session_id = str(message.get("session_id") or payload.get("session_id") or "")
    target_device_id = str(
        message.get("target_device_id")
        or payload.get("target_device_id")
        or device_id
    )

    logger.info(
        "Android session migrate requested: session_id=%s source=%s target=%s",
        session_id,
        device_id,
        target_device_id,
    )

    try:
        from core.routes.sessions import migrate_session_via_canonical_manager

        result = await migrate_session_via_canonical_manager(
            session_id=session_id,
            source_device=device_id,
            target_device=target_device_id,
            context_override=payload.get("context") or {},
        )
    except Exception as exc:
        logger.warning("Android session migrate failed: %s", exc)
        result = {"success": False, "error": str(exc)}

    return MessageBuilder.session_migrate_ack(
        device_id=device_id,
        session_id=session_id,
        target_device_id=target_device_id,
        success=bool(result.get("success")),
        correlation_id=correlation_id,
        error=result.get("error"),
    )
