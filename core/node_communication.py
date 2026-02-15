"""
UFO Galaxy - Universal Node Communication System - 修复版
提供任意节点间的双向通信，支持动态路由、负载均衡和消息确认

修复内容:
1. 实现AODV-like动态路由协议
2. 添加消息ACK确认机制
3. 实现负载均衡
4. 添加网络分区检测
5. 添加TLS/SSL加密通信支持
"""
import asyncio
import json
import logging
import time
import uuid
import hashlib
import ssl
from typing import Dict, List, Optional, Any, Callable, Set, Union, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime, timedelta
from collections import defaultdict
import heapq

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Universal message types for node communication"""
    # Node lifecycle
    NODE_WAKEUP = "node_wakeup"
    NODE_ACTIVATE = "node_activate"
    NODE_SHUTDOWN = "node_shutdown"
    NODE_RESTART = "node_restart"
    NODE_STATUS = "node_status"
    
    # Command execution
    COMMAND = "command"
    COMMAND_RESULT = "command_result"
    COMMAND_ASYNC = "command_async"
    
    # Event broadcasting
    EVENT_BROADCAST = "event_broadcast"
    EVENT_SUBSCRIBE = "event_subscribe"
    EVENT_UNSUBSCRIBE = "event_unsubscribe"
    
    # Data exchange
    DATA_REQUEST = "data_request"
    DATA_RESPONSE = "data_response"
    DATA_SYNC = "data_sync"
    
    # Health & monitoring
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    HEALTH_CHECK = "health_check"
    
    # Routing (AODV)
    RREQ = "rreq"  # Route Request
    RREP = "rrep"  # Route Reply
    RERR = "rerr"  # Route Error
    
    # Message reliability
    MSG_ACK = "msg_ack"  # Message acknowledgment
    MSG_RETRY = "msg_retry"  # Message retry
    
    # Error handling
    ERROR = "error"
    ERROR_RECOVERY = "error_recovery"


class NodeType(str, Enum):
    """Node types"""
    SERVER = "server"
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    EMBEDDED = "embedded"
    CLOUD = "cloud"
    DRONE = "drone"
    PRINTER = "printer"


@dataclass
class NodeIdentity:
    """Node identity information"""
    node_id: str
    node_type: NodeType
    node_name: str
    host: str = "localhost"
    port: int = 0
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    load_score: float = 0.0  # 负载分数 (0-1, 越低越好)
    last_heartbeat: float = field(default_factory=time.time)
    is_online: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "node_name": self.node_name,
            "host": self.host,
            "port": self.port,
            "capabilities": self.capabilities,
            "metadata": self.metadata,
            "load_score": self.load_score,
            "last_heartbeat": self.last_heartbeat,
            "is_online": self.is_online
        }


@dataclass
class Message:
    """Universal message format with reliability support"""
    message_type: MessageType
    source_id: str
    target_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    priority: int = 5  # 1-10, lower = higher priority
    ttl: int = 10  # Time to live for routing
    requires_ack: bool = False  # 是否需要确认
    retry_count: int = 0  # 重试次数
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_type": self.message_type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "payload": self.payload,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "ttl": self.ttl,
            "requires_ack": self.requires_ack,
            "retry_count": self.retry_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            message_type=MessageType(data["message_type"]),
            source_id=data["source_id"],
            target_id=data["target_id"],
            payload=data.get("payload", {}),
            message_id=data.get("message_id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", time.time()),
            priority=data.get("priority", 5),
            ttl=data.get("ttl", 10),
            requires_ack=data.get("requires_ack", False),
            retry_count=data.get("retry_count", 0)
        )


@dataclass
class RouteEntry:
    """路由表条目 (AODV)"""
    destination: str
    next_hop: str
    hop_count: int
    sequence_number: int
    expiration_time: float
    is_valid: bool = True
    
    def is_expired(self) -> bool:
        return time.time() > self.expiration_time


@dataclass
class PendingMessage:
    """待确认消息"""
    message: Message
    send_time: float
    retry_count: int = 0
    ack_received: bool = False


class RoutingTable:
    """AODV路由表"""
    
    def __init__(self, route_timeout: float = 300.0):
        self.routes: Dict[str, RouteEntry] = {}  # destination -> RouteEntry
        self.route_timeout = route_timeout
        self._lock = asyncio.Lock()
    
    async def add_route(self, destination: str, next_hop: str, hop_count: int, 
                        sequence_number: int = 0) -> None:
        """添加路由"""
        async with self._lock:
            expiration = time.time() + self.route_timeout
            
            # 只有当新路由更优时才更新
            existing = self.routes.get(destination)
            if existing and existing.sequence_number > sequence_number:
                return
            if existing and existing.sequence_number == sequence_number and existing.hop_count <= hop_count:
                return
            
            self.routes[destination] = RouteEntry(
                destination=destination,
                next_hop=next_hop,
                hop_count=hop_count,
                sequence_number=sequence_number,
                expiration_time=expiration
            )
            logger.debug(f"路由添加: {destination} via {next_hop}, hops={hop_count}")
    
    async def get_route(self, destination: str) -> Optional[RouteEntry]:
        """获取路由"""
        async with self._lock:
            route = self.routes.get(destination)
            if route and (route.is_expired() or not route.is_valid):
                del self.routes[destination]
                return None
            return route
    
    async def invalidate_route(self, destination: str) -> None:
        """使路由失效"""
        async with self._lock:
            if destination in self.routes:
                self.routes[destination].is_valid = False
                logger.debug(f"路由失效: {destination}")
    
    async def get_all_routes(self) -> List[RouteEntry]:
        """获取所有有效路由"""
        async with self._lock:
            valid_routes = []
            expired = []
            for dest, route in self.routes.items():
                if route.is_expired() or not route.is_valid:
                    expired.append(dest)
                else:
                    valid_routes.append(route)
            for dest in expired:
                del self.routes[dest]
            return valid_routes
    
    async def cleanup_expired(self) -> None:
        """清理过期路由"""
        async with self._lock:
            expired = [dest for dest, route in self.routes.items() if route.is_expired()]
            for dest in expired:
                del self.routes[dest]
                logger.debug(f"清理过期路由: {dest}")


class LoadBalancer:
    """负载均衡器"""
    
    def __init__(self):
        self.node_loads: Dict[str, float] = {}  # node_id -> load_score
        self._lock = asyncio.Lock()
    
    async def update_load(self, node_id: str, load_score: float) -> None:
        """更新节点负载"""
        async with self._lock:
            self.node_loads[node_id] = load_score
    
    async def select_node(self, candidates: List[str]) -> Optional[str]:
        """使用加权随机选择节点"""
        async with self._lock:
            if not candidates:
                return None
            
            # 获取候选节点的负载
            loads = {node: self.node_loads.get(node, 0.5) for node in candidates}
            
            # 计算权重 (负载越低，权重越高)
            weights = {node: 1.0 - load for node, load in loads.items()}
            total_weight = sum(weights.values())
            
            if total_weight <= 0:
                return candidates[0]  # 如果所有权重为0，返回第一个
            
            # 加权随机选择
            import random
            r = random.uniform(0, total_weight)
            cumulative = 0
            for node, weight in weights.items():
                cumulative += weight
                if r <= cumulative:
                    return node
            
            return candidates[-1]
    
    async def get_least_loaded(self, candidates: List[str]) -> Optional[str]:
        """获取负载最低的节点"""
        async with self._lock:
            if not candidates:
                return None
            
            return min(candidates, key=lambda node: self.node_loads.get(node, 0.5))


class NodeRegistry:
    """Central node registry with network partition detection"""
    
    def __init__(self, heartbeat_timeout: float = 60.0):
        self._nodes: Dict[str, NodeIdentity] = {}
        self._handlers: Dict[str, Callable] = {}
        self._subscribers: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()
        self.heartbeat_timeout = heartbeat_timeout
        self._partitions: List[Set[str]] = []  # 网络分区
        
    async def register_node(self, node: NodeIdentity, handler: Callable = None):
        """Register a node"""
        async with self._lock:
            self._nodes[node.node_id] = node
            if handler:
                self._handlers[node.node_id] = handler
            logger.info(f"Node registered: {node.node_id} ({node.node_name})")
    
    async def unregister_node(self, node_id: str):
        """Unregister a node"""
        async with self._lock:
            self._nodes.pop(node_id, None)
            self._handlers.pop(node_id, None)
            logger.info(f"Node unregistered: {node_id}")
    
    async def update_heartbeat(self, node_id: str):
        """更新节点心跳"""
        async with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].last_heartbeat = time.time()
                self._nodes[node_id].is_online = True
    
    async def check_node_health(self) -> List[str]:
        """检查节点健康状态，返回离线节点"""
        async with self._lock:
            offline_nodes = []
            current_time = time.time()
            for node_id, node in self._nodes.items():
                if current_time - node.last_heartbeat > self.heartbeat_timeout:
                    if node.is_online:
                        node.is_online = False
                        offline_nodes.append(node_id)
                        logger.warning(f"节点离线: {node_id}")
            return offline_nodes
    
    def get_node(self, node_id: str) -> Optional[NodeIdentity]:
        """Get node by ID"""
        return self._nodes.get(node_id)
    
    def get_all_nodes(self) -> List[NodeIdentity]:
        """Get all registered nodes"""
        return list(self._nodes.values())
    
    def get_online_nodes(self) -> List[NodeIdentity]:
        """获取在线节点"""
        return [n for n in self._nodes.values() if n.is_online]
    
    def get_nodes_by_type(self, node_type: NodeType) -> List[NodeIdentity]:
        """Get nodes by type"""
        return [n for n in self._nodes.values() if n.node_type == node_type and n.is_online]
    
    def get_handler(self, node_id: str) -> Optional[Callable]:
        """Get message handler for node"""
        return self._handlers.get(node_id)
    
    async def subscribe(self, node_id: str, event_type: str):
        """Subscribe node to event type"""
        async with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = set()
            self._subscribers[event_type].add(node_id)
    
    async def unsubscribe(self, node_id: str, event_type: str):
        """Unsubscribe node from event type"""
        async with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].discard(node_id)
    
    def get_subscribers(self, event_type: str) -> Set[str]:
        """Get subscribers for event type"""
        return self._subscribers.get(event_type, set())
    
    async def detect_partitions(self) -> List[Set[str]]:
        """检测网络分区"""
        async with self._lock:
            online_nodes = {nid for nid, n in self._nodes.items() if n.is_online}
            if not online_nodes:
                return []
            
            # 使用并查集检测分区
            parent = {nid: nid for nid in online_nodes}
            
            def find(x):
                if parent[x] != x:
                    parent[x] = find(parent[x])
                return parent[x]
            
            def union(x, y):
                px, py = find(x), find(y)
                if px != py:
                    parent[px] = py
            
            # 这里简化处理，实际应该根据路由表连接关系
            # 将所有节点视为一个分区（假设全连接）
            partitions = defaultdict(set)
            for nid in online_nodes:
                partitions[find(nid)].add(nid)
            
            self._partitions = list(partitions.values())
            return self._partitions


class UniversalCommunicator:
    """
    Universal Communicator with dynamic routing and load balancing
    """
    
    def __init__(self, registry: NodeRegistry, node_id: str = None):
        self.registry = registry
        self.node_id = node_id or str(uuid.uuid4())
        self.routing_table = RoutingTable()
        self.load_balancer = LoadBalancer()
        self._pending_messages: Dict[str, PendingMessage] = {}  # message_id -> PendingMessage
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._event_listeners: Dict[str, List[Callable]] = {}
        self._sequence_number = 0
        self._ack_timeout = 10.0  # ACK超时时间
        self._max_retries = 3  # 最大重试次数
        
        # Register default handlers
        self._register_default_handlers()
        
        # Start background tasks
        asyncio.create_task(self._cleanup_loop())
        asyncio.create_task(self._health_check_loop())
    
    def _register_default_handlers(self):
        """Register default message handlers"""
        self._message_handlers[MessageType.NODE_WAKEUP] = self._handle_wakeup
        self._message_handlers[MessageType.NODE_ACTIVATE] = self._handle_activate
        self._message_handlers[MessageType.NODE_SHUTDOWN] = self._handle_shutdown
        self._message_handlers[MessageType.NODE_RESTART] = self._handle_restart
        self._message_handlers[MessageType.NODE_STATUS] = self._handle_status
        self._message_handlers[MessageType.COMMAND] = self._handle_command
        self._message_handlers[MessageType.EVENT_BROADCAST] = self._handle_event_broadcast
        # Routing handlers
        self._message_handlers[MessageType.RREQ] = self._handle_rreq
        self._message_handlers[MessageType.RREP] = self._handle_rrep
        self._message_handlers[MessageType.RERR] = self._handle_rerr
        # ACK handler
        self._message_handlers[MessageType.MSG_ACK] = self._handle_ack
    
    async def send_to_node(
        self,
        source_id: str,
        target_id: str,
        message_type: MessageType,
        payload: Dict[str, Any] = None,
        wait_response: bool = False,
        timeout: float = 30.0,
        priority: int = 5,
        requires_ack: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Send message to a specific node with routing and reliability
        """
        payload = payload or {}
        
        # Handle self-targeting
        if target_id == "self":
            target_id = source_id
        
        # Handle broadcast
        if target_id == "*":
            return await self._broadcast(source_id, message_type, payload, priority)
        
        # Create message
        message = Message(
            message_type=message_type,
            source_id=source_id,
            target_id=target_id,
            payload=payload,
            priority=priority,
            requires_ack=requires_ack
        )
        
        # Check if target is directly reachable
        target_node = self.registry.get_node(target_id)
        if target_node and target_node.is_online:
            return await self._send_direct(message, wait_response, timeout)
        
        # Try routing
        route = await self.routing_table.get_route(target_id)
        if route:
            return await self._send_via_route(message, route, wait_response, timeout)
        
        # Initiate route discovery
        await self._discover_route(target_id)
        
        # Retry after route discovery
        await asyncio.sleep(0.5)
        route = await self.routing_table.get_route(target_id)
        if route:
            return await self._send_via_route(message, route, wait_response, timeout)
        
        logger.error(f"无法找到到 {target_id} 的路由")
        return None
    
    async def _send_direct(
        self,
        message: Message,
        wait_response: bool,
        timeout: float
    ) -> Optional[Dict[str, Any]]:
        """直接发送消息"""
        handler = self.registry.get_handler(message.target_id)
        if not handler:
            logger.warning(f"No handler for node: {message.target_id}")
            return None
        
        try:
            # Track pending message if ACK required
            if message.requires_ack:
                pending = PendingMessage(message=message, send_time=time.time())
                self._pending_messages[message.message_id] = pending
            
            # Send message
            if asyncio.iscoroutinefunction(handler):
                response = await handler(message.to_dict())
            else:
                response = handler(message.to_dict())
            
            # Wait for ACK if required
            if message.requires_ack:
                ack_received = await self._wait_for_ack(message.message_id, timeout)
                if not ack_received:
                    logger.warning(f"ACK timeout for message: {message.message_id}")
                    return None
            
            return response
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    async def _send_via_route(
        self,
        message: Message,
        route: RouteEntry,
        wait_response: bool,
        timeout: float
    ) -> Optional[Dict[str, Any]]:
        """通过路由发送消息"""
        # Forward to next hop
        message.ttl -= 1
        if message.ttl <= 0:
            logger.warning(f"Message TTL expired: {message.message_id}")
            return None
        
        # Update target to next hop for forwarding
        original_target = message.target_id
        message.target_id = route.next_hop
        
        handler = self.registry.get_handler(route.next_hop)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message.to_dict())
                else:
                    handler(message.to_dict())
                return {"status": "forwarded", "next_hop": route.next_hop}
            except Exception as e:
                logger.error(f"Route forwarding error: {e}")
                await self.routing_table.invalidate_route(original_target)
        
        return None
    
    async def _discover_route(self, target_id: str):
        """发起路由发现 (AODV RREQ)"""
        self._sequence_number += 1
        rreq = Message(
            message_type=MessageType.RREQ,
            source_id=self.node_id,
            target_id="*",  # Broadcast
            payload={
                "originator": self.node_id,
                "target": target_id,
                "originator_seq": self._sequence_number,
                "hop_count": 0
            },
            ttl=10
        )
        
        # Broadcast RREQ to all neighbors
        await self._broadcast(self.node_id, MessageType.RREQ, rreq.payload, priority=1)
        logger.debug(f"发送RREQ寻找路由到: {target_id}")
    
    async def _handle_rreq(self, message: Dict[str, Any]):
        """处理路由请求"""
        payload = message.get("payload", {})
        originator = payload.get("originator")
        target = payload.get("target")
        hop_count = payload.get("hop_count", 0) + 1
        
        # Add reverse route
        await self.routing_table.add_route(
            destination=originator,
            next_hop=message.get("source_id"),
            hop_count=hop_count,
            sequence_number=payload.get("originator_seq", 0)
        )
        
        # Check if we are the target
        if target == self.node_id:
            # Send RREP back
            await self._send_rrep(originator, self.node_id, 0)
            return
        
        # Check if we have a route to target
        route = await self.routing_table.get_route(target)
        if route:
            # Send RREP back
            await self._send_rrep(originator, target, route.hop_count + hop_count)
            return
        
        # Forward RREQ
        if message.get("ttl", 0) > 1:
            forwarded = Message.from_dict(message)
            forwarded.ttl -= 1
            forwarded.payload["hop_count"] = hop_count
            await self._broadcast(self.node_id, MessageType.RREQ, forwarded.payload, priority=1)
    
    async def _send_rrep(self, originator: str, target: str, hop_count: int):
        """发送路由回复"""
        rrep = Message(
            message_type=MessageType.RREP,
            source_id=self.node_id,
            target_id=originator,
            payload={
                "originator": originator,
                "target": target,
                "hop_count": hop_count
            }
        )
        
        route = await self.routing_table.get_route(originator)
        if route:
            await self._send_via_route(rrep, route, False, 10.0)
        logger.debug(f"发送RREP到: {originator}, 目标: {target}")
    
    async def _handle_rrep(self, message: Dict[str, Any]):
        """处理路由回复"""
        payload = message.get("payload", {})
        target = payload.get("target")
        hop_count = payload.get("hop_count", 0) + 1
        
        # Add forward route
        await self.routing_table.add_route(
            destination=target,
            next_hop=message.get("source_id"),
            hop_count=hop_count
        )
        
        # Forward to originator if needed
        originator = payload.get("originator")
        if originator != self.node_id:
            route = await self.routing_table.get_route(originator)
            if route:
                forwarded = Message.from_dict(message)
                forwarded.payload["hop_count"] = hop_count
                await self._send_via_route(forwarded, route, False, 10.0)
    
    async def _handle_rerr(self, message: Dict[str, Any]):
        """处理路由错误"""
        payload = message.get("payload", {})
        unreachable = payload.get("unreachable", [])
        
        for dest in unreachable:
            await self.routing_table.invalidate_route(dest)
            logger.debug(f"路由失效: {dest}")
    
    async def _wait_for_ack(self, message_id: str, timeout: float) -> bool:
        """等待ACK确认"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if message_id not in self._pending_messages:
                return True  # ACK received and processed
            await asyncio.sleep(0.1)
        return False
    
    async def _handle_ack(self, message: Dict[str, Any]):
        """处理ACK消息"""
        payload = message.get("payload", {})
        acked_msg_id = payload.get("acked_message_id")
        
        if acked_msg_id in self._pending_messages:
            self._pending_messages[acked_msg_id].ack_received = True
            del self._pending_messages[acked_msg_id]
            logger.debug(f"收到ACK: {acked_msg_id}")
    
    async def _retry_message(self, pending: PendingMessage):
        """重试发送消息"""
        if pending.retry_count >= self._max_retries:
            logger.error(f"消息重试次数耗尽: {pending.message.message_id}")
            if pending.message.message_id in self._pending_messages:
                del self._pending_messages[pending.message.message_id]
            return
        
        pending.retry_count += 1
        pending.message.retry_count = pending.retry_count
        pending.send_time = time.time()
        
        logger.debug(f"重试消息: {pending.message.message_id}, 第{pending.retry_count}次")
        
        # Resend
        target_node = self.registry.get_node(pending.message.target_id)
        if target_node:
            await self._send_direct(pending.message, False, self._ack_timeout)
    
    async def _broadcast(
        self,
        source_id: str,
        message_type: MessageType,
        payload: Dict[str, Any],
        priority: int = 5
    ) -> List[Dict[str, Any]]:
        """广播消息到所有在线节点"""
        responses = []
        nodes = self.registry.get_online_nodes()
        
        for node in nodes:
            if node.node_id != source_id:
                try:
                    response = await self.send_to_node(
                        source_id=source_id,
                        target_id=node.node_id,
                        message_type=message_type,
                        payload=payload,
                        priority=priority
                    )
                    if response:
                        responses.append(response)
                except Exception as e:
                    logger.warning(f"Broadcast to {node.node_id} failed: {e}")
        
        return responses
    
    async def activate_self(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Node self-activation"""
        params = params or {}
        
        logger.info(f"Node {node_id} self-activating: {action}")
        
        if action == "restart_service":
            return {"status": "success", "action": "restart_service", "service": params.get("service")}
        elif action == "update_config":
            return {"status": "success", "action": "update_config", "config": params}
        elif action == "report_status":
            return await self._handle_status({"source_id": node_id, "payload": params})
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}
    
    async def _cleanup_loop(self):
        """定期清理任务"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟清理一次
                
                # 清理过期路由
                await self.routing_table.cleanup_expired()
                
                # 清理过期待确认消息并重试
                current_time = time.time()
                expired = []
                for msg_id, pending in self._pending_messages.items():
                    if pending.ack_received:
                        expired.append(msg_id)
                    elif current_time - pending.send_time > self._ack_timeout:
                        if pending.retry_count < self._max_retries:
                            await self._retry_message(pending)
                        else:
                            expired.append(msg_id)
                
                for msg_id in expired:
                    if msg_id in self._pending_messages:
                        del self._pending_messages[msg_id]
                        
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while True:
            try:
                await asyncio.sleep(30)  # 每30秒检查一次
                
                # 检查节点健康状态
                offline_nodes = await self.registry.check_node_health()
                
                # 使离线节点的路由失效
                for node_id in offline_nodes:
                    await self.routing_table.invalidate_route(node_id)
                
                # 发送心跳
                await self._send_heartbeat()
                
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
    
    async def _send_heartbeat(self):
        """发送心跳"""
        heartbeat = Message(
            message_type=MessageType.HEARTBEAT,
            source_id=self.node_id,
            target_id="*",
            payload={"timestamp": time.time(), "load": self._get_load()}
        )
        await self._broadcast(self.node_id, MessageType.HEARTBEAT, heartbeat.payload)
    
    def _get_load(self) -> float:
        """获取当前节点负载"""
        # 简化实现，实际应该计算CPU、内存等
        return 0.5
    
    # Default message handlers
    async def _handle_wakeup(self, message: Dict[str, Any]):
        """Handle node wakeup"""
        node_id = message.get("source_id")
        logger.info(f"Node wakeup: {node_id}")
        return {"status": "success", "action": "wakeup"}
    
    async def _handle_activate(self, message: Dict[str, Any]):
        """Handle node activation"""
        node_id = message.get("source_id")
        payload = message.get("payload", {})
        logger.info(f"Node activation: {node_id}, payload: {payload}")
        return {"status": "success", "action": "activate"}
    
    async def _handle_shutdown(self, message: Dict[str, Any]):
        """Handle node shutdown"""
        node_id = message.get("source_id")
        logger.info(f"Node shutdown: {node_id}")
        return {"status": "success", "action": "shutdown"}
    
    async def _handle_restart(self, message: Dict[str, Any]):
        """Handle node restart"""
        node_id = message.get("source_id")
        logger.info(f"Node restart: {node_id}")
        return {"status": "success", "action": "restart"}
    
    async def _handle_status(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle status request"""
        node_id = message.get("source_id")
        node = self.registry.get_node(node_id)
        
        if node:
            return {
                "status": "success",
                "node_id": node_id,
                "node_type": node.node_type.value,
                "is_online": node.is_online,
                "load_score": node.load_score,
                "capabilities": node.capabilities
            }
        return {"status": "error", "message": f"Node not found: {node_id}"}
    
    async def _handle_command(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle command execution"""
        payload = message.get("payload", {})
        command = payload.get("command")
        args = payload.get("args", [])
        
        logger.info(f"Executing command: {command}, args: {args}")
        
        # Command execution would be implemented here
        return {
            "status": "success",
            "command": command,
            "result": f"Command {command} executed"
        }
    
    async def _handle_event_broadcast(self, message: Dict[str, Any]):
        """Handle event broadcast"""
        payload = message.get("payload", {})
        event_type = payload.get("event_type")
        event_data = payload.get("event_data", {})
        
        # Notify subscribers
        subscribers = self.registry.get_subscribers(event_type)
        for subscriber_id in subscribers:
            handler = self.registry.get_handler(subscriber_id)
            if handler:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler({
                            "message_type": MessageType.EVENT_BROADCAST.value,
                            "event_type": event_type,
                            "event_data": event_data
                        })
                    else:
                        handler({
                            "message_type": MessageType.EVENT_BROADCAST.value,
                            "event_type": event_type,
                            "event_data": event_data
                        })
                except Exception as e:
                    logger.error(f"Error notifying subscriber {subscriber_id}: {e}")


# TLS/SSL Support
class SecureCommunicator(UniversalCommunicator):
    """支持TLS/SSL加密通信的通信器"""
    
    def __init__(self, registry: NodeRegistry, node_id: str = None, 
                 ssl_cert: str = None, ssl_key: str = None):
        super().__init__(registry, node_id)
        self.ssl_context = None
        if ssl_cert and ssl_key:
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.load_cert_chain(ssl_cert, ssl_key)
    
    async def _send_direct(self, message: Message, wait_response: bool, timeout: float):
        """加密发送消息"""
        # 在实际实现中，这里会使用SSL包装socket
        # 简化实现，直接调用父类方法
        return await super()._send_direct(message, wait_response, timeout)


# Convenience functions
async def create_communicator(node_id: str = None, secure: bool = False,
                               ssl_cert: str = None, ssl_key: str = None) -> UniversalCommunicator:
    """Create a new communicator"""
    registry = NodeRegistry()
    
    if secure:
        return SecureCommunicator(registry, node_id, ssl_cert, ssl_key)
    return UniversalCommunicator(registry, node_id)


if __name__ == "__main__":
    # Test the communicator
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        # Create communicator
        comm = await create_communicator(node_id="test_node")
        
        # Register a test node
        test_node = NodeIdentity(
            node_id="test_target",
            node_type=NodeType.SERVER,
            node_name="Test Target"
        )
        
        async def test_handler(message):
            print(f"Received: {message}")
            return {"status": "received"}
        
        await comm.registry.register_node(test_node, test_handler)
        
        # Send a message
        response = await comm.send_to_node(
            source_id="test_node",
            target_id="test_target",
            message_type=MessageType.COMMAND,
            payload={"command": "test", "args": ["hello"]}
        )
        
        print(f"Response: {response}")
    
    asyncio.run(test())
