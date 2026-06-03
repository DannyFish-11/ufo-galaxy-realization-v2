"""
core/adapters/nats_adapter.py — NATS 传输适配器
"""

import logging
from typing import Any, Dict, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.NATS")


class NATSAdapter(TransportAdapter):
    """NATS 传输适配器。

    用于广播消息和结果回流（pub/sub）。
    """

    @property
    def transport_type(self) -> str:
        return "nats"

    def __init__(self, nats_bus: Optional[Any] = None) -> None:
        self._nats = nats_bus

    def _get_nats(self) -> Optional[Any]:
        if self._nats is None:
            try:
                from core.nats_bus import nats_bus
                self._nats = nats_bus
            except Exception:
                pass
        return self._nats

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """NATS 发送是 pub 到 topic。"""
        nats = self._get_nats()
        if nats is None or not nats.is_connected():
            return {"success": False, "error": "NATS not connected"}

        try:
            await nats._publish(target, message)
            return {"success": True, "via": "nats"}
        except Exception as e:
            logger.warning("NATS pub to %s failed: %s", target, e)
            return {"success": False, "error": f"NATS failed: {e}"}

    async def is_available(self, target: str) -> bool:
        """NATS 只要连接就可用（不检查具体 topic）。"""
        nats = self._get_nats()
        if nats is None:
            return False
        try:
            return nats.is_connected()
        except Exception:
            return False

    async def broadcast(self, message: Dict[str, Any], topic: str) -> Dict[str, Any]:
        """NATS 广播到 topic。"""
        return await self.send(message, topic)
