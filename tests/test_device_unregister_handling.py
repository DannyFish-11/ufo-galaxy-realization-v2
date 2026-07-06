"""tests/test_device_unregister_handling.py
=============================================
DEVICE_UNREGISTER ("device_unregister") wire messages were classified into
IngressEventKind.DEVICE_DISCONNECT but never dispatched anywhere in
websocket_handler.handle_message() - they fell through to the generic
"Unsupported message kind" error branch, even though DeviceManager already
had a fully real unregister_device() method that nothing ever called for
this path (only the transport-level disconnect() used it).

Validates that an explicit device_unregister message now triggers the same
real cleanup path as an actual socket disconnect, and that the connection
is closed server-side afterward.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_unregister_msg(device_id: str = "dev-unreg-001") -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": "device_unregister",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        "route_mode": "direct",
        "payload": {},
    }


class TestDeviceUnregisterDispatch:
    def _make_ws(self):
        ws = MagicMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    def test_device_unregister_triggers_real_cleanup_and_closes_socket(self):
        from galaxy_gateway.websocket_handler import handle_message

        ws = self._make_ws()
        msg = _make_unregister_msg()

        with patch("galaxy_gateway.websocket_handler.connection_manager.disconnect",
                   new=AsyncMock()) as mock_disconnect:
            _run_async(handle_message("conn-unreg-001", msg, ws))

        mock_disconnect.assert_awaited_once_with("conn-unreg-001")
        ws.close.assert_awaited_once()

    def test_device_unregister_is_not_delegated_to_android_bridge(self):
        """device_unregister is a transport-class message, not an Android
        business-domain message - it must be handled locally, not delegated."""
        from galaxy_gateway.websocket_handler import handle_message

        ws = self._make_ws()
        msg = _make_unregister_msg()

        mock_bridge = MagicMock()
        mock_bridge.handle_message = AsyncMock(return_value=None)

        with patch("galaxy_gateway.android_bridge.android_bridge", mock_bridge), \
             patch("galaxy_gateway.websocket_handler.connection_manager.disconnect",
                   new=AsyncMock()) as mock_disconnect:
            _run_async(handle_message("conn-unreg-002", msg, ws))

        mock_bridge.handle_message.assert_not_awaited()
        mock_disconnect.assert_awaited_once_with("conn-unreg-002")

    def test_device_unregister_survives_disconnect_failure(self):
        """A failure in the cleanup path must be caught, not raised out of
        handle_message (it's a fire-and-forget dispatch from the WS loop)."""
        from galaxy_gateway.websocket_handler import handle_message

        ws = self._make_ws()
        msg = _make_unregister_msg()

        with patch("galaxy_gateway.websocket_handler.connection_manager.disconnect",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            # Must not raise.
            _run_async(handle_message("conn-unreg-003", msg, ws))
