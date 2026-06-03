"""
core/aip_transport.py — AIP v3 统一传输层
==========================================

AIP v3 = 统一协议 + 混合传输

所有消息（Mesh协同、NATS任务、设备控制）统一通过此类发送。
根据 message["transport"] 字段自动选择底层传输适配器。

支持的传输适配器:
- websocket: WebSocket 点对点（主路径）
- nats: NATS pub/sub（广播/回流）
- tcp: TCP 直连（P2P）
- mqtt: MQTT 发布/订阅
- ble: Bluetooth LE
- serial: 串口通信
- udp: UDP 报文

架构:
    Mesh/NATS/App ──► AIPTransport.send()
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              适配器注册表    默认fallback
                    │
            transport → adapter
                    │
            ┌───┬───┼───┬───┬───┐
            ▼   ▼   ▼   ▼   ▼   ▼
           WS NATS TCP MQTT BLE SERIAL
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Awaitable

logger = logging.getLogger("Galaxy.AIPTransport")


class TransportAdapter(ABC):
    """传输适配器抽象基类。

    所有传输协议（WS/NATS/TCP/MQTT/BLE/SERIAL）必须实现此接口。
    """

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """返回传输类型标识: websocket, nats, tcp, mqtt, ble, serial, udp"""

    @abstractmethod
    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """发送 AIP v3 消息到目标。

        Args:
            message: AIP v3 消息字典（必须含 transport 字段）
            target: 目标设备ID或topic

        Returns:
            {"success": bool, "via": str, ...}
        """

    @abstractmethod
    async def is_available(self, target: str) -> bool:
        """检查目标是否可通过此传输到达。"""

    async def close(self) -> None:
        """清理资源（可选实现）。"""
        pass


class AIPTransport:
    """AIP v3 统一传输管理器。

    所有设备间通信的统一入口。
    通过注册 TransportAdapter 实现多协议混合传输。
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, TransportAdapter] = {}
        self._default_transport: str = "websocket"

    def register_adapter(self, adapter: TransportAdapter) -> None:
        """注册传输适配器。"""
        self._adapters[adapter.transport_type] = adapter
        logger.info("Transport adapter registered: %s", adapter.transport_type)

    def unregister_adapter(self, transport_type: str) -> None:
        """注销传输适配器。"""
        adapter = self._adapters.pop(transport_type, None)
        if adapter:
            logger.info("Transport adapter unregistered: %s", transport_type)

    def get_adapter(self, transport_type: str) -> Optional[TransportAdapter]:
        """获取指定类型的适配器。"""
        return self._adapters.get(transport_type)

    def list_adapters(self) -> List[str]:
        """返回已注册的传输类型列表。"""
        return list(self._adapters.keys())

    async def send(
        self,
        message: Dict[str, Any],
        target: str,
        transport: Optional[str] = None,
    ) -> Dict[str, Any]:
        """统一发送入口。

        根据 transport 参数或 message["transport"] 字段选择适配器。
        如果指定适配器不可用，fallback 到默认适配器。

        Args:
            message: AIP v3 消息字典
            target: 目标设备ID或topic
            transport: 强制指定传输类型（覆盖 message 中的字段）

        Returns:
            {"success": bool, "via": str, ...}
        """
        ttype = transport or message.get("transport", self._default_transport)

        adapter = self._adapters.get(ttype)
        if adapter is None:
            logger.warning("Transport adapter '%s' not registered, fallback to '%s'",
                           ttype, self._default_transport)
            adapter = self._adapters.get(self._default_transport)
            if adapter is None:
                return {
                    "success": False,
                    "error": f"No adapter for '{ttype}' and default '{self._default_transport}' not registered",
                }

        # 检查目标是否可达
        if not await adapter.is_available(target):
            logger.debug("Target '%s' not available via '%s', trying fallback", target, ttype)
            fallback = self._adapters.get(self._default_transport)
            if fallback and await fallback.is_available(target):
                adapter = fallback
                ttype = self._default_transport
            else:
                return {
                    "success": False,
                    "error": f"Target '{target}' not available via '{ttype}' or fallback",
                }

        try:
            result = await adapter.send(message, target)
            result["_transport_used"] = ttype
            return result
        except Exception as e:
            logger.warning("Send via '%s' failed: %s", ttype, e)
            return {"success": False, "error": f"{ttype} send failed: {e}"}

    async def broadcast(
        self,
        message: Dict[str, Any],
        topic: str,
    ) -> Dict[str, Any]:
        """广播消息（优先 NATS）。"""
        message["transport"] = "nats"
        return await self.send(message, topic, transport="nats")

    async def close_all(self) -> None:
        """关闭所有适配器。"""
        for adapter in self._adapters.values():
            try:
                await adapter.close()
            except Exception as e:
                logger.debug("Error closing adapter '%s': %s", adapter.transport_type, e)


# Singleton
_transport_instance: Optional[AIPTransport] = None


def get_aip_transport() -> AIPTransport:
    """获取全局 AIPTransport 实例。"""
    global _transport_instance
    if _transport_instance is None:
        _transport_instance = AIPTransport()
    return _transport_instance


def register_transport_adapter(adapter: TransportAdapter) -> None:
    """便捷函数：注册适配器到全局实例。"""
    get_aip_transport().register_adapter(adapter)
