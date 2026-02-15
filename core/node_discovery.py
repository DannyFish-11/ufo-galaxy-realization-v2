"""
节点发现服务 (Node Discovery)
==============================

提供动态节点发现和注册，补充现有的静态 node_registry.py：
- UDP 广播发现：自动发现局域网内的节点
- 节点注册表：动态注册和注销
- 心跳保活：检测节点存活状态
- 节点下线处理：优雅退出 + 故障检测
"""

import asyncio
import json
import logging
import time
import socket
import struct
from typing import Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("UFO-Galaxy.NodeDiscovery")

DISCOVERY_PORT = 19720
DISCOVERY_MAGIC = b"UFOGLXY"  # 7 bytes 魔数
HEARTBEAT_INTERVAL = 10       # 秒
NODE_TIMEOUT = 35             # 3 次心跳未收到即认为下线


# ───────────────────── 数据模型 ─────────────────────

class NodeRole(Enum):
    MASTER = "master"
    WORKER = "worker"
    GATEWAY = "gateway"
    DEVICE = "device"


class DiscoveryState(Enum):
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    HEALTHY = "healthy"
    SUSPECT = "suspect"      # 心跳超时但未确认下线
    OFFLINE = "offline"
    DEREGISTERED = "deregistered"


@dataclass
class DiscoveredNode:
    """已发现的节点"""
    node_id: str
    host: str
    port: int
    role: NodeRole = NodeRole.WORKER
    capabilities: List[str] = field(default_factory=list)
    state: DiscoveryState = DiscoveryState.DISCOVERED
    metadata: Dict = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    version: str = ""

    def is_alive(self) -> bool:
        return (time.time() - self.last_heartbeat) < NODE_TIMEOUT

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "role": self.role.value,
            "capabilities": self.capabilities,
            "state": self.state.value,
            "last_heartbeat": self.last_heartbeat,
            "version": self.version,
        }


# ───────────────────── 协议消息 ─────────────────────

class MessageType(Enum):
    ANNOUNCE = 0x01      # 节点宣告自己的存在
    HEARTBEAT = 0x02     # 心跳
    QUERY = 0x03         # 查询在线节点
    RESPONSE = 0x04      # 查询响应
    DEREGISTER = 0x05    # 节点主动下线


def encode_message(msg_type: MessageType, payload: Dict) -> bytes:
    """编码发现消息"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return DISCOVERY_MAGIC + struct.pack("!BH", msg_type.value, len(body)) + body


def decode_message(data: bytes) -> Optional[tuple]:
    """解码发现消息，返回 (MessageType, payload_dict) 或 None"""
    if len(data) < 10 or data[:7] != DISCOVERY_MAGIC:
        return None
    msg_type_val, body_len = struct.unpack("!BH", data[7:10])
    try:
        msg_type = MessageType(msg_type_val)
    except ValueError:
        return None
    body = data[10:10 + body_len]
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return msg_type, payload


# ───────────────────── 节点发现服务 ─────────────────────

class NodeDiscoveryService:
    """
    节点发现服务

    功能：
    1. 广播宣告：新节点启动时通过 UDP 广播宣告自己
    2. 广播监听：持续监听发现新节点
    3. 心跳维护：定期发送/检查心跳
    4. 状态管理：维护所有已知节点的状态
    """

    def __init__(self, node_id: str, host: str = "0.0.0.0", port: int = 0,
                 role: NodeRole = NodeRole.WORKER,
                 capabilities: Optional[List[str]] = None,
                 discovery_port: int = DISCOVERY_PORT):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.role = role
        self.capabilities = capabilities or []
        self.discovery_port = discovery_port

        # 节点注册表
        self.nodes: Dict[str, DiscoveredNode] = {}

        # 回调
        self._on_node_joined: List[Callable] = []
        self._on_node_left: List[Callable] = []
        self._on_node_updated: List[Callable] = []

        # 运行时
        self._transport = None
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def on_node_joined(self, callback: Callable):
        """注册节点加入回调"""
        self._on_node_joined.append(callback)

    def on_node_left(self, callback: Callable):
        """注册节点离开回调"""
        self._on_node_left.append(callback)

    def on_node_updated(self, callback: Callable):
        """注册节点更新回调"""
        self._on_node_updated.append(callback)

    async def start(self):
        """启动发现服务"""
        self._running = True

        # 启动 UDP 监听
        loop = asyncio.get_event_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _DiscoveryProtocol(self),
                local_addr=("0.0.0.0", self.discovery_port),
                family=socket.AF_INET,
                allow_broadcast=True,
            )
            logger.info(f"节点发现服务已启动: {self.node_id} (UDP:{self.discovery_port})")
        except OSError as e:
            logger.warning(f"UDP 绑定失败 (端口 {self.discovery_port}): {e}，使用纯注册模式")
            self._transport = None

        # 宣告自己
        await self._announce()

        # 启动心跳和检查任务
        self._tasks.append(asyncio.ensure_future(self._heartbeat_loop()))
        self._tasks.append(asyncio.ensure_future(self._health_check_loop()))

    async def stop(self):
        """停止发现服务"""
        self._running = False

        # 发送下线通知
        await self._deregister()

        # 停止所有任务
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        if self._transport:
            self._transport.close()

        logger.info(f"节点发现服务已停止: {self.node_id}")

    # ─── 手动注册 ───

    def register_node(self, node: DiscoveredNode):
        """手动注册节点（用于已知节点或配置的节点）"""
        is_new = node.node_id not in self.nodes
        node.state = DiscoveryState.REGISTERED
        self.nodes[node.node_id] = node

        if is_new:
            logger.info(f"节点已注册: {node.node_id} ({node.host}:{node.port})")
            for cb in self._on_node_joined:
                _safe_call(cb, node)

    def deregister_node(self, node_id: str):
        """注销节点"""
        node = self.nodes.get(node_id)
        if node:
            node.state = DiscoveryState.DEREGISTERED
            logger.info(f"节点已注销: {node_id}")
            for cb in self._on_node_left:
                _safe_call(cb, node)
            del self.nodes[node_id]

    # ─── 查询 ───

    def get_healthy_nodes(self) -> List[DiscoveredNode]:
        return [n for n in self.nodes.values()
                if n.state in (DiscoveryState.HEALTHY, DiscoveryState.REGISTERED)
                and n.is_alive()]

    def get_nodes_by_capability(self, capability: str) -> List[DiscoveredNode]:
        return [n for n in self.get_healthy_nodes()
                if capability in n.capabilities]

    def get_nodes_by_role(self, role: NodeRole) -> List[DiscoveredNode]:
        return [n for n in self.get_healthy_nodes()
                if n.role == role]

    # ─── 广播和心跳 ───

    async def _announce(self):
        """广播宣告"""
        payload = {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "role": self.role.value,
            "capabilities": self.capabilities,
            "version": "1.0",
        }
        self._broadcast(MessageType.ANNOUNCE, payload)

    async def _deregister(self):
        """广播下线"""
        self._broadcast(MessageType.DEREGISTER, {"node_id": self.node_id})

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                self._broadcast(MessageType.HEARTBEAT, {
                    "node_id": self.node_id,
                    "timestamp": time.time(),
                })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"心跳错误: {e}")

    async def _health_check_loop(self):
        """定期检查节点健康状态"""
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                now = time.time()

                for node in list(self.nodes.values()):
                    if node.node_id == self.node_id:
                        continue

                    elapsed = now - node.last_heartbeat
                    old_state = node.state

                    if elapsed > NODE_TIMEOUT:
                        if node.state != DiscoveryState.OFFLINE:
                            node.state = DiscoveryState.OFFLINE
                            logger.warning(f"节点离线: {node.node_id} (超时 {elapsed:.0f}s)")
                            for cb in self._on_node_left:
                                _safe_call(cb, node)
                    elif elapsed > HEARTBEAT_INTERVAL * 2:
                        if node.state != DiscoveryState.SUSPECT:
                            node.state = DiscoveryState.SUSPECT
                            logger.info(f"节点可疑: {node.node_id} (心跳延迟 {elapsed:.0f}s)")
                    else:
                        if node.state not in (DiscoveryState.HEALTHY, DiscoveryState.REGISTERED):
                            node.state = DiscoveryState.HEALTHY

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查错误: {e}")

    def _broadcast(self, msg_type: MessageType, payload: Dict):
        """UDP 广播"""
        if not self._transport:
            return
        data = encode_message(msg_type, payload)
        try:
            self._transport.sendto(data, ("<broadcast>", self.discovery_port))
        except Exception as e:
            logger.debug(f"广播失败: {e}")

    def handle_message(self, msg_type: MessageType, payload: Dict, addr: tuple):
        """处理收到的发现消息"""
        sender_id = payload.get("node_id", "")
        if sender_id == self.node_id:
            return  # 忽略自己

        if msg_type == MessageType.ANNOUNCE:
            self._handle_announce(payload, addr)
        elif msg_type == MessageType.HEARTBEAT:
            self._handle_heartbeat(payload)
        elif msg_type == MessageType.DEREGISTER:
            self._handle_deregister(payload)
        elif msg_type == MessageType.QUERY:
            self._handle_query(addr)

    def _handle_announce(self, payload: Dict, addr: tuple):
        node_id = payload["node_id"]
        is_new = node_id not in self.nodes

        try:
            role = NodeRole(payload.get("role", "worker"))
        except ValueError:
            role = NodeRole.WORKER

        node = DiscoveredNode(
            node_id=node_id,
            host=payload.get("host", addr[0]),
            port=payload.get("port", 0),
            role=role,
            capabilities=payload.get("capabilities", []),
            state=DiscoveryState.HEALTHY,
            version=payload.get("version", ""),
            last_heartbeat=time.time(),
        )
        self.nodes[node_id] = node

        if is_new:
            logger.info(f"发现新节点: {node_id} ({node.host}:{node.port})")
            for cb in self._on_node_joined:
                _safe_call(cb, node)

    def _handle_heartbeat(self, payload: Dict):
        node_id = payload.get("node_id", "")
        node = self.nodes.get(node_id)
        if node:
            was_offline = node.state in (DiscoveryState.OFFLINE, DiscoveryState.SUSPECT)
            node.last_heartbeat = time.time()
            node.state = DiscoveryState.HEALTHY

            if was_offline:
                logger.info(f"节点恢复: {node_id}")
                for cb in self._on_node_joined:
                    _safe_call(cb, node)

    def _handle_deregister(self, payload: Dict):
        node_id = payload.get("node_id", "")
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.state = DiscoveryState.DEREGISTERED
            logger.info(f"节点主动下线: {node_id}")
            for cb in self._on_node_left:
                _safe_call(cb, node)
            del self.nodes[node_id]

    def _handle_query(self, addr: tuple):
        """响应查询：发送自己的信息"""
        payload = {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "role": self.role.value,
            "capabilities": self.capabilities,
        }
        if self._transport:
            data = encode_message(MessageType.RESPONSE, payload)
            self._transport.sendto(data, addr)

    def get_status(self) -> Dict:
        by_state = {}
        for n in self.nodes.values():
            by_state[n.state.value] = by_state.get(n.state.value, 0) + 1
        return {
            "node_id": self.node_id,
            "total_nodes": len(self.nodes),
            "healthy_nodes": len(self.get_healthy_nodes()),
            "by_state": by_state,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }


# ───────────────────── UDP 协议处理 ─────────────────────

class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """asyncio UDP 协议"""

    def __init__(self, service: NodeDiscoveryService):
        self.service = service

    def datagram_received(self, data: bytes, addr: tuple):
        result = decode_message(data)
        if result:
            msg_type, payload = result
            self.service.handle_message(msg_type, payload, addr)

    def error_received(self, exc):
        logger.debug(f"UDP 错误: {exc}")


def _safe_call(callback, *args):
    try:
        callback(*args)
    except Exception as e:
        logger.warning(f"回调异常: {e}")


# ───────────────────── 单例 ─────────────────────

_discovery_instance: Optional[NodeDiscoveryService] = None


def get_node_discovery(node_id: str = "master",
                       **kwargs) -> NodeDiscoveryService:
    global _discovery_instance
    if _discovery_instance is None:
        _discovery_instance = NodeDiscoveryService(node_id=node_id, **kwargs)
    return _discovery_instance
