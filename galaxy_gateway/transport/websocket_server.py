"""
WebSocket 服务端传输层

负责:
1. 管理 WebSocket 连接
2. 消息的收发
3. 连接状态管理
4. 心跳检测
"""

import asyncio
import json
import logging
from typing import Dict, Optional, Callable, Set
from datetime import datetime, timedelta

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..protocol import AIPMessage, MessageType, parse_message, create_error_message

logger = logging.getLogger(__name__)


class DeviceConnection(BaseModel):
    """设备连接信息"""
    device_id: str
    websocket: WebSocket
    connected_at: datetime
    last_heartbeat: datetime
    is_active: bool = True
    
    class Config:
        arbitrary_types_allowed = True


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
        try:
            await websocket.accept()
            
            now = datetime.utcnow()
            self.connections[device_id] = DeviceConnection(
                device_id=device_id,
                websocket=websocket,
                connected_at=now,
                last_heartbeat=now
            )
            
            logger.info(f"Device connected: {device_id}")
            
            if self.on_connect:
                await self._safe_callback(self.on_connect, device_id)
            
            return True
        except Exception as e:
            logger.error(f"Failed to accept connection for {device_id}: {e}")
            return False
    
    async def disconnect(self, device_id: str):
        """断开连接"""
        if device_id in self.connections:
            conn = self.connections[device_id]
            conn.is_active = False
            
            try:
                await conn.websocket.close()
            except Exception:
                pass
            
            del self.connections[device_id]
            logger.info(f"Device disconnected: {device_id}")
            
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
        """处理接收到的消息"""
        try:
            message = parse_message(data)
            
            # 更新心跳时间
            if device_id in self.connections:
                self.connections[device_id].last_heartbeat = datetime.utcnow()
            
            # 处理心跳消息
            if message.type == MessageType.DEVICE_HEARTBEAT:
                await self._handle_heartbeat(device_id, message)
                return
            
            # 调用外部消息处理器
            if self.on_message:
                await self._safe_callback(self.on_message, device_id, message)
                
        except Exception as e:
            logger.error(f"Failed to handle message from {device_id}: {e}")
            error_msg = create_error_message(device_id, str(e))
            await self.send_message(device_id, error_msg)
    
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
                
                now = datetime.utcnow()
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
