"""
Galaxy 多协议支持层
==================

支持多种通信协议:
1. HTTP REST API - 简单请求
2. WebSocket - 实时双向通信
3. AIP v2.0 - Agent Interaction Protocol
4. 本地直接调用 - 高性能

版本: v2.3.22
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import httpx
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MultiProtocolLayer")


class ProtocolType(Enum):
    """协议类型"""
    HTTP = "http"
    WEBSOCKET = "websocket"
    AIP = "aip"
    LOCAL = "local"


@dataclass
class ProtocolConfig:
    """协议配置"""
    protocol_type: ProtocolType
    base_url: str = ""
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class Message:
    """通用消息"""
    message_id: str
    message_type: str
    source: str
    target: str
    action: str
    params: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class HTTPProtocol:
    """HTTP 协议实现"""
    
    def __init__(self, config: ProtocolConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers=self.config.headers
            )
        return self._client
    
    async def send(self, message: Message) -> Dict[str, Any]:
        """发送 HTTP 请求"""
        client = await self._get_client()
        
        url = f"{self.config.base_url}/{message.action}"
        
        for attempt in range(self.config.retry_count):
            try:
                response = await client.post(
                    url,
                    json={
                        "message_id": message.message_id,
                        "params": message.params,
                        "source": message.source,
                        "timestamp": message.timestamp.isoformat()
                    }
                )
                response.raise_for_status()
                return response.json()
            
            except Exception as e:
                if attempt < self.config.retry_count - 1:
                    await asyncio.sleep(self.config.retry_delay)
                else:
                    return {"success": False, "error": str(e)}
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class WebSocketProtocol:
    """WebSocket 协议实现"""
    
    def __init__(self, config: ProtocolConfig):
        self.config = config
        self._connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self._message_handlers: Dict[str, Callable] = {}
    
    async def connect(self, target: str) -> bool:
        """建立 WebSocket 连接"""
        if target in self._connections:
            return True
        
        try:
            ws_url = self.config.base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws_url = f"{ws_url}/ws"
            
            self._connections[target] = await websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10
            )
            
            # 启动消息接收循环
            asyncio.create_task(self._receive_loop(target))
            
            logger.info(f"WebSocket connected to {target}")
            return True
        
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False
    
    async def _receive_loop(self, target: str):
        """消息接收循环"""
        ws = self._connections.get(target)
        if not ws:
            return
        
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    message_id = data.get("message_id")
                    
                    if message_id and message_id in self._message_handlers:
                        handler = self._message_handlers.pop(message_id)
                        await handler(data)
                
                except json.JSONDecodeError:
                    pass
        
        except websockets.ConnectionClosed:
            logger.warning(f"WebSocket connection closed: {target}")
            if target in self._connections:
                del self._connections[target]
    
    async def send(self, message: Message) -> Dict[str, Any]:
        """发送 WebSocket 消息"""
        target = message.target
        
        if target not in self._connections:
            await self.connect(target)
        
        ws = self._connections.get(target)
        if not ws:
            return {"success": False, "error": "WebSocket not connected"}
        
        # 创建响应 Future
        response_future = asyncio.Future()
        self._message_handlers[message.message_id] = lambda data: response_future.set_result(data)
        
        # 发送消息
        await ws.send(json.dumps({
            "message_id": message.message_id,
            "message_type": message.message_type,
            "action": message.action,
            "params": message.params,
            "source": message.source,
            "timestamp": message.timestamp.isoformat()
        }))
        
        # 等待响应
        try:
            response = await asyncio.wait_for(response_future, timeout=self.config.timeout)
            return response
        except asyncio.TimeoutError:
            return {"success": False, "error": "Timeout"}
    
    async def close(self):
        for ws in self._connections.values():
            await ws.close()
        self._connections.clear()


class AIPProtocol:
    """
    AIP v2.0 (Agent Interaction Protocol) 实现
    
    标准化的 Agent 交互协议
    """
    
    def __init__(self, config: ProtocolConfig):
        self.config = config
        self._http = HTTPProtocol(config)
        self._protocol_version = "2.0"
    
    def _build_message(self, message: Message) -> Dict[str, Any]:
        """构建 AIP 消息"""
        return {
            "header": {
                "message_id": message.message_id,
                "message_type": message.message_type,
                "protocol_version": self._protocol_version,
                "timestamp": message.timestamp.timestamp(),
                "source_node": message.source,
                "target_node": message.target,
                "correlation_id": message.metadata.get("correlation_id"),
                "priority": message.metadata.get("priority", 1),
                "ttl": message.metadata.get("ttl", 30)
            },
            "body": {
                "action": message.action,
                "params": message.params
            },
            "metadata": message.metadata
        }
    
    async def send(self, message: Message) -> Dict[str, Any]:
        """发送 AIP 消息"""
        aip_message = self._build_message(message)
        
        # 通过 HTTP 发送
        http_message = Message(
            message_id=message.message_id,
            message_type="aip_request",
            source=message.source,
            target=message.target,
            action="aip",
            params=aip_message,
            timestamp=message.timestamp
        )
        
        return await self._http.send(http_message)
    
    async def close(self):
        await self._http.close()


class LocalProtocol:
    """本地直接调用协议"""
    
    def __init__(self, config: ProtocolConfig):
        self.config = config
        self._handlers: Dict[str, Callable] = {}
    
    def register_handler(self, action: str, handler: Callable):
        """注册处理器"""
        self._handlers[action] = handler
    
    async def send(self, message: Message) -> Dict[str, Any]:
        """本地调用"""
        handler = self._handlers.get(message.action)
        
        if not handler:
            return {"success": False, "error": f"No handler for action: {message.action}"}
        
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(message.params)
            else:
                result = handler(message.params)
            
            return {
                "success": True,
                "message_id": message.message_id,
                "result": result
            }
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close(self):
        pass


class MultiProtocolLayer:
    """
    多协议支持层
    
    统一管理多种协议，自动选择最佳协议
    """
    
    def __init__(self):
        self._protocols: Dict[ProtocolType, Any] = {}
        self._default_protocol = ProtocolType.HTTP
    
    def configure(self, protocol_type: ProtocolType, config: ProtocolConfig):
        """配置协议"""
        if protocol_type == ProtocolType.HTTP:
            self._protocols[protocol_type] = HTTPProtocol(config)
        elif protocol_type == ProtocolType.WEBSOCKET:
            self._protocols[protocol_type] = WebSocketProtocol(config)
        elif protocol_type == ProtocolType.AIP:
            self._protocols[protocol_type] = AIPProtocol(config)
        elif protocol_type == ProtocolType.LOCAL:
            self._protocols[protocol_type] = LocalProtocol(config)
        
        logger.info(f"Configured protocol: {protocol_type.value}")
    
    async def send(
        self,
        message: Message,
        protocol: ProtocolType = None
    ) -> Dict[str, Any]:
        """发送消息"""
        protocol = protocol or self._default_protocol
        
        if protocol not in self._protocols:
            return {"success": False, "error": f"Protocol not configured: {protocol.value}"}
        
        proto = self._protocols[protocol]
        return await proto.send(message)
    
    def set_default_protocol(self, protocol: ProtocolType):
        """设置默认协议"""
        self._default_protocol = protocol
    
    async def close(self):
        """关闭所有协议连接"""
        for proto in self._protocols.values():
            await proto.close()


# 全局实例
multi_protocol = MultiProtocolLayer()
