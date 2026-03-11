"""
Galaxy - 统一设备通信协议
============================

提供统一的设备通信层，支持多种通信方式：
1. WebSocket - 实时双向通信
2. HTTP Long Polling - 兼容模式
3. MQTT - IoT 设备
4. ADB - Android 设备

功能：
1. 统一的消息格式
2. 心跳保活
3. 断线重连
4. 消息确认
5. 命令执行

使用方法：
    from core.device_communication import device_comm
    
    # 连接设备
    await device_comm.connect("android_001", websocket)
    
    # 发送命令
    result = await device_comm.send_command("android_001", "click", {"x": 100, "y": 200})
    
    # 断开设备
    await device_comm.disconnect("android_001")
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Union
from fastapi import WebSocket

logger = logging.getLogger("Galaxy.DeviceComm")


# ============================================================================
# 消息协议定义
# ============================================================================

try:
    from galaxy_gateway.protocol.aip_v3 import MessageType as AIPv3MessageType
except ImportError:
    AIPv3MessageType = None  # type: ignore[assignment,misc]


class MessageType(str, Enum):
    """消息类型 — 兼容 AIP v3.0 (COMPAT LAYER)

    这是简化的本地消息类型。Canonical 定义位于:
        galaxy_gateway.protocol.aip_v3.MessageType

    本地简化类型与 AIP v3.0 MessageType 的映射关系：
      COMMAND     → COMMAND
      RESPONSE    → TASK_RESULT
      HEARTBEAT   → DEVICE_HEARTBEAT
      STATUS      → DEVICE_STATUS
      ERROR       → ERROR
    使用 ``to_aip_v3()`` 获取对应的 AIP v3.0 MessageType 枚举值。
    """
    # 控制
    COMMAND = "command"         # 命令
    RESPONSE = "response"       # 响应
    ACK = "ack"                 # 确认

    # 状态
    HEARTBEAT = "heartbeat"     # 心跳
    STATUS = "status"           # 状态更新

    # 事件
    EVENT = "event"             # 事件
    ERROR = "error"             # 错误

    # 流
    STREAM_START = "stream_start"
    STREAM_DATA = "stream_data"
    STREAM_END = "stream_end"

    # 唤醒与会话漫游
    WAKE_EVENT = "wake_event"           # 设备唤醒事件
    SESSION_MIGRATE = "session_migrate" # 会话迁移请求
    SESSION_RESTORE = "session_restore" # 会话恢复

    def to_aip_v3(self):
        """转换为 AIP v3.0 MessageType 枚举值（若可用）或名称字符串。

        Returns:
            galaxy_gateway.protocol.aip_v3.MessageType 枚举值，
            若 v3 模块不可用则返回 str。
        """
        _name_map = {
            "command": "COMMAND",
            "response": "TASK_RESULT",
            "ack": "COORD_SYNC",
            "heartbeat": "DEVICE_HEARTBEAT",
            "status": "DEVICE_STATUS",
            "event": "WAKE_EVENT",
            "error": "ERROR",
            "stream_start": "SCREEN_STREAM_START",
            "stream_data": "SCREEN_STREAM_DATA",
            "stream_end": "SCREEN_STREAM_STOP",
            "wake_event": "WAKE_EVENT",
            "session_migrate": "SESSION_MIGRATE",
            "session_restore": "SESSION_MIGRATE_ACK",
        }
        v3_name = _name_map.get(self.value, self.value.upper())
        if AIPv3MessageType is not None:
            try:
                return AIPv3MessageType[v3_name]
            except KeyError:
                pass
        return v3_name


@dataclass
class DeviceMessage:
    """设备消息"""
    type: MessageType
    action: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    device_id: str = ""
    correlation_id: str = ""  # 关联的请求 ID
    
    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "action": self.action,
            "payload": self.payload,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "device_id": self.device_id,
            "correlation_id": self.correlation_id,
        })

    def to_aip_v3_dict(self) -> dict:
        """转换为 AIP v3.0 格式的字典"""
        return {
            "version": "3.0",
            "message_id": self.message_id,
            "type": self.type.to_aip_v3(),
            "device_id": self.device_id,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "correlation_id": self.correlation_id,
            "payload": {
                "action": self.action,
                **self.payload,
            },
        }
    
    @classmethod
    def from_json(cls, data: str) -> "DeviceMessage":
        obj = json.loads(data)
        return cls(
            type=MessageType(obj.get("type", "command")),
            action=obj.get("action", ""),
            payload=obj.get("payload", {}),
            message_id=obj.get("message_id", ""),
            timestamp=obj.get("timestamp", time.time()),
            device_id=obj.get("device_id", ""),
            correlation_id=obj.get("correlation_id", ""),
        )


@dataclass
class DeviceConnection:
    """设备连接"""
    device_id: str
    websocket: Optional[WebSocket] = None
    connected_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    last_message: float = field(default_factory=time.time)
    
    # 统计
    messages_sent: int = 0
    messages_received: int = 0
    commands_executed: int = 0
    errors: int = 0
    
    # 状态
    status: str = "connected"
    
    # 等待响应的请求
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)
    
    def is_alive(self, timeout: float = 60.0) -> bool:
        """检查连接是否存活"""
        return time.time() - self.last_heartbeat < timeout


# ============================================================================
# 设备通信管理器
# ============================================================================

class DeviceCommunication:
    """
    统一设备通信管理器
    
    管理所有设备的通信连接
    """
    
    _instance = None
    
    def __init__(self):
        # 设备连接
        self.connections: Dict[str, DeviceConnection] = {}
        
        # 心跳任务
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # 消息处理器
        self._message_handlers: Dict[str, Callable] = {}
        
        # 事件回调
        self._on_device_connected: List[Callable] = []
        self._on_device_disconnected: List[Callable] = []
        self._on_device_message: List[Callable] = []
        
        # 配置
        self.heartbeat_interval = 30.0
        self.heartbeat_timeout = 60.0
        self.command_timeout = 30.0
        
        logger.info("设备通信管理器初始化")
    
    @classmethod
    def get_instance(cls) -> "DeviceCommunication":
        # NOTE: This singleton is used for process-wide state sharing.
        # Avoid adding new call sites — prefer dependency injection where
        # possible to improve testability.  See ARCHITECTURE_REVIEW.md
        # (Singleton Guardrails section) for the planned refactor strategy.
        if cls._instance is None:
            cls._instance = DeviceCommunication()
        return cls._instance
    
    # ========================================================================
    # 连接管理
    # ========================================================================
    
    async def connect(
        self,
        device_id: str,
        websocket: WebSocket,
    ) -> bool:
        """
        连接设备
        
        Args:
            device_id: 设备 ID
            websocket: WebSocket 连接
        
        Returns:
            是否成功
        """
        try:
            # 创建连接
            conn = DeviceConnection(
                device_id=device_id,
                websocket=websocket,
                connected_at=time.time(),
                last_heartbeat=time.time(),
                status="connected",
            )
            
            self.connections[device_id] = conn
            
            # 更新设备注册表
            try:
                from core.device_registry import device_registry
                await device_registry.update_status(device_id, status="online")
            except (ImportError, AttributeError) as e:
                logger.debug(f"设备注册表不可用: {e}")
            
            # 启动心跳任务
            if not self._heartbeat_task:
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # 触发事件
            await self._emit_event("connected", device_id)
            
            logger.info(f"设备连接: {device_id}")
            return True
            
        except Exception as e:
            logger.error(f"设备连接失败: {device_id} - {e}")
            return False
    
    async def disconnect(self, device_id: str) -> bool:
        """断开设备连接"""
        if device_id not in self.connections:
            return False
        
        conn = self.connections.pop(device_id)
        
        # 关闭 WebSocket（带超时防止挂起）
        if conn.websocket:
            try:
                await asyncio.wait_for(conn.websocket.close(), timeout=5.0)
            except Exception as e:
                logger.debug(f"WebSocket 关闭异常: {device_id} - {e}")

        # 更新设备注册表
        try:
            from core.device_registry import device_registry, DeviceStatus
            await device_registry.update_status(device_id, status=DeviceStatus.OFFLINE)
        except (ImportError, AttributeError) as e:
            logger.debug(f"设备注册表不可用: {e}")
        
        # 触发事件
        await self._emit_event("disconnected", device_id)
        
        logger.info(f"设备断开: {device_id}")
        return True
    
    def is_connected(self, device_id: str) -> bool:
        """检查设备是否连接"""
        conn = self.connections.get(device_id)
        return conn is not None and conn.is_alive(self.heartbeat_timeout)
    
    def list_connected_devices(self) -> List[str]:
        """列出已连接的设备"""
        return [
            device_id for device_id, conn in self.connections.items()
            if conn.is_alive(self.heartbeat_timeout)
        ]
    
    # ========================================================================
    # 消息发送
    # ========================================================================
    
    async def send(
        self,
        device_id: str,
        message: DeviceMessage,
    ) -> bool:
        """
        发送消息
        
        Args:
            device_id: 设备 ID
            message: 消息
        
        Returns:
            是否成功
        """
        conn = self.connections.get(device_id)
        if not conn or not conn.websocket:
            logger.warning(f"设备未连接: {device_id}")
            return False
        
        try:
            message.device_id = device_id
            await conn.websocket.send_text(message.to_json())
            conn.messages_sent += 1
            conn.last_message = time.time()
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {device_id} - {e}")
            conn.errors += 1
            return False
    
    async def send_command(
        self,
        device_id: str,
        action: str,
        params: Dict[str, Any] = None,
        timeout: float = None,
    ) -> Dict[str, Any]:
        """
        发送命令并等待响应
        
        Args:
            device_id: 设备 ID
            action: 动作
            params: 参数
            timeout: 超时时间
        
        Returns:
            响应结果
        """
        conn = self.connections.get(device_id)
        if not conn or not conn.websocket:
            return {"success": False, "error": "设备未连接"}
        
        timeout = timeout or self.command_timeout
        
        # 创建消息
        message = DeviceMessage(
            type=MessageType.COMMAND,
            action=action,
            payload=params or {},
        )
        
        # 创建等待响应的 Future
        future = asyncio.Future()
        conn.pending_requests[message.message_id] = future
        
        try:
            # 发送命令
            success = await self.send(device_id, message)
            if not success:
                return {"success": False, "error": "发送失败"}
            
            # 等待响应
            response = await asyncio.wait_for(future, timeout=timeout)
            
            conn.commands_executed += 1
            return response
            
        except asyncio.TimeoutError:
            return {"success": False, "error": "命令超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.pending_requests.pop(message.message_id, None)
    
    async def broadcast(
        self,
        message: DeviceMessage,
        device_ids: List[str] = None,
    ) -> Dict[str, bool]:
        """
        广播消息
        
        Args:
            message: 消息
            device_ids: 设备 ID 列表 (None 表示所有设备)
        
        Returns:
            各设备的发送结果
        """
        if device_ids is None:
            device_ids = list(self.connections.keys())
        
        results = {}
        for device_id in device_ids:
            results[device_id] = await self.send(device_id, message)
        
        return results
    
    # ========================================================================
    # 消息处理
    # ========================================================================
    
    async def handle_message(
        self,
        device_id: str,
        message_data: str,
    ) -> Optional[DeviceMessage]:
        """
        处理收到的消息
        
        Args:
            device_id: 设备 ID
            message_data: 消息数据
        
        Returns:
            响应消息 (如果需要)
        """
        conn = self.connections.get(device_id)
        if not conn:
            return None
        
        try:
            # 先尝试解析为 JSON
            import json
            raw_msg = json.loads(message_data)
            
            # 兼容安卓端握手消息
            if raw_msg.get("type") == "handshake":
                logger.info(f"收到安卓端握手: {device_id}")
                
                # 自动注册设备
                try:
                    from core.device_registry import device_registry
                    device = device_registry.get(device_id)
                    if not device:
                        await device_registry.register(
                            device_id=device_id,
                            device_type=raw_msg.get("platform", "android"),
                            name=f"Android Device ({device_id[:8]})",
                            capabilities=["screen", "touch", "keyboard"],
                            metadata={
                                "version": raw_msg.get("version", "2.0"),
                                "auto_registered": True,
                            },
                        )
                except Exception as e:
                    logger.warning(f"自动注册设备失败: {e}")
                
                # 返回握手确认
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="handshake",
                    payload={"status": "connected", "device_id": device_id},
                )
            
            # 兼容安卓端心跳消息
            if raw_msg.get("type") == "heartbeat":
                conn.last_heartbeat = time.time()
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="heartbeat",
                )
            
            # 兼容安卓端 AIP 消息格式
            if "type" in raw_msg and "payload" in raw_msg:
                # AIP 格式，转换为 DeviceMessage
                message = DeviceMessage(
                    type=MessageType.COMMAND if raw_msg.get("type") in ["TEXT", "COMMAND"] else MessageType.EVENT,
                    action=raw_msg.get("type", "").lower(),
                    payload=raw_msg.get("payload", {}),
                    device_id=device_id,
                )
            else:
                # 标准 DeviceMessage 格式
                message = DeviceMessage.from_json(message_data)
            conn.messages_received += 1
            conn.last_message = time.time()
            
            # 处理心跳
            if message.type == MessageType.HEARTBEAT:
                conn.last_heartbeat = time.time()
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="heartbeat",
                    correlation_id=message.message_id,
                )
            
            # 处理响应
            elif message.type == MessageType.RESPONSE:
                if message.correlation_id in conn.pending_requests:
                    future = conn.pending_requests[message.correlation_id]
                    if not future.done():
                        future.set_result(message.payload)
                return None
            
            # 处理状态更新
            elif message.type == MessageType.STATUS:
                await self._handle_status(device_id, message)
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="status",
                    correlation_id=message.message_id,
                )
            
            # 处理事件
            elif message.type == MessageType.EVENT:
                await self._handle_event(device_id, message)
                return None
            
            # 处理错误
            elif message.type == MessageType.ERROR:
                conn.errors += 1
                logger.error(f"设备错误: {device_id} - {message.payload}")
                return None
            
            # 触发消息回调
            await self._emit_event("message", device_id, message)
            
            # 调用注册的处理器
            if message.action in self._message_handlers:
                handler = self._message_handlers[message.action]
                result = await handler(device_id, message)
                if result:
                    return DeviceMessage(
                        type=MessageType.RESPONSE,
                        action=message.action,
                        payload=result,
                        correlation_id=message.message_id,
                    )
            
            return None
            
        except Exception as e:
            logger.error(f"处理消息失败: {device_id} - {e}")
            return None
    
    def register_handler(self, action: str, handler: Callable):
        """注册消息处理器"""
        self._message_handlers[action] = handler
    
    async def _handle_status(self, device_id: str, message: DeviceMessage):
        """处理状态更新"""
        try:
            from core.device_registry import device_registry
            status_data = message.payload
            # 更新设备状态
            # ...
        except (ImportError, AttributeError) as e:
            logger.debug(f"设备注册表不可用: {e}")
    
    async def _handle_event(self, device_id: str, message: DeviceMessage):
        """处理事件"""
        event_type = message.payload.get("event_type", "")
        event_data = message.payload.get("data", {})
        logger.info(f"设备事件: {device_id} - {event_type}")

        # 处理 WAKE_EVENT：转发到统一唤醒事件总线
        wake_event_value = MessageType.WAKE_EVENT.value
        if event_type == wake_event_value or message.action == wake_event_value:
            wake_payload = message.payload if "wake_word" in message.payload else event_data
            await self._handle_wake_event(device_id, wake_payload)

    async def _handle_wake_event(self, device_id: str, payload: dict):
        """将唤醒事件转发到 WakeEventBus"""
        try:
            from galaxy_gateway.wake_event_bus import wake_event_bus, RawWakeEvent
            raw = RawWakeEvent(
                source_device_id=device_id,
                wake_word=payload.get("wake_word", ""),
                timestamp=payload.get("timestamp", time.time()),
                task_type=payload.get("task_type", "general"),
                confidence=payload.get("confidence", 1.0),
                extra=payload.get("extra", {}),
            )
            await wake_event_bus.publish(raw)
        except Exception as e:
            logger.warning(f"转发唤醒事件失败: {device_id} - {e}")
    
    # ========================================================================
    # 心跳
    # ========================================================================
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                # 检查所有连接
                now = time.time()
                for device_id, conn in list(self.connections.items()):
                    # 检查超时
                    if not conn.is_alive(self.heartbeat_timeout):
                        logger.warning(f"设备心跳超时: {device_id}")
                        await self.disconnect(device_id)
                        continue
                    
                    # 发送心跳
                    await self.send(device_id, DeviceMessage(
                        type=MessageType.HEARTBEAT,
                    ))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"心跳循环错误: {e}")
    
    # ========================================================================
    # 事件
    # ========================================================================
    
    async def _emit_event(self, event_type: str, device_id: str, message: DeviceMessage = None):
        """触发事件"""
        if event_type == "connected":
            for callback in self._on_device_connected:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_id)
                    else:
                        callback(device_id)
                except Exception as e:
                    logger.error(f"事件回调失败: {e}")
        
        elif event_type == "disconnected":
            for callback in self._on_device_disconnected:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_id)
                    else:
                        callback(device_id)
                except Exception as e:
                    logger.error(f"事件回调失败: {e}")
        
        elif event_type == "message":
            for callback in self._on_device_message:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_id, message)
                    else:
                        callback(device_id, message)
                except Exception as e:
                    logger.error(f"事件回调失败: {e}")
    
    def on_device_connected(self, callback: Callable):
        """注册设备连接事件回调"""
        self._on_device_connected.append(callback)
    
    def on_device_disconnected(self, callback: Callable):
        """注册设备断开事件回调"""
        self._on_device_disconnected.append(callback)
    
    def on_device_message(self, callback: Callable):
        """注册设备消息事件回调"""
        self._on_device_message.append(callback)
    
    # ========================================================================
    # 统计
    # ========================================================================
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        total_sent = sum(c.messages_sent for c in self.connections.values())
        total_received = sum(c.messages_received for c in self.connections.values())
        total_commands = sum(c.commands_executed for c in self.connections.values())
        total_errors = sum(c.errors for c in self.connections.values())
        
        return {
            "connected_devices": len(self.connections),
            "total_messages_sent": total_sent,
            "total_messages_received": total_received,
            "total_commands": total_commands,
            "total_errors": total_errors,
        }


# ============================================================================
# 全局实例
# ============================================================================

device_comm = DeviceCommunication.get_instance()
