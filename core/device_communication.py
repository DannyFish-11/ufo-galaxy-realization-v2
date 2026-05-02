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
    """本地传输层消息类型 — 用于 DeviceMessage 内部封装。

    Canonical v3 定义位于: galaxy_gateway.protocol.aip_v3.MessageType
    路由层 (handle_message) 不直接使用本枚举做分支判断；所有入站消息
    须先经 compat 层规范化为 v3 字符串后再路由。

    与 AIP v3.0 的对应关系（供参考）：
      COMMAND   → command         (v3 COMMAND)
      ACK       → ack             (本地应答，无直接 v3 对应)
      HEARTBEAT → heartbeat       (v3 DEVICE_HEARTBEAT.value)
      ERROR     → error           (v3 ERROR)
      WAKE_EVENT → wake_event     (v3 WAKE_EVENT)

    以下成员是 v2 兼容遗留类型，**不应出现在路由层判断中**：
      RESPONSE  → 应经 compat 转换为 command_result 后路由
      STATUS    → 应经 compat 转换为 device_status 后路由
      EVENT     → 应经 compat 转换为 wake_event 后路由
    """
    # 控制
    COMMAND = "command"         # 命令
    RESPONSE = "response"       # [v2 compat] 命令响应 — 勿直接用于路由
    ACK = "ack"                 # 确认

    # 状态
    HEARTBEAT = "heartbeat"     # 心跳 (v3 DEVICE_HEARTBEAT.value = "heartbeat")
    STATUS = "status"           # [v2 compat] 状态更新 — 勿直接用于路由

    # 事件
    EVENT = "event"             # [v2 compat] 通用事件 — 勿直接用于路由
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
        """处理收到的消息 — AIP v3-only 路由。

        所有入站消息先经 compat 层规范化为 AIP v3 字段（type/version），
        路由层只分发 v3 MessageType 字符串：

        =========================================================  ===================
        v3 type string                                             动作
        =========================================================  ===================
        ``device_register``                                        注册设备
        ``heartbeat``                                              更新心跳时间戳
        ``command_result``                                         解决 pending 命令请求
        ``task_assign``                                            转发到 action handler
        ``capability_report``                                      更新设备能力
        ``device_status``                                          更新设备状态
        ``wake_event``                                             转发到唤醒事件总线
        ``error``                                                  记录错误日志
        =========================================================  ===================

        Legacy 类型（"handshake", "response", "status", "TEXT", "event" 等）
        由 compat 层预先规范化，**不会直接出现在路由判断中**。

        Args:
            device_id: 设备 ID
            message_data: JSON 编码的消息字符串

        Returns:
            响应消息（可选），无需响应时返回 None
        """
        conn = self.connections.get(device_id)
        if not conn:
            return None

        try:
            raw_msg = json.loads(message_data)

            # Step 1 — Normalise to AIP v3 via compat layer.
            # Legacy types ("handshake", "response", "status", "TEXT", "event",
            # etc.) are mapped to their v3 equivalents here; v3 messages pass
            # through unchanged.  After this point routing only sees v3 names.
            try:
                from galaxy_gateway.protocol.compat import normalise_to_v3_dict
                v3_msg = normalise_to_v3_dict(raw_msg)
            except Exception as _norm_err:
                logger.warning("handle_message: compat normalisation failed: %s", _norm_err)
                v3_msg = dict(raw_msg)  # fallback on import/parse failure

            msg_type = v3_msg.get("type", "")
            conn.messages_received += 1
            conn.last_message = time.time()

            # Step 2 — Route based on v3 MessageType names only.

            # device_register — register / auto-register device
            if msg_type == "device_register":
                logger.info("收到设备注册消息: %s", device_id)
                try:
                    from core.device_registry import device_registry
                    if not device_registry.get(device_id):
                        await device_registry.register(
                            device_id=device_id,
                            device_type=(v3_msg.get("device_type") or
                                         v3_msg.get("platform", "android")),
                            name=f"Device ({device_id[:8]})",
                            capabilities=(v3_msg.get("capabilities") or
                                          ["screen", "touch", "keyboard"]),
                            metadata={"auto_registered": True},
                        )
                except Exception as e:
                    logger.warning("自动注册设备失败: %s", e)
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="device_register",
                    device_id=device_id,
                    payload={"status": "registered", "device_id": device_id},
                )

            # heartbeat — keep-alive
            # Use the inbound message_id as correlation_id in the ACK so that
            # senders using request-response semantics can match the reply.
            if msg_type == "heartbeat":
                conn.last_heartbeat = time.time()
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="heartbeat",
                    device_id=device_id,
                    correlation_id=v3_msg.get("message_id", ""),
                )

            # command_result — resolve pending command request
            if msg_type == "command_result":
                correlation_id = v3_msg.get("correlation_id", "")
                if correlation_id and correlation_id in conn.pending_requests:
                    future = conn.pending_requests[correlation_id]
                    if not future.done():
                        future.set_result(v3_msg.get("payload", {}))
                elif correlation_id:
                    logger.warning(
                        "command_result from %s has no matching pending request "
                        "(correlation_id=%r); possibly late or duplicate",
                        device_id, correlation_id,
                    )
                return None

            # task_assign — dispatch to registered action handler
            if msg_type == "task_assign":
                action = (v3_msg.get("action") or
                          v3_msg.get("task_type", "task_assign"))
                if action and action in self._message_handlers:
                    handler = self._message_handlers[action]
                    message = DeviceMessage(
                        type=MessageType.COMMAND,
                        action=action,
                        payload=v3_msg.get("payload", {}),
                        device_id=device_id,
                        correlation_id=v3_msg.get("correlation_id", ""),
                    )
                    result = await handler(device_id, message)
                    if result:
                        return DeviceMessage(
                            type=MessageType.ACK,
                            action=action,
                            payload=result,
                            device_id=device_id,
                            correlation_id=message.message_id,
                        )
                return None

            # capability_report — update device capabilities
            if msg_type == "capability_report":
                await self._handle_capability_report(device_id, v3_msg)
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="capability_report",
                    device_id=device_id,
                )

            # device_status — update device status in registry
            if msg_type == "device_status":
                status_msg = DeviceMessage(
                    type=MessageType.STATUS,
                    action="device_status",
                    payload=v3_msg.get("payload", {}),
                    device_id=device_id,
                )
                await self._handle_status(device_id, status_msg)
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="device_status",
                    device_id=device_id,
                    correlation_id=v3_msg.get("message_id", ""),
                )

            # wake_event — forward to wake event bus
            if msg_type == "wake_event":
                event_msg = DeviceMessage(
                    type=MessageType.WAKE_EVENT,
                    action="wake_event",
                    payload=v3_msg.get("payload", {}),
                    device_id=device_id,
                )
                await self._handle_event(device_id, event_msg)
                return None

            # error — log and return None
            if msg_type == "error":
                conn.errors += 1
                logger.error("设备错误: %s - %s", device_id, v3_msg.get("payload"))
                return None

            # device_state_snapshot — Android runtime state projection to V2
            if msg_type == "device_state_snapshot":
                try:
                    from core.android_device_state_store import absorb_device_state_snapshot
                    absorb_device_state_snapshot(
                        device_id,
                        v3_msg.get("payload", v3_msg),
                    )
                except Exception as _snap_err:
                    logger.warning(
                        "Failed to absorb device_state_snapshot from %s: %s",
                        device_id, _snap_err,
                    )
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="device_state_snapshot",
                    device_id=device_id,
                    correlation_id=v3_msg.get("message_id", ""),
                )

            # device_execution_event — Android execution phase event
            if msg_type == "device_execution_event":
                try:
                    from core.android_device_state_store import absorb_device_execution_event
                    absorb_device_execution_event(
                        device_id,
                        v3_msg.get("payload", v3_msg),
                    )
                except Exception as _evt_err:
                    logger.warning(
                        "Failed to absorb device_execution_event from %s: %s",
                        device_id, _evt_err,
                    )
                return DeviceMessage(
                    type=MessageType.ACK,
                    action="device_execution_event",
                    device_id=device_id,
                    correlation_id=v3_msg.get("message_id", ""),
                )

            # Step 3 — Unrecognised v3 type: try action-based dispatch, then
            # emit an event for any registered "message" callbacks.
            logger.debug("Unrecognised v3 message type from %s: %r", device_id, msg_type)
            action = v3_msg.get("action", "")
            if action and action in self._message_handlers:
                handler = self._message_handlers[action]
                message = DeviceMessage(
                    type=MessageType.COMMAND,
                    action=action,
                    payload=v3_msg.get("payload", {}),
                    device_id=device_id,
                )
                result = await handler(device_id, message)
                if result:
                    return DeviceMessage(
                        type=MessageType.ACK,
                        action=action,
                        payload=result,
                        device_id=device_id,
                        correlation_id=message.message_id,
                    )

            await self._emit_event("message", device_id, DeviceMessage(
                type=MessageType.EVENT,
                action=msg_type,
                payload=v3_msg.get("payload", {}),
                device_id=device_id,
            ))
            return None

        except Exception as e:
            logger.error("处理消息失败: %s - %s", device_id, e)
            return None
    
    def register_handler(self, action: str, handler: Callable):
        """注册消息处理器"""
        self._message_handlers[action] = handler

    async def _handle_capability_report(self, device_id: str, v3_msg: dict):
        """处理 capability_report: 将设备能力更新到注册表。"""
        try:
            from core.device_registry import device_registry
            payload = v3_msg.get("payload", {})
            capabilities = (payload.get("capabilities") or
                            payload.get("supported_actions", []))
            if capabilities and hasattr(device_registry, "update_capabilities"):
                await device_registry.update_capabilities(device_id, capabilities)
        except (ImportError, AttributeError) as e:
            logger.debug("设备注册表不可用（capability_report）: %s", e)

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
