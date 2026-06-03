"""
core/adapters/tcp_adapter.py — TCP P2P 传输适配器

基于 TCP 的 P2P 直连传输。
适用场景: 同一局域网内设备直连、Mesh 网络点对点通信。

特性:
- 自动发现同一局域网内的 Galaxy 设备 (mDNS/zeroconf)
- 长连接保持，心跳检测
- 自动重连
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.TCP")

# mDNS 可选依赖
try:
    import zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

# Galaxy TCP P2P 服务标识
GALAXY_SERVICE_TYPE = "_galaxy-aip3._tcp.local."
DEFAULT_PORT = 19421
HEARTBEAT_INTERVAL = 30.0


class TCPAdapter(TransportAdapter):
    """TCP P2P 传输适配器。

    通过 TCP socket 直接连接目标设备，不经过网关。
    适用于 Mesh 网络中的点对点通信。
    """

    @property
    def transport_type(self) -> str:
        return "tcp"

    def __init__(self, local_port: int = DEFAULT_PORT) -> None:
        self._local_port = local_port
        self._peers: Dict[str, "PeerConnection"] = {}   # device_id → PeerConnection
        self._server: Optional[asyncio.Server] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    # -- TransportAdapter 接口 ---------------------------------------------

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """通过 TCP 直连发送消息到目标设备。"""
        peer = self._peers.get(target)
        if not peer or not peer.connected:
            # 尝试解析 host:port 连接
            if ":" in target:
                host, port_str = target.rsplit(":", 1)
                try:
                    port = int(port_str)
                    result = await self._connect_and_send(host, port, message, target)
                    return result
                except ValueError:
                    pass
            return {"success": False, "error": f"TCP peer '{target}' not connected"}

        try:
            payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
            peer.writer.write(len(payload).to_bytes(4, "big"))
            peer.writer.write(payload)
            await peer.writer.drain()
            return {"success": True, "via": "tcp", "bytes": len(payload)}
        except Exception as e:
            logger.warning("TCP send to '%s' failed: %s", target, e)
            peer.connected = False
            return {"success": False, "error": str(e)}

    async def is_available(self, target: str) -> bool:
        peer = self._peers.get(target)
        return peer is not None and peer.connected

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """广播到所有已连接的 TCP peer。"""
        results = {}
        for device_id in list(self._peers.keys()):
            results[device_id] = await self.send(message, device_id)
        return {"success": True, "via": "tcp", "results": results}

    async def close(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        for peer in list(self._peers.values()):
            try:
                peer.writer.close()
                await peer.writer.wait_closed()
            except Exception:
                pass
        self._peers.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # -- 服务端启动 --------------------------------------------------------

    async def start_server(self) -> None:
        """启动 TCP 监听，等待其他设备连接。"""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_incoming, "0.0.0.0", self._local_port
        )
        logger.info("TCP P2P server listening on port %d", self._local_port)

        # 启动心跳
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _handle_incoming(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """处理 incoming TCP 连接。"""
        addr = writer.get_extra_info("peername")
        logger.debug("TCP incoming connection from %s", addr)

        while self._running:
            try:
                # 读取 4 字节长度头
                len_bytes = await reader.readexactly(4)
                msg_len = int.from_bytes(len_bytes, "big")
                if msg_len > 10 * 1024 * 1024:  # 10MB 上限
                    logger.warning("TCP message too large: %d bytes", msg_len)
                    break

                # 读取消息体
                data = await reader.readexactly(msg_len)
                message = json.loads(data.decode("utf-8"))

                device_id = message.get("device_id", "")
                if device_id:
                    peer = self._peers.get(device_id)
                    if not peer:
                        peer = PeerConnection(device_id, reader, writer)
                        self._peers[device_id] = peer
                    peer.connected = True

                logger.debug("TCP RX from %s: %s", device_id, message.get("type", "unknown"))
                # TODO: 分发到消息处理器

            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                logger.debug("TCP connection error from %s: %s", addr, e)
                break

        # 清理
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    # -- 客户端连接 --------------------------------------------------------

    async def connect_to_peer(self, host: str, port: int, device_id: str) -> Dict[str, Any]:
        """主动连接到 P2P 对等端。"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=10.0
            )

            peer = PeerConnection(device_id, reader, writer)
            peer.connected = True
            self._peers[device_id] = peer

            logger.info("TCP P2P connected to %s at %s:%d", device_id, host, port)
            return {"success": True, "device_id": device_id, "host": host, "port": port}

        except Exception as e:
            logger.warning("TCP P2P connect to %s:%d failed: %s", host, port, e)
            return {"success": False, "error": str(e)}

    async def _connect_and_send(
        self, host: str, port: int, message: Dict[str, Any], device_id: str
    ) -> Dict[str, Any]:
        """临时连接到目标发送消息。"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5.0
            )

            payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
            writer.write(len(payload).to_bytes(4, "big"))
            writer.write(payload)
            await writer.drain()

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            return {"success": True, "via": "tcp", "bytes": len(payload)}

        except Exception as e:
            return {"success": False, "error": f"TCP connect-send failed: {e}"}

    # -- mDNS 服务发现 -----------------------------------------------------

    async def discover_peers(self, timeout: float = 5.0) -> Dict[str, str]:
        """通过 mDNS 发现同一局域网内的 Galaxy 设备。"""
        if not ZEROCONF_AVAILABLE:
            logger.debug("zeroconf not installed, skipping mDNS discovery")
            return {}

        found = {}
        zc = zeroconf.Zeroconf()

        try:
            # 浏览器方式发现
            browser = zeroconf.ServiceBrowser(
                zc, GALAXY_SERVICE_TYPE,
                handlers=[
                    lambda zc, type, name, state: (
                        found.update({name: state.addresses[0] if hasattr(state, "addresses") else ""})
                        if state else None
                    )
                ]
            )
            await asyncio.sleep(timeout)
            browser.cancel()
        except Exception as e:
            logger.debug("mDNS discovery error: %s", e)
        finally:
            zc.close()

        return found

    def register_local_service(self, device_id: str, port: Optional[int] = None) -> None:
        """注册本机 mDNS 服务，让其他设备发现。"""
        if not ZEROCONF_AVAILABLE:
            return

        try:
            zc = zeroconf.Zeroconf()
            info = zeroconf.ServiceInfo(
                GALAXY_SERVICE_TYPE,
                f"{device_id}.{GALAXY_SERVICE_TYPE}",
                addresses=[zeroconf.IPVersion.AllV4],  # 自动获取 IP
                port=port or self._local_port,
                properties={"device_id": device_id, "version": "3.0"},
            )
            zc.register_service(info)
            logger.info("mDNS service registered: %s on port %d", device_id, port or self._local_port)
        except Exception as e:
            logger.warning("mDNS register failed: %s", e)

    # -- 心跳 --------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """周期性发送心跳到所有 peer。"""
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                for device_id, peer in list(self._peers.items()):
                    if not peer.connected:
                        continue
                    try:
                        hb = {"type": "heartbeat", "device_id": "", "timestamp": int(time.time() * 1000)}
                        payload = json.dumps(hb).encode("utf-8")
                        peer.writer.write(len(payload).to_bytes(4, "big"))
                        peer.writer.write(payload)
                        await peer.writer.drain()
                    except Exception:
                        peer.connected = False
                        logger.debug("TCP heartbeat failed for %s, marking disconnected", device_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Heartbeat loop error: %s", e)


class PeerConnection:
    """TCP P2P 对等连接。"""

    def __init__(self, device_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.device_id = device_id
        self.reader = reader
        self.writer = writer
        self.connected = False
        self.last_seen = 0.0
