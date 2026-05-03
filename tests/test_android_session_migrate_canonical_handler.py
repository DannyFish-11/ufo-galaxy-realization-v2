from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_android_session_migrate_handler_uses_canonical_helper():
    from galaxy_gateway.android.handlers.session_flow import handle_session_migrate

    async def _fake_migrate_session_via_canonical_manager(**kwargs):
        return {"success": True, "session_id": kwargs["session_id"]}

    with patch(
        "core.routes.sessions.migrate_session_via_canonical_manager",
        _fake_migrate_session_via_canonical_manager,
    ):
        result = await handle_session_migrate(
            bridge=None,
            websocket=None,
            message={
                "type": "session_migrate",
                "device_id": "phone_1",
                "message_id": "msg_sm_1",
                "payload": {
                    "session_id": "session_1",
                    "target_device_id": "desktop_1",
                    "context": {"cursor": "keep"},
                },
            },
        )

    assert result["type"] == "session_migrate_ack"
    assert result["session_id"] == "session_1"
    assert result["target_device_id"] == "desktop_1"
    assert result["success"] is True
    assert result["correlation_id"] == "msg_sm_1"


def test_android_bridge_registers_session_migrate_handler():
    from galaxy_gateway.android_bridge import AndroidBridge
    from galaxy_gateway.protocol.aip_v3 import MessageType

    bridge = AndroidBridge()
    assert MessageType.SESSION_MIGRATE in bridge._message_handlers
