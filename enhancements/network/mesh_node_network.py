"""
潮网式节点互联架构 (Mesh Node Network)
实现整个系统各节点（自身+其他节点）的网状互联
"""

import logging
import asyncio
import json
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """节点类型"""
    CORE = "core"  # 核心节点（L4 主循环）
    DEVICE = "device"  # 设备节点（无人机、3D 打印机等）
    SERVICE = "service"  # 服务节点（工具、API等）
    GATEWAY = "gateway"  # 网关节点
    AGENT = "agent"  # Agent 节点（Android、Windows等）


class NodeStatus(Enum):
    """节点状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"
    INITIALIZING = "initializing"


class MessageType(Enum):
    """消息类型"""
    COMMAND = "command"
    QUERY = "query"
    RESPONSE = "response"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    DISCOVERY = "discovery"


@dataclass
class NodeInfo:
    """节点信息"""
    id: str
    name: str
    type: NodeType
    status: NodeStatus
    capabilities: List[str]
    address: str  # 网络地址或路径
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_seen: str = ""
    connections: Set[str] = field(default_factory=set)  # 连接的节点 ID


@dataclass
class Message:
    """消息"""
    id: str
    type: MessageType
    source: str  # 源节点 ID
    target: str  # 目标节点 ID
    payload: Dict[str, Any]
    timestamp: str
    priority: int = 5  # 1-10, 10 最高


class MeshNodeNetwork:
    """潮网式节点网络"""
    
    def __init__(self, node_id: str, node_name: str, node_type: NodeType):
        """
        初始化潮网式节点网络
        
        Args:
            node_id: 节点 ID
            node_name: 节点名称
            node_type: 节点类型
        """
        self.node_id = node_id
        self.node_name = node_name
        self.node_type = node_type
        
        # 节点注册表
        self.nodes: Dict[str, NodeInfo] = {}
        
        # 消息队列
        self.message_queue: asyncio.Queue = asyncio.Queue()
        
        # 消息处理器
        self.message_handlers: Dict[MessageType, List[Callable]] = {
            msg_type: [] for msg_type in MessageType
        }
        
        # 路由表（节点 ID -> 下一跳节点 ID）
        self.routing_table: Dict[str, str] = {}
        
        # 消息历史
        self.message_history: List[Message] = []
        
        # 运行状态
        self.running = False
        
        # 注册自己
        self._register_self()
        
        logger.info(f"MeshNodeNetwork 初始化完成: {node_id} ({node_name})")
    
    def _register_self(self):
        """注册自己"""
        self_info = NodeInfo(
            id=self.node_id,
            name=self.node_name,
            type=self.node_type,
            status=NodeStatus.ONLINE,
            capabilities=[],
            address="local",
            last_seen=self._get_timestamp()
        )
        
        self.nodes[self.node_id] = self_info
    
    def register_node(
        self,
        node_id: str,
        name: str,
        node_type: NodeType,
        capabilities: List[str],
        address: str,
        metadata: Optional[Dict] = None
    ):
        """
        注册节点
        
        Args:
            node_id: 节点 ID
            name: 节点名称
            node_type: 节点类型
            capabilities: 节点能力
            address: 节点地址
            metadata: 元数据
        """
        node_info = NodeInfo(
            id=node_id,
            name=name,
            type=node_type,
            status=NodeStatus.INITIALIZING,
            capabilities=capabilities,
            address=address,
            metadata=metadata or {},
            last_seen=self._get_timestamp()
        )
        
        self.nodes[node_id] = node_info
        
        logger.info(f"注册节点: {node_id} ({name}), 类型: {node_type.value}")
        
        # 自动建立连接
        self._establish_connection(node_id)
    
    def _establish_connection(self, node_id: str):
        """建立连接"""
        if node_id == self.node_id:
            return
        
        # 添加到自己的连接列表
        self.nodes[self.node_id].connections.add(node_id)
        
        # 添加到对方的连接列表
        if node_id in self.nodes:
            self.nodes[node_id].connections.add(self.node_id)
        
        # 更新路由表（简化版本：直连）
        self.routing_table[node_id] = node_id
        
        logger.info(f"建立连接: {self.node_id} <-> {node_id}")
    
    def unregister_node(self, node_id: str):
        """注销节点"""
        if node_id in self.nodes:
            # 移除连接
            for other_node_id in self.nodes[node_id].connections:
                if other_node_id in self.nodes:
                    self.nodes[other_node_id].connections.discard(node_id)
            
            # 移除路由
            if node_id in self.routing_table:
                del self.routing_table[node_id]
            
            # 移除节点
            del self.nodes[node_id]
            
            logger.info(f"注销节点: {node_id}")
    
    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """获取节点信息"""
        return self.nodes.get(node_id)
    
    def get_nodes_by_type(self, node_type: NodeType) -> List[NodeInfo]:
        """按类型获取节点"""
        return [node for node in self.nodes.values() if node.type == node_type]
    
    def get_nodes_by_capability(self, capability: str) -> List[NodeInfo]:
        """按能力获取节点"""
        return [
            node for node in self.nodes.values()
            if capability in node.capabilities
        ]
    
    def update_node_status(self, node_id: str, status: NodeStatus):
        """更新节点状态"""
        if node_id in self.nodes:
            self.nodes[node_id].status = status
            self.nodes[node_id].last_seen = self._get_timestamp()
            logger.info(f"更新节点状态: {node_id} -> {status.value}")
    
    async def send_message(
        self,
        target: str,
        message_type: MessageType,
        payload: Dict[str, Any],
        priority: int = 5
    ) -> str:
        """
        发送消息
        
        Args:
            target: 目标节点 ID
            message_type: 消息类型
            payload: 消息载荷
            priority: 优先级
            
        Returns:
            消息 ID
        """
        message = Message(
            id=self._generate_message_id(),
            type=message_type,
            source=self.node_id,
            target=target,
            payload=payload,
            timestamp=self._get_timestamp(),
            priority=priority
        )
        
        # 添加到消息队列
        await self.message_queue.put(message)
        
        # 记录历史
        self.message_history.append(message)
        
        logger.info(f"发送消息: {self.node_id} -> {target}, 类型: {message_type.value}")
        
        return message.id
    
    async def broadcast_message(
        self,
        message_type: MessageType,
        payload: Dict[str, Any],
        priority: int = 5
    ):
        """
        广播消息
        
        Args:
            message_type: 消息类型
            payload: 消息载荷
            priority: 优先级
        """
        for node_id in self.nodes.keys():
            if node_id != self.node_id:
                await self.send_message(node_id, message_type, payload, priority)
    
    def register_message_handler(
        self,
        message_type: MessageType,
        handler: Callable[[Message], Any]
    ):
        """
        注册消息处理器
        
        Args:
            message_type: 消息类型
            handler: 处理函数
        """
        self.message_handlers[message_type].append(handler)
        logger.info(f"注册消息处理器: {message_type.value}")
    
    async def start(self):
        """启动网络"""
        self.running = True
        logger.info("启动潮网式节点网络")
        
        # 启动消息处理循环
        asyncio.create_task(self._message_processing_loop())
        
        # 启动心跳循环
        asyncio.create_task(self._heartbeat_loop())
        
        # 启动节点发现循环
        asyncio.create_task(self._discovery_loop())
    
    async def stop(self):
        """停止网络"""
        self.running = False
        logger.info("停止潮网式节点网络")
    
    async def _message_processing_loop(self):
        """消息处理循环"""
        while self.running:
            try:
                # 从队列获取消息（带超时）
                try:
                    message = await asyncio.wait_for(
                        self.message_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # 处理消息
                await self._process_message(message)
            
            except Exception as e:
                logger.error(f"消息处理循环错误: {e}")
    
    async def _process_message(self, message: Message):
        """处理消息"""
        logger.info(f"处理消息: {message.id}, 类型: {message.type.value}")
        
        # 检查目标
        if message.target != self.node_id and message.target != "broadcast":
            # 需要转发
            await self._forward_message(message)
            return
        
        # 调用处理器
        handlers = self.message_handlers.get(message.type, [])
        for handler in handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"消息处理器错误: {e}")
    
    async def _forward_message(self, message: Message):
        """转发消息"""
        # 查找路由
        next_hop = self.routing_table.get(message.target)
        
        if next_hop:
            logger.info(f"转发消息: {message.id} -> {next_hop}")
            # 这里应该实际发送到下一跳节点
            # 简化版本：直接添加到队列
            await self.message_queue.put(message)
        else:
            logger.warning(f"无法转发消息: 未找到路由 {message.target}")
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                # 发送心跳
                await self.broadcast_message(
                    MessageType.HEARTBEAT,
                    {
                        'status': NodeStatus.ONLINE.value,
                        'timestamp': self._get_timestamp()
                    }
                )
                
                # 等待 30 秒
                await asyncio.sleep(30)
            
            except Exception as e:
                logger.error(f"心跳循环错误: {e}")
    
    async def _discovery_loop(self):
        """节点发现循环"""
        while self.running:
            try:
                # 发送发现消息
                await self.broadcast_message(
                    MessageType.DISCOVERY,
                    {
                        'node_id': self.node_id,
                        'node_name': self.node_name,
                        'node_type': self.node_type.value,
                        'capabilities': self.nodes[self.node_id].capabilities
                    }
                )
                
                # 等待 60 秒
                await asyncio.sleep(60)
            
            except Exception as e:
                logger.error(f"节点发现循环错误: {e}")
    
    def _generate_message_id(self) -> str:
        """生成消息 ID"""
        data = f"{self.node_id}_{self._get_timestamp()}_{len(self.message_history)}"
        return hashlib.md5(data.encode()).hexdigest()[:16]
    
    def _get_timestamp(self) -> str:
        """获取时间戳"""
        return datetime.now().isoformat()
    
    def get_network_topology(self) -> Dict:
        """获取网络拓扑"""
        topology = {
            'nodes': [],
            'edges': []
        }
        
        for node in self.nodes.values():
            topology['nodes'].append({
                'id': node.id,
                'name': node.name,
                'type': node.type.value,
                'status': node.status.value
            })
            
            for connected_node_id in node.connections:
                topology['edges'].append({
                    'source': node.id,
                    'target': connected_node_id
                })
        
        return topology
    
    def get_network_statistics(self) -> Dict:
        """获取网络统计"""
        return {
            'total_nodes': len(self.nodes),
            'online_nodes': sum(1 for n in self.nodes.values() if n.status == NodeStatus.ONLINE),
            'offline_nodes': sum(1 for n in self.nodes.values() if n.status == NodeStatus.OFFLINE),
            'total_connections': sum(len(n.connections) for n in self.nodes.values()) // 2,
            'total_messages': len(self.message_history),
            'nodes_by_type': {
                node_type.value: len(self.get_nodes_by_type(node_type))
                for node_type in NodeType
            }
        }
    
    def export_network_state(self, file_path: str):
        """导出网络状态"""
        state = {
            'node_id': self.node_id,
            'node_name': self.node_name,
            'node_type': self.node_type.value,
            'nodes': {
                node_id: {
                    'id': node.id,
                    'name': node.name,
                    'type': node.type.value,
                    'status': node.status.value,
                    'capabilities': node.capabilities,
                    'address': node.address,
                    'metadata': node.metadata,
                    'last_seen': node.last_seen,
                    'connections': list(node.connections)
                }
                for node_id, node in self.nodes.items()
            },
            'routing_table': self.routing_table,
            'timestamp': self._get_timestamp()
        }
        
        with open(file_path, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"导出网络状态: {file_path}")
    
    def import_network_state(self, file_path: str):
        """导入网络状态"""
        with open(file_path, 'r') as f:
            state = json.load(f)
        
        # 恢复节点
        for node_data in state['nodes'].values():
            if node_data['id'] != self.node_id:  # 跳过自己
                self.register_node(
                    node_id=node_data['id'],
                    name=node_data['name'],
                    node_type=NodeType(node_data['type']),
                    capabilities=node_data['capabilities'],
                    address=node_data['address'],
                    metadata=node_data['metadata']
                )
                
                # 恢复状态
                self.update_node_status(
                    node_data['id'],
                    NodeStatus(node_data['status'])
                )
        
        # 恢复路由表
        self.routing_table.update(state['routing_table'])
        
        logger.info(f"导入网络状态: {file_path}")
