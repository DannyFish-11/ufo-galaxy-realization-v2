"""
WebSocket 服务端传输层

负责:
1. 管理 WebSocket 连接
2. 消息的收发
3. 连接状态管理
4. 心跳检测

Normalization boundary (PR-5)
------------------------------
All accepted messages are normalized to a
:class:`~galaxy_gateway.protocol.normalized_ingress_event.NormalizedIngressEvent`
via :func:`~galaxy_gateway.protocol.normalized_ingress_event.to_normalized_ingress_event`
before entering runtime dispatch.  Internal dispatch branches on
``event.kind`` (an :class:`~galaxy_gateway.protocol.normalized_ingress_event.IngressEventKind`
constant) rather than raw type strings.
"""

import asyncio
import json
import logging
from typing import Dict, Optional, Callable, Set
from datetime import datetime, timedelta, timezone

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict

from ..protocol import AIPMessage, MessageType, create_error_message
from ..protocol.compat import parse_message_compat
from ..protocol.normalized_ingress_event import (
    IngressEventKind,
    NormalizedIngressEvent,
    to_normalized_ingress_event,
)

logger = logging.getLogger(__name__)


class DeviceConnection(BaseModel):
    """设备连接信息"""
    device_id: str
    websocket: WebSocket
    connected_at: datetime
    last_heartbeat: datetime
    is_active: bool = True
    
    model_config = ConfigDict(arbitrary_types_allowed=True)


class WebSocketManager:
    """WebSocket 连接管理器"""
    
    def __init__(
        self,
        heartbeat_interval: int = 30,
        heartbeat_timeout: int = 90,
        on_message: Optional[Callable[[str, AIPMessage], None]] = None,
        on_connect: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[str], None]] = None
    ):
        self.connections: Dict[str, DeviceConnection] = {}
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_backoff: Dict[str, float] = {}  # M5 fixed: exponential backoff tracker
        self._backoff_base = 1.0
        self._backoff_max = 60.0
        
    async def start(self):
        """启动管理器"""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_checker())
        logger.info("WebSocket Manager started")
        
    async def stop(self):
        """停止管理器"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # 关闭所有连接
        for device_id in list(self.connections.keys()):
            await self.disconnect(device_id)
        
        logger.info("WebSocket Manager stopped")
    
    async def connect(self, websocket: WebSocket, device_id: str) -> bool:
        """接受新连接"""
        # M5 fixed: check exponential backoff for reconnecting clients
        now = datetime.now(timezone.utc).timestamp()
        backoff_until = self._reconnect_backoff.get(device_id, 0)
        if now < backoff_until:
            wait = backoff_until - now
            logger.warning("Device %s reconnect too fast, backoff %.1fs", device_id, wait)
            await asyncio.sleep(wait)
        try:
            await websocket.accept()
            
            now = datetime.now(timezone.utc)
            self.connections[device_id] = DeviceConnection(
                device_id=device_id,
                connected_at=now,
                last_heartbeat=now
            )
            _websocket_sockets[device_id] = websocket  # M4 fixed: store WebSocket separately
            
            logger.info(f"Device connected: {device_id}")
            
            if self.on_connect:
                await self._safe_callback(self.on_connect, device_id)
            
            return True
        except Exception as e:
            logger.error(f"Failed to accept connection for {device_id}: {e}")
            return False
    
    async def disconnect(self, device_id: str):
        """断开连接"""
        # M5 fixed: set exponential backoff before removing connection
        prev_backoff = self._reconnect_backoff.get(device_id, 0)
        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts - prev_backoff < 120:  # double backoff if disconnect within 2min
            self._reconnect_backoff[device_id] = now_ts + min(
                self._backoff_max, self._backoff_base * 2 ** len([k for k, v in self._reconnect_backoff.items() if v > now_ts])
            )
        else:
            self._reconnect_backoff[device_id] = now_ts + self._backoff_base
        if device_id in self.connections:
            conn = self.connections[device_id]
            conn.is_active = False
            
            try:
                await conn.websocket.close()
            except Exception:
                pass
            
            del self.connections[device_id]
            _websocket_sockets.pop(device_id, None)  # M4 fixed: clean up separate WebSocket store
            logger.info("Device disconnected: %s", device_id)
            
            if self.on_disconnect:
                await self._safe_callback(self.on_disconnect, device_id)
    
    async def send_message(self, device_id: str, message: AIPMessage) -> bool:
        """发送消息到指定设备"""
        if device_id not in self.connections:
            logger.warning(f"Device not connected: {device_id}")
            return False
        
        conn = self.connections[device_id]
        if not conn.is_active:
            logger.warning(f"Device connection inactive: {device_id}")
            return False
        
        try:
            data = message.model_dump_json()
            await conn.websocket.send_text(data)
            logger.debug(f"Sent message to {device_id}: {message.type}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {device_id}: {e}")
            await self.disconnect(device_id)
            return False
    
    async def broadcast(self, message: AIPMessage, exclude: Optional[Set[str]] = None):
        """广播消息到所有设备"""
        exclude = exclude or set()
        tasks = []
        
        for device_id in self.connections:
            if device_id not in exclude:
                tasks.append(self.send_message(device_id, message))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def handle_connection(self, websocket: WebSocket, device_id: str):
        """处理设备连接的完整生命周期"""
        if not await self.connect(websocket, device_id):
            # M5 fixed: set exponential backoff on connection failure to prevent tight retry loops
            now_ts = datetime.now(timezone.utc).timestamp()
            prev_failures = len([k for k, v in self._reconnect_backoff.items() if v > now_ts])
            delay = min(self._backoff_max, self._backoff_base * (2 ** prev_failures))
            self._reconnect_backoff[device_id] = now_ts + delay
            logger.warning("Connection failed for %s, backoff %.1fs", device_id, delay)
            await asyncio.sleep(delay)
            return
        
        try:
            while True:
                data = await websocket.receive_text()
                await self._handle_message(device_id, data)
        except WebSocketDisconnect:
            logger.info(f"Device {device_id} disconnected normally")
        except Exception as e:
            logger.error(f"Error handling connection for {device_id}: {e}")
        finally:
            await self.disconnect(device_id)
    
    async def _handle_message(self, device_id: str, data: str):
        """处理接收到的消息（PR-5 normalization boundary）。

        All raw ingress is normalized to a :class:`NormalizedIngressEvent`
        before dispatch.  ``event.kind`` drives the routing decision; legacy
        raw type strings are only consulted for the mesh pre-dispatch fast-path
        (mesh types are outside the AIP v3 MessageType vocabulary).
        """
        try:
            # Pre-dispatch: handle P2P mesh messages before AIP parsing
            # (mesh types may not exist in v3 MessageType enum)
            raw = json.loads(data)
            msg_type = raw.get("type", "")

            if msg_type in ("peer_announce", "peer_exchange", "mesh_topology"):
                await self._handle_mesh_message(device_id, msg_type, raw)
                return

            # Normalize to NormalizedIngressEvent (compat path: v1/v2 → v3)
            event: NormalizedIngressEvent = to_normalized_ingress_event(data)

            # 更新心跳时间
            if device_id in self.connections:
                self.connections[device_id].last_heartbeat = datetime.now(timezone.utc)

            # Dispatch based on canonical event.kind
            if event.kind == IngressEventKind.DEVICE_HEARTBEAT:
                # Reconstruct minimal AIPMessage for legacy heartbeat handler
                message = parse_message_compat(data)
                await self._handle_heartbeat(device_id, message)
                return

            # Reconstruct AIPMessage for the legacy on_message callback
            message = parse_message_compat(data)

            # 调用外部消息处理器
            if self.on_message:
                await self._safe_callback(self.on_message, device_id, message)

        except Exception as e:
            logger.error(f"Failed to handle message from {device_id}: {e}")
            error_msg = create_error_message(device_id, str(e))
            await self.send_message(device_id, error_msg)

    async def _handle_mesh_message(self, device_id: str, msg_type: str, raw: dict):
        """Handle P2P mesh overlay messages (peer_announce / peer_exchange / mesh_topology)"""
        try:
            from core.mesh_coordinator import get_mesh_coordinator
            mesh = get_mesh_coordinator()

            if msg_type == "peer_announce":
                # PR-28: Extract tailscale_ip if present in announce
                payload = raw.get("payload") or {}
                ts_ip = payload.get("tailscale_ip") or raw.get("tailscale_ip", "")
                if ts_ip:
                    raw["tailscale_ip"] = ts_ip
                peer = mesh.handle_peer_announce(device_id, raw)
                peer_list = mesh.build_peer_exchange(exclude_device=device_id)
                response = {
                    "type": "peer_exchange",
                    "peers": peer_list,
                    "your_peer": peer.to_dict() if hasattr(peer, "to_dict") else str(peer),
                }
            elif msg_type == "peer_exchange":
                peer_list = mesh.build_peer_exchange(exclude_device=device_id)
                response = {"type": "peer_exchange", "peers": peer_list}
            elif msg_type == "mesh_topology":
                topology = mesh.get_topology()
                response = {"type": "mesh_topology", "topology": topology}
            else:
                response = {"type": "error", "error": f"Unknown mesh type: {msg_type}"}

            # Send raw JSON (not AIPMessage) since mesh types are v2 extended
            websocket = _websocket_sockets.get(device_id)
            if websocket is not None:
                await websocket.send_text(json.dumps(response))
        except ImportError:
            logger.debug("mesh_coordinator not available, ignoring mesh message")
        except Exception as e:
            logger.error(f"Failed to handle mesh message from {device_id}: {e}")

    async def _handle_heartbeat(self, device_id: str, message: AIPMessage):
        """处理心跳消息"""
        ack = AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT_ACK,
            device_id=device_id,
            correlation_id=message.message_id
        )
        await self.send_message(device_id, ack)
    
    async def _heartbeat_checker(self):
        """心跳检测任务"""
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                now = datetime.now(timezone.utc)
                timeout_threshold = now - timedelta(seconds=self.heartbeat_timeout)
                
                for device_id in list(self.connections.keys()):
                    conn = self.connections.get(device_id)
                    if conn and conn.last_heartbeat < timeout_threshold:
                        logger.warning(f"Device {device_id} heartbeat timeout")
                        await self.disconnect(device_id)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat checker error: {e}")
    
    async def _safe_callback(self, callback: Callable, *args):
        """安全调用回调函数"""
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Callback error: {e}")
    
    def get_connected_devices(self) -> list:
        """获取所有已连接设备"""
        return list(self.connections.keys())
    
    def is_device_connected(self, device_id: str) -> bool:
        """检查设备是否已连接"""
        return device_id in self.connections and self.connections[device_id].is_active
    
    def get_device_count(self) -> int:
        """获取已连接设备数量"""
        return len(self.connections)
