"""
UFO Galaxy - 统一设备协调器
============================

组合三个设备协调子系统的能力到单一外观层：

1. TaskOrchestrator  — 高层任务编排（剪贴板/文件/媒体/通知）
2. SessionManager    — WebSocket 会话管理，采用 AIP v3.0 协议
3. FaultTolerance    — 分布式容错（从 Node_71 可选导入）

协议：
  - 规范协议：AIP v3.0 (galaxy_gateway/protocol/aip_v3.py)
  - 兼容层：galaxy_gateway/protocol/compat.py 自动支持 AIP v1.0/v2.0/v3.0
  - 底层传输：core/device_communication.py (DeviceMessage JSON)

使用方法：
    from core.unified_coordinator import get_unified_coordinator
    coordinator = get_unified_coordinator()
    result = await coordinator.execute_cross_device_task("把手机剪贴板内容复制到电脑")
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("UFO-Galaxy.UnifiedCoordinator")


# ============================================================================
# 会话管理（从 enhancements/multidevice 迁移，使用 JSON 协议）
# ============================================================================

@dataclass
class DeviceSession:
    """设备 WebSocket 会话"""
    session_id: str
    websocket: Any  # WebSocket instance
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    device_id: Optional[str] = None
    is_authenticated: bool = False
    message_count: int = 0
    ip_address: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    pending_acks: Dict[str, asyncio.Future] = field(default_factory=dict)

    def update_activity(self):
        self.last_activity = time.time()
        self.message_count += 1

    async def send_json(self, data: Dict[str, Any], require_ack: bool = False, timeout: float = 5.0) -> bool:
        """发送 JSON 消息"""
        try:
            await self.websocket.send_text(json.dumps(data))
            self.update_activity()
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    async def send_aip_message(self, message) -> bool:
        """发送 AIP v3.0 格式消息

        Args:
            message: AIPMessage 实例 (galaxy_gateway.protocol.aip_v3.AIPMessage)
        """
        try:
            if hasattr(message, 'model_dump_json'):
                await self.websocket.send_text(message.model_dump_json())
            elif hasattr(message, 'model_dump'):
                await self.websocket.send_text(json.dumps(message.model_dump()))
            else:
                await self.websocket.send_text(json.dumps(message))
            self.update_activity()
            return True
        except Exception as e:
            logger.error(f"发送 AIP 消息失败: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "connected_at": self.connected_at,
            "last_activity": self.last_activity,
            "message_count": self.message_count,
            "ip_address": self.ip_address,
            "is_authenticated": self.is_authenticated,
        }


class SessionManager:
    """设备会话管理器

    从 enhancements/multidevice/device_coordinator.py 迁移并简化。
    采用 AIP v3.0 (galaxy_gateway.protocol.aip_v3) 作为规范协议，
    通过 galaxy_gateway.protocol.compat 兼容层自动支持 AIP v1.0/v2.0 客户端。
    """

    def __init__(self, session_timeout: float = 300.0):
        self.sessions: Dict[str, DeviceSession] = {}
        self.device_sessions: Dict[str, str] = {}  # device_id -> session_id
        self.session_timeout = session_timeout
        self._lock = asyncio.Lock()
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)

    def register_callback(self, event: str, callback: Callable):
        self._callbacks[event].append(callback)

    async def _notify(self, event: str, *args, **kwargs):
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args, **kwargs)
                else:
                    cb(*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")

    async def create_session(self, websocket, ip_address: Optional[str] = None) -> DeviceSession:
        session_id = str(uuid.uuid4())
        session = DeviceSession(
            session_id=session_id,
            websocket=websocket,
            ip_address=ip_address,
        )
        async with self._lock:
            self.sessions[session_id] = session
        logger.info(f"Session created: {session_id}")
        await self._notify("session_created", session)
        return session

    async def remove_session(self, session_id: str) -> Optional[DeviceSession]:
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session and session.device_id:
                self.device_sessions.pop(session.device_id, None)
        if session:
            logger.info(f"Session removed: {session_id}")
            await self._notify("session_removed", session)
        return session

    async def authenticate_session(
        self, session_id: str, device_id: str, device_info: Any = None
    ) -> bool:
        async with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            # 替换同一设备的旧会话
            old_sid = self.device_sessions.get(device_id)
            if old_sid and old_sid != session_id:
                self.sessions.pop(old_sid, None)
            session.device_id = device_id
            session.is_authenticated = True
            self.device_sessions[device_id] = session_id
        logger.info(f"Session {session_id} authenticated for device {device_id}")
        await self._notify("session_authenticated", session)
        return True

    async def get_session(self, session_id: str) -> Optional[DeviceSession]:
        return self.sessions.get(session_id)

    async def get_session_by_device(self, device_id: str) -> Optional[DeviceSession]:
        sid = self.device_sessions.get(device_id)
        return self.sessions.get(sid) if sid else None

    async def get_all_sessions(self) -> List[DeviceSession]:
        return list(self.sessions.values())

    async def get_authenticated_sessions(self) -> List[DeviceSession]:
        return [s for s in self.sessions.values() if s.is_authenticated]

    async def send_to_device(self, device_id: str, message: Union[Dict[str, Any], Any]) -> bool:
        """发送消息到设备（支持 Dict 和 AIPMessage）"""
        session = await self.get_session_by_device(device_id)
        if not session:
            logger.warning(f"No session for device {device_id}")
            return False
        if hasattr(message, 'model_dump_json'):
            return await session.send_aip_message(message)
        return await session.send_json(message)

    async def broadcast(
        self, message: Dict[str, Any], exclude_devices: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        exclude = set(exclude_devices or [])
        results = {}
        sessions = await self.get_authenticated_sessions()
        for session in sessions:
            if session.device_id and session.device_id not in exclude:
                try:
                    results[session.device_id] = await session.send_json(message)
                except Exception as e:
                    logger.error(f"Broadcast error to {session.device_id}: {e}")
                    results[session.device_id] = False
        return results

    async def handle_message(self, session_id: str, raw_data: Union[str, dict]) -> Optional[Dict]:
        """解析并处理 AIP 消息（自动兼容 v1/v2/v3）

        通过 galaxy_gateway.protocol.compat.parse_message_compat 自动检测协议版本，
        将 AIP v1.0/v2.0 消息规范化到 v3.0 后分发到对应处理器。

        Args:
            session_id: 会话 ID
            raw_data: 原始消息（JSON 字符串或字典）

        Returns:
            响应字典，或 None
        """
        try:
            from galaxy_gateway.protocol.compat import parse_message_compat
            from galaxy_gateway.protocol.aip_v3 import MessageType as AIPMessageType

            message = parse_message_compat(raw_data)
            session = self.sessions.get(session_id)
            if session:
                session.update_activity()

            # 设备注册
            if message.type == AIPMessageType.DEVICE_REGISTER:
                device_id = message.device_id
                device_info = message.payload.get("device_info")
                ok = await self.authenticate_session(session_id, device_id, device_info)
                return {
                    "type": AIPMessageType.DEVICE_REGISTER_ACK.value,
                    "message_id": message.message_id,
                    "correlation_id": message.message_id,
                    "success": ok,
                    "device_id": device_id,
                }

            # 心跳
            if message.type == AIPMessageType.DEVICE_HEARTBEAT:
                return {
                    "type": AIPMessageType.DEVICE_HEARTBEAT_ACK.value,
                    "message_id": message.message_id,
                    "correlation_id": message.message_id,
                    "timestamp": time.time(),
                }

            # 设备状态
            if message.type == AIPMessageType.DEVICE_STATUS:
                if session and session.device_id:
                    # 通过 metadata 存储状态
                    session.metadata.update(message.payload)
                return {
                    "type": "ack",
                    "message_id": message.message_id,
                    "correlation_id": message.message_id,
                }

            # 任务提交
            if message.type == AIPMessageType.TASK_SUBMIT:
                return {
                    "type": AIPMessageType.TASK_STATUS.value,
                    "message_id": message.message_id,
                    "correlation_id": message.message_id,
                    "task_id": message.task_id,
                    "task_status": "pending",
                }

            # 默认 ACK
            return {
                "type": "ack",
                "message_id": message.message_id,
                "correlation_id": message.message_id,
                "version": "3.0",
            }

        except Exception as e:
            logger.error(f"消息处理失败: {e}")
            return {"type": "error", "error": str(e)}

    async def cleanup_stale(self, timeout: float = None) -> int:
        timeout = timeout or self.session_timeout
        now = time.time()
        stale = []
        async with self._lock:
            for sid, session in self.sessions.items():
                if now - session.last_activity > timeout:
                    stale.append(sid)
            for sid in stale:
                session = self.sessions.pop(sid, None)
                if session and session.device_id:
                    self.device_sessions.pop(session.device_id, None)
        for sid in stale:
            logger.info(f"Cleaned up stale session: {sid}")
        return len(stale)

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self.sessions)
        authenticated = sum(1 for s in self.sessions.values() if s.is_authenticated)
        total_messages = sum(s.message_count for s in self.sessions.values())
        return {
            "total_sessions": total,
            "authenticated_sessions": authenticated,
            "total_messages": total_messages,
            "active_devices": len(self.device_sessions),
        }


# ============================================================================
# 统一设备协调器
# ============================================================================

class UnifiedDeviceCoordinator:
    """统一设备协调器 — 组合所有子系统的能力

    层次：
      Layer 0: core/device_types.py           — 类型枚举
      Layer 1: core/device_registry.py        — 设备 CRUD
      Layer 2: core/device_communication.py   — WebSocket 传输
      Layer 3: 此模块                          — 统一协调外观
    """

    _instance = None

    def __init__(self):
        # Layer 1: 共享数据
        from core.shared_data_store import SharedDataStore
        self._shared_data = SharedDataStore()

        # Layer 2: 任务编排
        from core.task_orchestrator import TaskOrchestrator
        self._orchestrator = TaskOrchestrator()

        # Layer 3: 会话管理
        self._session_manager = SessionManager()

        # Layer 4: 分布式容错（可选 — 从 Node_71 导入）
        self._fault_tolerance = None
        try:
            from nodes.Node_71_MultiDeviceCoordination.core.fault_tolerance import (
                FaultToleranceLayer,
                CircuitBreakerConfig,
                RetryConfig,
                FailoverConfig,
            )
            self._fault_tolerance = FaultToleranceLayer(
                circuit_config=CircuitBreakerConfig(),
                retry_config=RetryConfig(),
                failover_config=FailoverConfig(),
            )
            logger.info("分布式容错层已加载（Node_71）")
        except (ImportError, Exception) as e:
            logger.info(f"分布式容错层不可用（降级模式）: {e}")

        logger.info("统一设备协调器初始化完成")

    # === 任务编排 API ===

    async def execute_cross_device_task(self, command: str, context: Dict = None) -> Dict:
        """执行跨设备协同任务"""
        return await self._orchestrator.execute_task(command, context)

    async def sync_clipboard(self, command: str, context: Dict = None) -> Dict:
        return await self._orchestrator.sync_clipboard(command, context)

    async def transfer_file(self, command: str, context: Dict = None) -> Dict:
        return await self._orchestrator.transfer_file(command, context)

    async def sync_media_control(self, command: str, context: Dict = None) -> Dict:
        return await self._orchestrator.sync_media_control(command, context)

    async def broadcast_notification(self, command: str, context: Dict = None) -> Dict:
        return await self._orchestrator.broadcast_notification(command, context)

    # === 会话管理 API ===

    async def create_session(self, websocket, ip_address: Optional[str] = None) -> DeviceSession:
        return await self._session_manager.create_session(websocket, ip_address)

    async def remove_session(self, session_id: str) -> Optional[DeviceSession]:
        return await self._session_manager.remove_session(session_id)

    async def authenticate_session(self, session_id: str, device_id: str, device_info=None) -> bool:
        return await self._session_manager.authenticate_session(session_id, device_id, device_info)

    async def send_to_device(self, device_id: str, message: Union[Dict[str, Any], Any]) -> bool:
        """发送消息到设备（支持 Dict 和 AIPMessage）"""
        return await self._session_manager.send_to_device(device_id, message)

    async def broadcast_message(self, message: Union[Dict[str, Any], Any], exclude_devices: Optional[List[str]] = None) -> Dict[str, bool]:
        return await self._session_manager.broadcast(message, exclude_devices)

    # === 共享数据 API ===

    def set_shared_data(self, key: str, value: Any):
        self._shared_data.set(key, value)

    def get_shared_data(self, key: str) -> Optional[Any]:
        return self._shared_data.get(key)

    # === 设备状态 ===

    def update_device_state(self, device_id: str, state: Dict):
        """更新设备状态（存到共享数据）"""
        from datetime import datetime
        self._shared_data.set(f"device_state:{device_id}", {
            **state,
            "updated_at": datetime.now().isoformat(),
        })

    def get_device_state(self, device_id: str) -> Optional[Dict]:
        return self._shared_data.get(f"device_state:{device_id}")

    # === 协议 API (AIP v3.0) ===

    async def handle_device_message(self, session_id: str, raw_data: Union[str, dict]) -> Optional[Dict]:
        """处理设备消息（自动兼容 AIP v1/v2/v3）

        使用 galaxy_gateway.protocol.compat.parse_message_compat 解析消息，
        自动检测并规范化协议版本到 AIP v3.0。
        """
        return await self._session_manager.handle_message(session_id, raw_data)

    def get_protocol_info(self) -> Dict[str, Any]:
        """获取协议版本信息"""
        try:
            from galaxy_gateway.protocol.aip_v3 import MessageType as AIPMessageType
            msg_type_count = len(AIPMessageType)
        except ImportError:
            msg_type_count = 0
        return {
            "canonical_version": "3.0",
            "supported_versions": ["1.0", "2.0", "3.0"],
            "message_types": msg_type_count,
            "compat_layer": "galaxy_gateway.protocol.compat",
        }

    # === 状态与生命周期 ===

    def get_status(self) -> Dict[str, Any]:
        session_stats = self._session_manager.get_statistics()
        return {
            "type": "unified_coordinator",
            "session_manager": session_stats,
            "fault_tolerance_available": self._fault_tolerance is not None,
            "shared_data_keys": len(self._shared_data.data),
        }

    async def cleanup(self):
        """清理过期会话"""
        removed = await self._session_manager.cleanup_stale()
        if removed > 0:
            logger.info(f"清理了 {removed} 个过期会话")
        return removed


# ============================================================================
# 单例
# ============================================================================

def get_unified_coordinator() -> UnifiedDeviceCoordinator:
    """获取统一设备协调器单例"""
    if UnifiedDeviceCoordinator._instance is None:
        UnifiedDeviceCoordinator._instance = UnifiedDeviceCoordinator()
    return UnifiedDeviceCoordinator._instance
