"""
core/aip_transport.py — AIP v3 统一传输层
==========================================

AIP v3 = 统一协议 + 混合传输

职责：
- 根据 AIPMessage.transport 字段选择传输方式
- WebSocket: 点对点传输（主路径）
- NATS: 广播/回流（pub/sub）
- 未来: DataChannel, MQTT, BLE...

与 Mesh 的关系：
- Mesh = 设备协同层（发现、组网、拓扑）
- AIPTransport 使用 Mesh 的拓扑信息优化传输
- 但不通过 Mesh 发送消息

与 NATS 的关系：
- NATS = 任务广播层
- AIPTransport 使用 NATS 做广播和结果回流
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.AIPTransport")


class AIPTransport:
    """AIP v3 统一传输入口。

    所有设备间通信统一通过此类发送，
    根据 message.transport 字段自动选择底层传输方式。
    """

    def __init__(self) -> None:
        self._ws_manager: Optional[Any] = None
        self._nats_bus: Optional[Any] = None
        self._mesh: Optional[Any] = None

    def _get_ws(self) -> Any:
        if self._ws_manager is None:
            try:
                from galaxy_gateway import connection_manager
                self._ws_manager = connection_manager
            except Exception:
                pass
        return self._ws_manager

    def _get_nats(self) -> Any:
        if self._nats_bus is None:
            try:
                from core.nats_bus import nats_bus
                self._nats_bus = nats_bus
            except Exception:
                pass
        return self._nats_bus

    def _get_mesh(self) -> Any:
        if self._mesh is None:
            try:
                from core.mesh_coordinator import get_mesh_coordinator
                self._mesh = get_mesh_coordinator()
            except Exception:
                pass
        return self._mesh

    async def send(
        self,
        message: Dict[str, Any],
        target_device: str,
    ) -> Dict[str, Any]:
        """发送 AIP v3 消息到目标设备。

        根据 message["transport"] 字段选择传输方式：
        - "websocket" (默认): WebSocket 点对点
        - "nats": NATS pub/sub
        - "mesh": 查询 Mesh 拓扑后走 WebSocket
        """
        transport = message.get("transport", "websocket")

        if transport == "nats":
            return await self._send_via_nats(message, target_device)

        if transport == "mesh":
            # 查询 Mesh 拓扑建议，但最终走 WS
            mesh = self._get_mesh()
            if mesh:
                peer = mesh.get_peer(target_device)
                if peer:
                    message["_mesh_advice"] = {
                        "reachable_direct": peer.reachable_direct,
                        "latency_ms": peer.latency_ms,
                    }

        # 默认: WebSocket 点对点
        return await self._send_via_ws(message, target_device)

    async def _send_via_ws(
        self,
        message: Dict[str, Any],
        target_device: str,
    ) -> Dict[str, Any]:
        """WebSocket 点对点传输"""
        ws = self._get_ws()
        if ws is None:
            return {"success": False, "error": "WebSocket manager not available"}

        try:
            await ws.send_message(target_device, message)
            return {"success": True, "via": "websocket"}
        except Exception as e:
            logger.warning("WS send to %s failed: %s", target_device, e)
            return {"success": False, "error": f"WS failed: {e}"}

    async def _send_via_nats(
        self,
        message: Dict[str, Any],
        target_device: str,
    ) -> Dict[str, Any]:
        """NATS pub/sub 传输（广播/回流）"""
        nats = self._get_nats()
        if nats is None or not nats.is_connected():
            return {"success": False, "error": "NATS not connected"}

        try:
            topic = f"galaxy.tasks.dispatch.{target_device}"
            await nats._publish(topic, message)
            return {"success": True, "via": "nats"}
        except Exception as e:
            logger.warning("NATS pub to %s failed: %s", target_device, e)
            return {"success": False, "error": f"NATS failed: {e}"}

    async def broadcast_result(
        self,
        task_id: str,
        result: Dict[str, Any],
    ) -> None:
        """通过 NATS 广播任务结果（回流）"""
        nats = self._get_nats()
        if nats and nats.is_connected():
            try:
                await nats._publish(
                    f"galaxy.tasks.result.{task_id}",
                    result,
                )
            except Exception as e:
                logger.debug("Result backflow failed: %s", e)


# Singleton
_transport: Optional[AIPTransport] = None


def get_aip_transport() -> AIPTransport:
    global _transport
    if _transport is None:
        _transport = AIPTransport()
    return _transport
