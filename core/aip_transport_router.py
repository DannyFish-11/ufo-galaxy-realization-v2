"""
core/aip_transport_router.py — AIP v3 统一传输路由器
=====================================================

PR-TRANSPORT-UNIFIED: 将 Mesh / NATS / WebSocket 拧成一股绳的
传输抽象层。被 CommandRouter 调用，替代硬编码的 WS 路由。

职责：
1. 根据源/目标设备的能力选择最优传输通道
2. Mesh P2P 优先（同LAN直连）
3. NATS 次之（异步可靠投递）
4. WebSocket 兜底（所有设备都支持）

与现有组件的关系：
    CommandRouter.route_envelope()
        └─ AIPTransportRouter.route() ← 这里
            ├─ MeshCoordinator.send()  → P2P / Relay / WS
            ├─ NATS Bus pub            → JetStream
            └─ WebSocketManager.send   → WS fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable

logger = logging.getLogger("Galaxy.AIPTransportRouter")


# ---------------------------------------------------------------------------
# Transport enum — 与 AIP v3 device_register.transport 字段对齐
# ---------------------------------------------------------------------------


class TransportType(str, Enum):
    """支持的传输协议类型"""

    MESH_P2P = "mesh_p2p"       # LAN TCP 直连
    MESH_RELAY = "mesh_relay"   # 服务端中继
    NATS = "nats"               # NATS JetStream
    WEBSOCKET = "websocket"     # WebSocket (兜底)
    MQTT = "mqtt"               # MQTT (未来)
    BLE = "ble"                 # Bluetooth LE (未来)


# 优先级：越低数字越高优先级
_TRANSPORT_PRIORITY: List[TransportType] = [
    TransportType.MESH_P2P,     # 0 — 最快，同LAN直连
    TransportType.MESH_RELAY,   # 1 — 次快，服务端中继
    TransportType.NATS,         # 2 — 可靠，异步投递
    TransportType.WEBSOCKET,    # 3 — 兜底，所有设备支持
]


# ---------------------------------------------------------------------------
# AIPTransportRouter
# ---------------------------------------------------------------------------


class AIPTransportRouter:
    """AIP v3 统一传输路由器。

    将 Mesh / NATS / WebSocket 统一为一个 send() 入口，
    根据设备注册时的 transport 能力和实时可达性自动选路。
    """

    def __init__(
        self,
        mesh_sender: Optional[Callable[..., Awaitable[Any]]] = None,
        nats_publisher: Optional[Callable[..., Awaitable[Any]]] = None,
        ws_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    ) -> None:
        self._mesh_send = mesh_sender
        self._nats_pub = nats_publisher
        self._ws_send = ws_sender
        self._udm: Optional[Any] = None
        self._mesh: Optional[Any] = None
        self._nats: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lazy getters (避免循环导入)
    # ------------------------------------------------------------------

    def _get_udm(self) -> Any:
        if self._udm is None:
            try:
                from core.unified.device_manager import UnifiedDeviceManager
                self._udm = UnifiedDeviceManager()
            except Exception as exc:
                logger.debug("UDM not available: %s", exc)
        return self._udm

    def _get_mesh(self) -> Any:
        if self._mesh is None:
            try:
                from core.mesh_coordinator import get_mesh_coordinator
                self._mesh = get_mesh_coordinator()
            except Exception as exc:
                logger.debug("MeshCoordinator not available: %s", exc)
        return self._mesh

    def _get_nats(self) -> Any:
        if self._nats is None:
            try:
                from core.nats_bus import nats_bus
                self._nats = nats_bus
            except Exception as exc:
                logger.debug("NATS bus not available: %s", exc)
        return self._nats

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(
        self,
        envelope: Dict[str, Any],
        source_device: str,
        target_device: str,
    ) -> Dict[str, Any]:
        """路由 AIP v3 消息到目标设备。

        选路逻辑：
        1. 查询 UDM 获取目标设备的 supported_transports
        2. 按优先级排序 (MESH_P2P > MESH_RELAY > NATS > WS)
        3. 逐一尝试，直到成功

        Args:
            envelope: AIP v3 消息信封
            source_device: 源设备 ID
            target_device: 目标设备 ID

        Returns:
            {"success": bool, "via": str, ...}
        """
        # 1. 获取目标设备支持的传输方式
        supported = await self._get_supported_transports(target_device)
        if not supported:
            supported = [TransportType.WEBSOCKET]  # 默认兜底

        # 2. 按优先级排序
        ordered = [t for t in _TRANSPORT_PRIORITY if t in supported]

        # 3. 逐一尝试
        for transport in ordered:
            try:
                if transport == TransportType.MESH_P2P:
                    result = await self._try_mesh_p2p(source_device, target_device, envelope)
                    if result:
                        return {"success": True, "via": "mesh_p2p", **result}

                elif transport == TransportType.MESH_RELAY:
                    result = await self._try_mesh_relay(source_device, target_device, envelope)
                    if result:
                        return {"success": True, "via": "mesh_relay", **result}

                elif transport == TransportType.NATS:
                    result = await self._try_nats(source_device, target_device, envelope)
                    if result:
                        return {"success": True, "via": "nats", **result}

                elif transport == TransportType.WEBSOCKET:
                    result = await self._try_ws(source_device, target_device, envelope)
                    if result:
                        return {"success": True, "via": "websocket", **result}

            except Exception as exc:
                logger.debug("Transport %s failed: %s", transport.value, exc)
                continue

        # 全部失败
        return {
            "success": False,
            "error": "ALL_TRANSPORTS_FAILED",
            "target_device": target_device,
            "attempted": [t.value for t in ordered],
        }

    # ------------------------------------------------------------------
    # Transport-specific send
    # ------------------------------------------------------------------

    async def _try_mesh_p2p(
        self, source: str, target: str, envelope: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """尝试 Mesh P2P 直连"""
        mesh = self._get_mesh()
        if mesh is None:
            return None

        # 检查 peer 是否可达
        peer = mesh.get_peer(target)
        if not peer or not peer.reachable_direct:
            return None

        # P2P 发送
        data = json.dumps(envelope).encode("utf-8")
        result = await mesh.send(
            target_device=target,
            payload=envelope,
            payload_type="task",
            source_device=source,
        )
        if result and getattr(result, "success", False):
            return {"latency_ms": getattr(result, "latency_ms", 0)}
        return None

    async def _try_mesh_relay(
        self, source: str, target: str, envelope: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """尝试 Mesh Relay 中继"""
        mesh = self._get_mesh()
        if mesh is None:
            return None

        result = await mesh.send(
            target_device=target,
            payload=envelope,
            payload_type="task",
            source_device=source,
        )
        if result and getattr(result, "success", False):
            via = getattr(result, "via", None)
            if via and via.value == "relay":
                return {"latency_ms": getattr(result, "latency_ms", 0)}
        return None

    async def _try_nats(
        self, source: str, target: str, envelope: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """尝试 NATS JetStream 投递"""
        nats = self._get_nats()
        if nats is None or not nats.is_connected():
            return None

        try:
            topic = f"galaxy.tasks.dispatch.{target}"
            await nats._publish(topic, envelope)
            return {}
        except Exception:
            return None

    async def _try_ws(
        self, source: str, target: str, envelope: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """尝试 WebSocket 发送（兜底）"""
        if self._ws_send is None:
            return None

        try:
            await self._ws_send(target, envelope)
            return {}
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_supported_transports(self, device_id: str) -> List[TransportType]:
        """从 UDM 查询设备支持的传输方式"""
        udm = self._get_udm()
        if udm is None:
            return []

        try:
            device = udm.get_device(device_id)
            if device is None:
                return []

            # 从 metadata.supported_transports 解析
            raw = device.metadata.get("supported_transports", [])
            result: List[TransportType] = []
            for t in raw:
                try:
                    result.append(TransportType(t))
                except ValueError:
                    pass
            return result
        except Exception as exc:
            logger.debug("Failed to get transports for %s: %s", device_id, exc)
            return []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_router_instance: Optional[AIPTransportRouter] = None


def get_transport_router(
    mesh_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    nats_publisher: Optional[Callable[..., Awaitable[Any]]] = None,
    ws_sender: Optional[Callable[..., Awaitable[Any]]] = None,
) -> AIPTransportRouter:
    """获取或创建 AIPTransportRouter 单例。"""
    global _router_instance
    if _router_instance is None:
        _router_instance = AIPTransportRouter(
            mesh_sender=mesh_sender,
            nats_publisher=nats_publisher,
            ws_sender=ws_sender,
        )
    return _router_instance


def inject_transport_senders(
    mesh_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    nats_publisher: Optional[Callable[..., Awaitable[Any]]] = None,
    ws_sender: Optional[Callable[..., Awaitable[Any]]] = None,
) -> None:
    """注入发送器到现有路由器实例。"""
    global _router_instance
    if _router_instance is None:
        get_transport_router(mesh_sender, nats_publisher, ws_sender)
    else:
        if mesh_sender is not None:
            _router_instance._mesh_send = mesh_sender
        if nats_publisher is not None:
            _router_instance._nats_pub = nats_publisher
        if ws_sender is not None:
            _router_instance._ws_send = ws_sender
    logger.info(
        "AIPTransportRouter senders injected | mesh=%s nats=%s ws=%s",
        mesh_sender is not None,
        nats_publisher is not None,
        ws_sender is not None,
    )
