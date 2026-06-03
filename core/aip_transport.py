"""
core/aip_transport.py — AIP v3 统一传输层
==========================================

所有消息（Mesh协同、NATS任务、设备控制）统一通过此类发送。
适配你的真实 AIP v3 协议 (core/schemas/aip_v3.py)。

对齐点:
- AIPMessage 基类无 transport/source/target 字段
- 用 device_id 标识设备
- aip_version 标记协议版本
- transport 字段在发送时由 AIPTransport 自动注入

支持的传输适配器:
- tailscale_p2p: Tailscale WireGuard P2P（同 tailnet 设备优先，~5ms）
- websocket: WebSocket 点对点（全局兜底路径）
- mqtt: MQTT 发布/订阅
- tcp: TCP 直连（P2P）
- udp: UDP 报文
- ble: Bluetooth LE
- serial: 串口通信

架构:
    Mesh/NATS/App ──► AIPTransport.send()
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              适配器注册表    自动选择/默认fallback
                    │
            transport → adapter
                    │
            ┌───┬───┼───┬───┬───┐
            ▼   ▼   ▼   ▼   ▼   ▼
           WS MQTT TCP UDP BLE SERIAL
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AIPTransport")


class TransportAdapter(ABC):
    """传输适配器抽象基类。所有传输协议必须实现此接口。"""

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """传输类型: websocket, mqtt, tcp, udp, ble, serial"""

    @abstractmethod
    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """发送 AIP v3 消息。返回 {"success": bool, "via": str, ...}"""

    @abstractmethod
    async def is_available(self, target: str) -> bool:
        """目标是否可通过此传输到达。"""

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """广播消息（可选实现，默认逐个发送给已知目标）。"""
        return {"success": True, "via": self.transport_type, "broadcast": "not_implemented"}

    async def close(self) -> None:
        """清理资源。"""
        pass


class AIPTransport:
    """AIP v3 统一传输管理器。

    设计原则:
    1. 与 core.schemas.aip_v3 协议对齐 — AIPMessage 无 transport 字段，发送时注入
    2. 自动传输选择 — 根据目标设备可用性和网络状况自动选择最优传输
    3. Mesh/NATS 保持独立 — 不并入 transport，但可通过 AIPTransport 发送消息
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, TransportAdapter] = {}
        self._default_transport: str = "websocket"
        # 传输优先级（用于自动选择）
        # PR-28: tailscale_p2p 排在首位 — 同 tailnet 设备直接走 WireGuard
        self._transport_priority = [
            "tailscale_p2p",   # Tailscale WireGuard P2P（最低延迟）
            "tcp",              # LAN TCP 直连
            "websocket",        # WebSocket 兜底
            "mqtt",             # MQTT 广播/订阅
            "udp",              # UDP 报文
            "ble",              # 蓝牙 LE
            "serial",           # 串口
        ]

    # -- 注册管理 ----------------------------------------------------------

    def register_adapter(self, adapter: TransportAdapter) -> None:
        self._adapters[adapter.transport_type] = adapter
        logger.info("Transport adapter registered: %s", adapter.transport_type)

    def unregister_adapter(self, transport_type: str) -> None:
        adapter = self._adapters.pop(transport_type, None)
        if adapter:
            logger.info("Transport adapter unregistered: %s", transport_type)

    def get_adapter(self, transport_type: str) -> Optional[TransportAdapter]:
        return self._adapters.get(transport_type)

    def list_adapters(self) -> List[str]:
        return list(self._adapters.keys())

    # -- 核心发送接口 ------------------------------------------------------

    async def send(
        self,
        message: Any,
        target: str,
        transport: Optional[str] = None,
    ) -> Dict[str, Any]:
        """统一发送入口。

        Args:
            message: AIP v3 消息 — AIPMessage 对象或 dict
            target: 目标 device_id
            transport: 强制指定传输类型（None=自动选择）

        自动处理:
        - 将 AIPMessage 转 dict
        - 自动注入 transport 字段（对齐 AIP v3 协议）
        - transport=None 时按优先级自动选择可用传输
        """
        # 1. 统一转 dict
        msg_dict = self._to_dict(message)

        # 2. 确定传输类型
        ttype = transport or msg_dict.get("_transport", self._default_transport)
        msg_dict["_transport"] = ttype  # 内部标记（不出现在 AIP v3 协议中）

        # 3. 自动选择：如果指定传输不可用，按优先级 fallback
        adapter = await self._select_adapter(target, preferred=ttype)
        if adapter is None:
            return {
                "success": False,
                "error": f"No transport available for target '{target}'",
            }

        ttype = adapter.transport_type

        # 4. 发送 + PR-28 fallback 链：一个传输失败自动试下一个
        return await self._send_with_fallback(msg_dict, target, adapter, ttype)

    async def broadcast(
        self,
        message: Any,
        targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """广播消息到多个目标。

        遍历所有可用适配器发送，不依赖 NATS。
        如果提供 targets，逐个发送到目标设备。
        如果没有 targets，调用各适配器的 broadcast 方法。
        """
        msg_dict = self._to_dict(message)
        results = {}

        if targets:
            # 逐个发送到指定目标
            for target in targets:
                result = await self.send(msg_dict, target)
                results[target] = result
        else:
            # 调用每个适配器的广播
            for ttype, adapter in self._adapters.items():
                try:
                    result = await adapter.broadcast(msg_dict)
                    results[ttype] = result
                except Exception as e:
                    logger.warning("Broadcast via '%s' failed: %s", ttype, e)
                    results[ttype] = {"success": False, "error": str(e)}

        return {"success": True, "results": results}

    # -- 自动传输选择 ------------------------------------------------------

    async def probe_best_transport(self, target: str) -> Optional[str]:
        """探测到目标设备的最佳传输。

        按优先级顺序检查各传输的可用性，返回第一个可用的。
        """
        for ttype in self._transport_priority:
            adapter = self._adapters.get(ttype)
            if adapter and await adapter.is_available(target):
                return ttype
        return None

    async def _select_adapter(
        self,
        target: str,
        preferred: str,
    ) -> Optional[TransportAdapter]:
        """选择最佳适配器。

        1. "auto" 模式：按优先级自动探测
        2. 优先使用 caller 指定的传输
        3. 如果不可用，按优先级 fallback
        4. 如果都不通，返回默认传输适配器

        PR-28: 当 TailscaleP2PAdapter 注册且目标在同 tailnet 时，
        自动提升 tailscale_p2p 为首选，绕过 WebSocket 网关。
        """
        # PR-28: Tailscale 拓扑感知 — 同 tailnet 优先 P2P
        ts_adapter = self._adapters.get("tailscale_p2p")
        if ts_adapter is not None and await ts_adapter.is_available(target):
            # Target is on same tailnet — use P2P even if caller didn't ask
            if preferred not in ("tailscale_p2p", "auto"):
                logger.debug(
                    "Tailscale P2P available for '%s', overriding preferred '%s'",
                    target, preferred,
                )
            logger.debug("Auto-selected 'tailscale_p2p' for target '%s' (same tailnet)", target)
            return ts_adapter

        # 1. "auto" 模式：按优先级探测第一个可用的
        if preferred == "auto":
            for ttype in self._transport_priority:
                adapter = self._adapters.get(ttype)
                if adapter and await adapter.is_available(target):
                    logger.debug("Auto-selected '%s' for target '%s'", ttype, target)
                    return adapter
            # 没有可用的，fallback 到默认
            default = self._adapters.get(self._default_transport)
            if default:
                return default
            return None

        # 2. 尝试首选
        adapter = self._adapters.get(preferred)
        if adapter and await adapter.is_available(target):
            return adapter

        # 3. 按优先级 fallback
        for ttype in self._transport_priority:
            if ttype == preferred:
                continue  # 已试过
            adapter = self._adapters.get(ttype)
            if adapter and await adapter.is_available(target):
                logger.debug("Fallback: '%s' → '%s' for target '%s'", preferred, ttype, target)
                return adapter

        # 4. 最后尝试默认（不检查 is_available，尽最大努力）
        default = self._adapters.get(self._default_transport)
        if default:
            logger.debug("Force default '%s' for target '%s'", self._default_transport, target)
            return default

        return None

    # -- PR-28: Fallback chain -----------------------------------------------

    async def _send_with_fallback(
        self,
        msg_dict: Dict[str, Any],
        target: str,
        first_adapter: TransportAdapter,
        first_ttype: str,
    ) -> Dict[str, Any]:
        """Send with automatic fallback chain.

        If the first adapter fails, try the next one in priority order.
        Records all attempts for diagnostics.
        """
        attempted: List[str] = []
        errors: List[str] = []

        adapters_to_try = [first_adapter]
        # Add remaining adapters in priority order
        for ttype in self._transport_priority:
            adapter = self._adapters.get(ttype)
            if adapter and adapter not in adapters_to_try:
                adapters_to_try.append(adapter)

        for adapter in adapters_to_try:
            ttype = adapter.transport_type
            attempted.append(ttype)
            try:
                result = await adapter.send(msg_dict, target)
                result["_transport_used"] = ttype
                if result.get("success"):
                    if len(attempted) > 1:
                        logger.info(
                            "PR-28 fallback success: %s → %s for %s (tried: %s)",
                            first_ttype, ttype, target, attempted,
                        )
                    return result
                # Adapter returned success=False — record reason and try next
                errors.append(f"{ttype}: {result.get('error', 'unknown')}")
            except Exception as exc:
                errors.append(f"{ttype}: {exc}")
                continue

        # All failed
        logger.warning(
            "PR-28 all transports failed for %s: %s", target, errors,
        )
        return {
            "success": False,
            "error": f"All transports failed (tried: {attempted}): {' | '.join(errors)}",
            "_attempted": attempted,
        }

    # -- 内部工具 ----------------------------------------------------------

    def _to_dict(self, message: Any) -> Dict[str, Any]:
        """将各种消息格式统一转为 dict。

        支持: AIPMessage (Pydantic), dict, str (JSON)
        """
        if isinstance(message, dict):
            return dict(message)  # 复制避免修改原对象
        if hasattr(message, "model_dump"):
            # Pydantic v2
            return message.model_dump()
        if hasattr(message, "dict"):
            # Pydantic v1
            return message.dict()
        if isinstance(message, str):
            import json
            return json.loads(message)
        raise ValueError(f"Unsupported message type: {type(message)}")

    async def close_all(self) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.close()
            except Exception as e:
                logger.debug("Error closing adapter '%s': %s", adapter.transport_type, e)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_transport_instance: Optional[AIPTransport] = None


def get_aip_transport() -> AIPTransport:
    global _transport_instance
    if _transport_instance is None:
        _transport_instance = AIPTransport()
    return _transport_instance


def register_transport_adapter(adapter: TransportAdapter) -> None:
    get_aip_transport().register_adapter(adapter)
