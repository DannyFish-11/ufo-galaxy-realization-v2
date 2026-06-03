"""
core/adapters/websocket_adapter.py — WebSocket 传输适配器
"""

import logging
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.WebSocket")


class WebSocketAdapter(TransportAdapter):
    """WebSocket 传输适配器。

    始终在线的长连接，点对点双向通信。
    """

    @property
    def transport_type(self) -> str:
        return "websocket"

    def __init__(self, ws_manager: Optional[Any] = None) -> None:
        self._ws = ws_manager

    def _get_ws(self) -> Optional[Any]:
        if self._ws is None:
            try:
                from galaxy_gateway import connection_manager
                self._ws = connection_manager
            except Exception:
                pass
        return self._ws

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        ws = self._get_ws()
        if ws is None:
            return {"success": False, "error": "WebSocket manager not available"}

        try:
            await ws.send_message(target, message)
            return {"success": True, "via": "websocket"}
        except Exception as e:
            logger.warning("WS send to %s failed: %s", target, e)
            return {"success": False, "error": f"WS failed: {e}"}

    async def is_available(self, target: str) -> bool:
        ws = self._get_ws()
        if ws is None:
            return False
        try:
            return await ws.is_device_connected(target)
        except Exception:
            return False
