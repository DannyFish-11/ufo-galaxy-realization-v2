#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
节点通信协议模块
================

定义节点间通信的标准协议：
1. 消息格式定义
2. 请求/响应协议
3. 事件广播协议
4. 流式传输协议

作者：Manus AI
日期：2026-02-06
"""

import json
import uuid
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto

logger = logging.getLogger("NodeProtocol")


# ============================================================================
# 消息类型
# ============================================================================

class MessageType(Enum):
    """消息类型"""
    # 请求/响应
    REQUEST = "request"
    RESPONSE = "response"
    
    # 事件
    EVENT = "event"
    BROADCAST = "broadcast"
    
    # 流式
    STREAM_START = "stream_start"
    STREAM_DATA = "stream_data"
    STREAM_END = "stream_end"
    
    # 控制
    PING = "ping"
    PONG = "pong"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    
    # 错误
    ERROR = "error"


class MessagePriority(Enum):
    """消息优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# ============================================================================
# 消息定义
# ============================================================================

@dataclass
class MessageHeader:
    """消息头"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: MessageType = MessageType.REQUEST
    timestamp: float = field(default_factory=time.time)
    source_node: str = ""
    target_node: str = ""
    correlation_id: Optional[str] = None  # 关联请求ID
    priority: MessagePriority = MessagePriority.NORMAL
    ttl: int = 30  # 生存时间（秒）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "correlation_id": self.correlation_id,
            "priority": self.priority.value,
            "ttl": self.ttl
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MessageHeader':
        return cls(
            message_id=data.get("message_id", str(uuid.uuid4())),
            message_type=MessageType(data.get("message_type", "request")),
            timestamp=data.get("timestamp", time.time()),
            source_node=data.get("source_node", ""),
            target_node=data.get("target_node", ""),
            correlation_id=data.get("correlation_id"),
            priority=MessagePriority(data.get("priority", 1)),
            ttl=data.get("ttl", 30)
        )


@dataclass
class Message:
    """标准消息"""
    header: MessageHeader
    action: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "header": self.header.to_dict(),
            "action": self.action,
            "payload": self.payload,
            "metadata": self.metadata
        }
        
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        return cls(
            header=MessageHeader.from_dict(data.get("header", {})),
            action=data.get("action", ""),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {})
        )
        
    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        return cls.from_dict(json.loads(json_str))
        
    def is_expired(self) -> bool:
        """检查消息是否过期"""
        return time.time() - self.header.timestamp > self.header.ttl


# ============================================================================
# 请求/响应消息
# ============================================================================

@dataclass
class Request(Message):
    """请求消息"""
    
    def __post_init__(self):
        self.header.message_type = MessageType.REQUEST
        
    @classmethod
    def create(cls, source: str, target: str, action: str, 
               params: Dict[str, Any] = None, priority: MessagePriority = MessagePriority.NORMAL) -> 'Request':
        """创建请求"""
        return cls(
            header=MessageHeader(
                source_node=source,
                target_node=target,
                message_type=MessageType.REQUEST,
                priority=priority
            ),
            action=action,
            payload=params or {}
        )


@dataclass
class Response(Message):
    """响应消息"""
    success: bool = True
    error: Optional[str] = None
    
    def __post_init__(self):
        self.header.message_type = MessageType.RESPONSE
        
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["success"] = self.success
        data["error"] = self.error
        return data
        
    @classmethod
    def from_request(cls, request: Request, success: bool = True, 
                     data: Dict[str, Any] = None, error: str = None) -> 'Response':
        """从请求创建响应"""
        return cls(
            header=MessageHeader(
                source_node=request.header.target_node,
                target_node=request.header.source_node,
                message_type=MessageType.RESPONSE,
                correlation_id=request.header.message_id
            ),
            action=request.action,
            payload=data or {},
            success=success,
            error=error
        )


# ============================================================================
# 事件消息
# ============================================================================

@dataclass
class Event(Message):
    """事件消息"""
    event_type: str = ""
    
    def __post_init__(self):
        self.header.message_type = MessageType.EVENT
        
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["event_type"] = self.event_type
        return data
        
    @classmethod
    def create(cls, source: str, event_type: str, 
               data: Dict[str, Any] = None) -> 'Event':
        """创建事件"""
        return cls(
            header=MessageHeader(
                source_node=source,
                message_type=MessageType.EVENT
            ),
            event_type=event_type,
            payload=data or {}
        )


# ============================================================================
# 流式消息
# ============================================================================

@dataclass
class StreamMessage(Message):
    """流式消息"""
    stream_id: str = ""
    sequence: int = 0
    is_final: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["stream_id"] = self.stream_id
        data["sequence"] = self.sequence
        data["is_final"] = self.is_final
        return data


class StreamSession:
    """流式会话"""
    
    def __init__(self, stream_id: str, source: str, target: str):
        self.stream_id = stream_id
        self.source = source
        self.target = target
        self.sequence = 0
        self.started = False
        self.ended = False
        self.data_buffer: List[Any] = []
        
    def start(self) -> StreamMessage:
        """开始流"""
        self.started = True
        return StreamMessage(
            header=MessageHeader(
                source_node=self.source,
                target_node=self.target,
                message_type=MessageType.STREAM_START
            ),
            stream_id=self.stream_id,
            sequence=0
        )
        
    def send(self, data: Any) -> StreamMessage:
        """发送数据"""
        self.sequence += 1
        return StreamMessage(
            header=MessageHeader(
                source_node=self.source,
                target_node=self.target,
                message_type=MessageType.STREAM_DATA
            ),
            stream_id=self.stream_id,
            sequence=self.sequence,
            payload={"data": data}
        )
        
    def end(self, final_data: Any = None) -> StreamMessage:
        """结束流"""
        self.ended = True
        self.sequence += 1
        return StreamMessage(
            header=MessageHeader(
                source_node=self.source,
                target_node=self.target,
                message_type=MessageType.STREAM_END
            ),
            stream_id=self.stream_id,
            sequence=self.sequence,
            payload={"data": final_data} if final_data else {},
            is_final=True
        )


# ============================================================================
# 消息路由器
# ============================================================================

class MessageRouter:
    """消息路由器"""
    
    def __init__(self):
        self.handlers: Dict[str, List[Callable]] = {}  # action -> handlers
        self.event_handlers: Dict[str, List[Callable]] = {}  # event_type -> handlers
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.streams: Dict[str, StreamSession] = {}
        
    def register_handler(self, action: str, handler: Callable):
        """注册动作处理器"""
        if action not in self.handlers:
            self.handlers[action] = []
        self.handlers[action].append(handler)
        
    def register_event_handler(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        
    async def route_message(self, message: Message) -> Optional[Response]:
        """路由消息"""
        msg_type = message.header.message_type
        
        if msg_type == MessageType.REQUEST:
            return await self._handle_request(message)
        elif msg_type == MessageType.RESPONSE:
            await self._handle_response(message)
        elif msg_type == MessageType.EVENT:
            await self._handle_event(message)
        elif msg_type in [MessageType.STREAM_START, MessageType.STREAM_DATA, MessageType.STREAM_END]:
            await self._handle_stream(message)
        elif msg_type == MessageType.PING:
            return self._handle_ping(message)
            
        return None
        
    async def _handle_request(self, request: Message) -> Response:
        """处理请求"""
        action = request.action
        handlers = self.handlers.get(action, [])
        
        if not handlers:
            return Response.from_request(
                request, 
                success=False, 
                error=f"未找到处理器: {action}"
            )
            
        try:
            # 调用第一个处理器
            handler = handlers[0]
            if asyncio.iscoroutinefunction(handler):
                result = await handler(request.payload)
            else:
                result = handler(request.payload)
                
            return Response.from_request(request, success=True, data=result)
            
        except Exception as e:
            logger.error(f"处理请求失败 {action}: {e}")
            return Response.from_request(request, success=False, error=str(e))
            
    async def _handle_response(self, response: Message):
        """处理响应"""
        correlation_id = response.header.correlation_id
        if correlation_id and correlation_id in self.pending_requests:
            future = self.pending_requests.pop(correlation_id)
            future.set_result(response)
            
    async def _handle_event(self, event: Message):
        """处理事件"""
        if isinstance(event, Event):
            event_type = event.event_type
        else:
            event_type = event.metadata.get("event_type", "")
            
        handlers = self.event_handlers.get(event_type, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event.payload)
                else:
                    handler(event.payload)
            except Exception as e:
                logger.error(f"处理事件失败 {event_type}: {e}")
                
    async def _handle_stream(self, message: Message):
        """处理流式消息"""
        if isinstance(message, StreamMessage):
            stream_id = message.stream_id
            
            if message.header.message_type == MessageType.STREAM_START:
                self.streams[stream_id] = StreamSession(
                    stream_id,
                    message.header.source_node,
                    message.header.target_node
                )
            elif message.header.message_type == MessageType.STREAM_DATA:
                if stream_id in self.streams:
                    self.streams[stream_id].data_buffer.append(message.payload.get("data"))
            elif message.header.message_type == MessageType.STREAM_END:
                if stream_id in self.streams:
                    del self.streams[stream_id]
                    
    def _handle_ping(self, message: Message) -> Response:
        """处理 Ping"""
        return Response(
            header=MessageHeader(
                source_node=message.header.target_node,
                target_node=message.header.source_node,
                message_type=MessageType.PONG,
                correlation_id=message.header.message_id
            ),
            payload={"timestamp": time.time()}
        )
        
    async def send_request(self, request: Request, timeout: float = 30.0) -> Response:
        """发送请求并等待响应"""
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request.header.message_id] = future
        
        try:
            # 这里需要实际的发送逻辑
            # 暂时直接路由
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self.pending_requests.pop(request.header.message_id, None)
            return Response.from_request(request, success=False, error="请求超时")


# ============================================================================
# 协议适配器
# ============================================================================

class ProtocolAdapter:
    """协议适配器 - 用于与外部系统通信"""
    
    @staticmethod
    def to_android_format(message: Message) -> Dict[str, Any]:
        """转换为 Android 端格式"""
        return {
            "id": message.header.message_id,
            "type": message.header.message_type.value,
            "action": message.action,
            "data": message.payload,
            "timestamp": int(message.header.timestamp * 1000),  # 毫秒
            "source": message.header.source_node,
            "target": message.header.target_node
        }
        
    @staticmethod
    def from_android_format(data: Dict[str, Any]) -> Message:
        """从 Android 端格式转换"""
        return Message(
            header=MessageHeader(
                message_id=data.get("id", str(uuid.uuid4())),
                message_type=MessageType(data.get("type", "request")),
                timestamp=data.get("timestamp", time.time() * 1000) / 1000,
                source_node=data.get("source", ""),
                target_node=data.get("target", "")
            ),
            action=data.get("action", ""),
            payload=data.get("data", {})
        )
        
    @staticmethod
    def to_websocket_format(message: Message) -> str:
        """转换为 WebSocket 格式"""
        return message.to_json()
        
    @staticmethod
    def from_websocket_format(json_str: str) -> Message:
        """从 WebSocket 格式转换"""
        return Message.from_json(json_str)


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    async def test():
        router = MessageRouter()
        
        # 注册处理器
        async def handle_test(params):
            return {"result": "success", "params": params}
            
        router.register_handler("test", handle_test)
        
        # 创建请求
        request = Request.create("node_a", "node_b", "test", {"key": "value"})
        print(f"请求: {request.to_json()}")
        
        # 路由请求
        response = await router.route_message(request)
        print(f"响应: {response.to_json()}")
        
        # 创建事件
        event = Event.create("node_a", "status_changed", {"status": "ready"})
        print(f"事件: {event.to_json()}")
        
        # 测试流式
        stream = StreamSession("stream_1", "node_a", "node_b")
        print(f"流开始: {stream.start().to_json()}")
        print(f"流数据: {stream.send({'chunk': 1}).to_json()}")
        print(f"流结束: {stream.end().to_json()}")
        
    asyncio.run(test())
