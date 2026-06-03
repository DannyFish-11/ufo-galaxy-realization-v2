"""
core/adapters/udp_adapter.py — UDP 传输适配器

基于 UDP 的无连接传输。
适用场景: 设备发现广播、心跳探测、低延迟消息、局域网广播。

特性:
- 无连接，低延迟
- 支持单播和广播
- 自动重传（可选）
- 消息大小限制 65KB（UDP 报文上限）
"""

import asyncio
import json
import logging
import socket
import struct
from typing import Any, Dict, List, Optional, Tuple

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.UDP")

# Galaxy UDP 配置
DEFAULT_PORT = 19422
BROADCAST_ADDR = "<broadcast>"
MAX_UDP_SIZE = 65507  # UDP 最大 payload
MAGIC_HEADER = b"GA3\x00"  # Galaxy AIP v3 魔数头


class UDPAdapter(TransportAdapter):
    """UDP 传输适配器。

    通过 UDP socket 发送/接收 AIP v3 消息。
    适用于: 设备发现、心跳、广播通知、低延迟场景。
    不适用于: 大消息传输、可靠传输场景（用 TCP/WS）。
    """

    @property
    def transport_type(self) -> str:
        return "udp"

    def __init__(self, local_port: int = DEFAULT_PORT) -> None:
        self._local_port = local_port
        self._socket: Optional[socket.socket] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional[asyncio.DatagramProtocol] = None
        self._peers: Dict[str, Tuple[str, int]] = {}  # device_id → (host, port)
        self._running = False

    # -- TransportAdapter 接口 ---------------------------------------------

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """发送 UDP 消息到目标。

        target 格式:
        - device_id: 从 _peers 查找 (host, port)
        - "host:port": 直接解析地址
        """
        if self._socket is None:
            return {"success": False, "error": "UDP socket not started"}

        # 解析目标地址
        addr = self._resolve_target(target)
        if addr is None:
            return {"success": False, "error": f"UDP target '{target}' not resolvable"}

        host, port = addr

        try:
            payload = json.dumps(message, ensure_ascii=False).encode("utf-8")

            if len(payload) > MAX_UDP_SIZE:
                return {"success": False, "error": f"UDP payload too large: {len(payload)} > {MAX_UDP_SIZE}"}

            # [MAGIC(4B) + length(4B) + payload]
            packet = MAGIC_HEADER + struct.pack(">I", len(payload)) + payload

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._socket.sendto, packet, (host, port)
            )

            return {"success": True, "via": "udp", "bytes": len(payload), "to": f"{host}:{port}"}

        except Exception as e:
            logger.warning("UDP send to '%s:%d' failed: %s", host, port, e)
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        """UDP 始终可用（无连接）。

        如果能解析目标地址，认为可用。
        """
        return self._resolve_target(target) is not None

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """UDP 广播到局域网所有设备。"""
        if self._socket is None:
            return {"success": False, "error": "UDP socket not started"}

        try:
            payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
            packet = MAGIC_HEADER + struct.pack(">I", len(payload)) + payload

            # 广播
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._socket.sendto, packet, (BROADCAST_ADDR, self._local_port)
            )

            # 也发送给所有已知 peer
            results = {"broadcast": True}
            for device_id, (host, port) in self._peers.items():
                try:
                    await loop.run_in_executor(
                        None, self._socket.sendto, packet, (host, port)
                    )
                    results[device_id] = True
                except Exception:
                    results[device_id] = False

            return {"success": True, "via": "udp", "results": results}

        except Exception as e:
            logger.warning("UDP broadcast failed: %s", e)
            return {"success": False, "error": str(e)}

    async def close(self) -> None:
        self._running = False
        if self._transport:
            self._transport.close()
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        self._peers.clear()

    # -- 服务启动 ----------------------------------------------------------

    async def start(self) -> None:
        """启动 UDP 监听。"""
        self._running = True

        # 创建 socket
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("0.0.0.0", self._local_port))
        self._socket.setblocking(False)

        # 启动 asyncio datagram endpoint
        loop = asyncio.get_event_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(self._on_receive),
            sock=self._socket,
        )

        logger.info("UDP adapter listening on port %d", self._local_port)

    def _on_receive(self, data: bytes, addr: Tuple[str, int]) -> None:
        """处理接收到的 UDP 消息。"""
        try:
            # 检查魔数头
            if not data.startswith(MAGIC_HEADER):
                return  # 非 Galaxy 消息，忽略

            # 解析长度 + payload
            payload_len = struct.unpack(">I", data[4:8])[0]
            payload = data[8:8 + payload_len]
            message = json.loads(payload.decode("utf-8"))

            device_id = message.get("device_id", "")
            if device_id:
                # 更新 peer 地址
                self._peers[device_id] = addr

            logger.debug("UDP RX from %s:%d: %s", addr[0], addr[1], message.get("type", "unknown"))
            # TODO: 分发到消息处理器

        except Exception as e:
            logger.debug("UDP RX parse error from %s:%d: %s", addr[0], addr[1], e)

    # -- Peer 注册 ---------------------------------------------------------

    def register_peer(self, device_id: str, host: str, port: Optional[int] = None) -> None:
        """注册已知 peer 的地址。"""
        self._peers[device_id] = (host, port or self._local_port)

    def unregister_peer(self, device_id: str) -> None:
        self._peers.pop(device_id, None)

    # -- 内部 --------------------------------------------------------------

    def _resolve_target(self, target: str) -> Optional[Tuple[str, int]]:
        """解析目标地址。"""
        # 1. 从 peer 表查找
        if target in self._peers:
            return self._peers[target]

        # 2. 解析 host:port 格式
        if ":" in target:
            parts = target.rsplit(":", 1)
            try:
                return (parts[0], int(parts[1]))
            except ValueError:
                pass

        return None


class UDPProtocol(asyncio.DatagramProtocol):
    """asyncio DatagramProtocol 实现。"""

    def __init__(self, on_data: Any):
        self._on_data = on_data

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        self._on_data(data, addr)
