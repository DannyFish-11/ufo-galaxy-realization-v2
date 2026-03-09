"""
Galaxy v5.0 - Device Protocol Module
AIP v3.0 Protocol Implementation (migrated from v2.0)

This module provides the device communication protocol for Galaxy's multi-device
coordination system. It uses AIP v3.0 (JSON/Pydantic) as the primary format,
with backward-compatible v2.0 binary serialization for legacy clients.

All new code should use:
  - to_json() / from_json() for serialization
  - AIPMessage (Pydantic BaseModel from aip_v3)
  - MessageType (from aip_v3) for message types

Legacy v2.0 binary support (to_bytes/from_bytes) is retained for wire
compatibility but internally bridges through v3.0.

Author: Galaxy Team
Version: 5.0.0 (AIP v3.0)
"""

import json
import struct
import hashlib
import time
import logging
import asyncio
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List, Callable, Union
from enum import Enum, IntEnum
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)

# =============================================================================
# AIP v3.0 MessageType — 从协议层导入，作为本模块的标准消息类型
# =============================================================================

from galaxy_gateway.protocol.aip_v3 import (
    MessageType as V3MessageType,
    AIPDeviceType,
    DevicePlatform,
    DeviceCapability as V3DeviceCapability,
    AIPMessage as V3AIPMessage,
    parse_message as v3_parse_message,
    validate_message as v3_validate_message,
    create_register_message,
    create_heartbeat_message,
    create_task_message,
    create_error_message,
)
from core.device_types import DeviceType, DeviceStatus


# =============================================================================
# Legacy v2.0 MessageType — 保留 IntEnum 以支持 v2 二进制协议的序列化/反序列化
# =============================================================================

class LegacyMessageType(IntEnum):
    """AIP v2.0 Message Types (binary protocol only, use V3MessageType for new code)"""
    DEVICE_REGISTER = 0x01
    DEVICE_UNREGISTER = 0x02
    DEVICE_HEARTBEAT = 0x03
    DEVICE_STATUS = 0x04
    DEVICE_DISCOVER = 0x05
    TASK_SUBMIT = 0x10
    TASK_ASSIGN = 0x11
    TASK_STATUS = 0x12
    TASK_RESULT = 0x13
    TASK_CANCEL = 0x14
    COORD_SYNC = 0x20
    COORD_BROADCAST = 0x21
    COORD_ROUTING = 0x22
    COORD_ELECTION = 0x23
    DATA_REQUEST = 0x30
    DATA_RESPONSE = 0x31
    DATA_STREAM = 0x32
    CONTROL_COMMAND = 0x40
    CONTROL_CONFIG = 0x41
    CONTROL_SHUTDOWN = 0x42
    ERROR_REPORT = 0x50
    RECOVERY_REQUEST = 0x51
    RECOVERY_RESPONSE = 0x52
    ANDROID_SCREEN = 0x60
    ANDROID_INPUT = 0x61
    ANDROID_INSTALL = 0x62
    WAKE_EVENT = 0x70
    WAKE_ROUTE_RESULT = 0x71
    SESSION_MIGRATE = 0x72
    SESSION_RESTORE = 0x73


# v2 int → v3 string 映射表
_V2_TO_V3_MSG_TYPE: Dict[int, str] = {
    0x01: "device_register",
    0x02: "device_unregister",
    0x03: "device_heartbeat",
    0x04: "device_status",
    0x05: "device_capabilities",
    0x10: "task_submit",
    0x11: "task_assign",
    0x12: "task_status",
    0x13: "task_result",
    0x14: "task_cancel",
    0x20: "coord_sync",
    0x21: "coord_broadcast",
    0x40: "command",
    0x41: "command",
    0x42: "command",
    0x50: "error",
    0x51: "error_recovery",
    0x60: "screen_capture",
    0x61: "gui_input",
    0x62: "command",
    0x70: "wake_event",
    0x72: "session_migrate",
}

# v3 string → v2 int 反向映射（取第一个匹配）
_V3_TO_V2_MSG_TYPE: Dict[str, int] = {}
for _v2_int, _v3_str in _V2_TO_V3_MSG_TYPE.items():
    if _v3_str not in _V3_TO_V2_MSG_TYPE:
        _V3_TO_V2_MSG_TYPE[_v3_str] = _v2_int

# v2 DeviceType integer mapping（向后兼容）
_V2_DEVICE_TYPE_INT: Dict[str, int] = {
    DeviceType.UNKNOWN.value: 0,
    DeviceType.LINUX.value: 1,
    DeviceType.ANDROID.value: 3,
    DeviceType.EMBEDDED.value: 6,
    DeviceType.CUSTOM.value: 7,
}

_V2_DEVICE_STATUS_INT: Dict[str, int] = {
    DeviceStatus.OFFLINE.value: 0,
    DeviceStatus.ONLINE.value: 1,
    DeviceStatus.BUSY.value: 2,
    DeviceStatus.ERROR.value: 3,
    DeviceStatus.UNKNOWN.value: 5,
}

# =============================================================================
# 公开 MessageType — 使用 V3MessageType 作为标准
# =============================================================================

# 新代码应使用 V3MessageType (str enum with 48+ types)
# 向后兼容: MessageType 现在指向 V3MessageType
MessageType = V3MessageType


# =============================================================================
# Task & Device data classes（保留 dataclass 接口以兼容现有代码）
# =============================================================================

class TaskPriority(IntEnum):
    """Task Priority Levels"""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class TaskState(IntEnum):
    """Task Execution States"""
    PENDING = 0
    SCHEDULED = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5
    TIMEOUT = 6


class ErrorCode(IntEnum):
    """AIP Error Codes"""
    SUCCESS = 0
    INVALID_MESSAGE = 1
    DEVICE_NOT_FOUND = 2
    DEVICE_OFFLINE = 3
    TASK_NOT_FOUND = 4
    INSUFFICIENT_RESOURCES = 5
    PERMISSION_DENIED = 6
    TIMEOUT = 7
    PROTOCOL_ERROR = 8
    INTERNAL_ERROR = 9
    NOT_IMPLEMENTED = 10


@dataclass
class DeviceCapabilities:
    """Device Capability Information"""
    cpu_cores: int = 1
    memory_gb: float = 1.0
    storage_gb: float = 10.0
    gpu_available: bool = False
    gpu_memory_gb: float = 0.0
    network_mbps: float = 100.0
    supports_screen: bool = False
    supports_audio: bool = False
    supports_camera: bool = False
    custom_features: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeviceCapabilities':
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class DeviceInfo:
    """Device Information Structure"""
    device_id: str
    device_type: DeviceType
    device_name: str
    device_model: str
    os_version: str
    app_version: str
    ip_address: str
    port: int
    capabilities: DeviceCapabilities
    tags: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    status: DeviceStatus = DeviceStatus.ONLINE

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['device_type'] = self.device_type.value
        data['capabilities'] = self.capabilities.to_dict()
        data['status'] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeviceInfo':
        data = data.copy()
        raw_dt = data.get('device_type', 'unknown')
        if isinstance(raw_dt, int):
            _int_to_dt = {v: k for k, v in _V2_DEVICE_TYPE_INT.items()}
            raw_dt = _int_to_dt.get(raw_dt, DeviceType.UNKNOWN.value)
        data['device_type'] = DeviceType(raw_dt)
        data['capabilities'] = DeviceCapabilities.from_dict(
            data.get('capabilities', {})
        )
        raw_st = data.get('status', 'online')
        if isinstance(raw_st, int):
            _int_to_st = {v: k for k, v in _V2_DEVICE_STATUS_INT.items()}
            raw_st = _int_to_st.get(raw_st, DeviceStatus.UNKNOWN.value)
        data['status'] = DeviceStatus(raw_st)
        return cls(**data)


@dataclass
class TaskInfo:
    """Task Information Structure"""
    task_id: str
    task_type: str
    priority: TaskPriority
    payload: Dict[str, Any]
    assigned_device: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    scheduled_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    state: TaskState = TaskState.PENDING
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: float = 300.0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['priority'] = self.priority.value
        data['state'] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskInfo':
        data = data.copy()
        data['priority'] = TaskPriority(data.get('priority', 2))
        data['state'] = TaskState(data.get('state', 0))
        return cls(**data)


# =============================================================================
# AIPMessage — v3.0 Pydantic 消息 + v2.0 二进制兼容层
# =============================================================================

class AIPMessage(V3AIPMessage):
    """
    AIP v3.0 消息（继承自 galaxy_gateway.protocol.aip_v3.AIPMessage）

    新增 v2.0 二进制兼容方法:
      - to_bytes() / from_bytes() — legacy 二进制序列化
      - to_json() / from_json() — 推荐的 JSON 序列化
    """

    # v2.0 protocol constants
    _V2_MAGIC: int = 0x55464F47  # 'UFOG'
    _V2_VERSION: int = 0x0200
    _V2_HEADER_SIZE: int = 16
    _V2_FOOTER_SIZE: int = 8

    def to_json(self) -> str:
        """序列化为 JSON 字符串（推荐接口）"""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: Union[str, dict]) -> 'AIPMessage':
        """从 JSON 反序列化（推荐接口）"""
        if isinstance(data, str):
            data = json.loads(data)
        return cls.model_validate(data)

    def to_bytes(self) -> bytes:
        """
        Legacy v2.0 二进制序列化

        Format: Header(16) + JSON payload + Footer(8)
        """
        v3_type_str = self.type.value if isinstance(self.type, Enum) else str(self.type)
        v2_msg_type = _V3_TO_V2_MSG_TYPE.get(v3_type_str, 0x40)

        full_payload = {
            'payload': self.payload,
            'timestamp': self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp),
            'source_device': self.device_id,
            'target_device': None,
            'correlation_id': self.correlation_id,
        }
        payload_bytes = json.dumps(full_payload, ensure_ascii=False).encode('utf-8')
        payload_length = len(payload_bytes)

        header = struct.pack(
            '>IHHII',
            self._V2_MAGIC,
            self._V2_VERSION,
            v2_msg_type,
            payload_length,
            0
        )

        checksum = hashlib.crc32(payload_bytes) & 0xFFFFFFFF
        footer = struct.pack('>II', checksum, 0)

        return header + payload_bytes + footer

    @classmethod
    def from_bytes(cls, data: bytes) -> 'AIPMessage':
        """
        Legacy v2.0 二进制反序列化

        Parses the v2 binary wire format and returns a v3 AIPMessage.
        """
        if len(data) < cls._V2_HEADER_SIZE + cls._V2_FOOTER_SIZE:
            raise ProtocolError("Message too short")

        magic, version, msg_type_val, payload_length, sequence = struct.unpack(
            '>IHHII', data[:cls._V2_HEADER_SIZE]
        )

        if magic != cls._V2_MAGIC:
            raise ProtocolError(f"Invalid magic: {hex(magic)}")

        if version != cls._V2_VERSION:
            raise ProtocolError(f"Unsupported version: {hex(version)}")

        payload_start = cls._V2_HEADER_SIZE
        payload_end = payload_start + payload_length
        payload_bytes = data[payload_start:payload_end]

        stored_checksum = struct.unpack('>I', data[payload_end:payload_end + 4])[0]
        calculated_checksum = hashlib.crc32(payload_bytes) & 0xFFFFFFFF
        if stored_checksum != calculated_checksum:
            raise ProtocolError("Checksum mismatch")

        full_payload = json.loads(payload_bytes.decode('utf-8'))

        v3_type_str = _V2_TO_V3_MSG_TYPE.get(msg_type_val, "command")
        try:
            v3_type = V3MessageType(v3_type_str)
        except ValueError:
            v3_type = V3MessageType.COMMAND

        source = full_payload.get('source_device', '')

        return cls(
            type=v3_type,
            device_id=source or "unknown",
            payload=full_payload.get('payload', {}),
            correlation_id=full_payload.get('correlation_id'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()


class ProtocolError(Exception):
    """Protocol-related error"""
    pass


# =============================================================================
# Protocol Validator — v3.0 JSON 消息验证
# =============================================================================

class ProtocolValidator:
    """AIP v3.0 Protocol Validator"""

    @staticmethod
    def validate_message(message: AIPMessage) -> tuple:
        """验证 AIP 消息"""
        if not message.device_id:
            return False, "Missing device_id"
        if not message.type:
            return False, "Missing message type"

        validators = {
            V3MessageType.DEVICE_REGISTER: ProtocolValidator._validate_register,
            V3MessageType.TASK_SUBMIT: ProtocolValidator._validate_task_submit,
            V3MessageType.DEVICE_HEARTBEAT: ProtocolValidator._validate_heartbeat,
        }

        validator = validators.get(message.type)
        if validator:
            return validator(message.payload)

        return True, None

    @staticmethod
    def _validate_register(payload: Dict[str, Any]) -> tuple:
        """验证设备注册 payload"""
        required = ['device_id', 'device_type', 'device_name']
        for f in required:
            if f not in payload:
                return False, f"Missing required field: {f}"
        return True, None

    @staticmethod
    def _validate_task_submit(payload: Dict[str, Any]) -> tuple:
        """验证任务提交 payload"""
        required = ['task_id', 'task_type', 'payload']
        for f in required:
            if f not in payload:
                return False, f"Missing required field: {f}"
        return True, None

    @staticmethod
    def _validate_heartbeat(payload: Dict[str, Any]) -> tuple:
        """验证心跳 payload"""
        if 'device_id' not in payload:
            return False, "Missing required field: device_id"
        return True, None


# =============================================================================
# Message Builder — 构建 AIP v3.0 消息
# =============================================================================

class MessageBuilder:
    """Builder for AIP Messages (v3.0)"""

    _sequence_counter: int = 0
    _lock = asyncio.Lock()

    @classmethod
    async def get_next_sequence(cls) -> int:
        """Get next sequence number"""
        async with cls._lock:
            cls._sequence_counter = (cls._sequence_counter + 1) % 0xFFFFFFFF
            return cls._sequence_counter

    @classmethod
    async def build_register(
        cls,
        device_info: DeviceInfo,
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build device registration message"""
        return AIPMessage(
            type=V3MessageType.DEVICE_REGISTER,
            device_id=source_device or device_info.device_id,
            payload=device_info.to_dict(),
        )

    @classmethod
    async def build_heartbeat(
        cls,
        device_id: str,
        status: DeviceStatus,
        metrics: Optional[Dict[str, Any]] = None,
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build heartbeat message"""
        payload = {
            'device_id': device_id,
            'status': status.value,
            'timestamp': time.time(),
            'metrics': metrics or {}
        }
        return AIPMessage(
            type=V3MessageType.DEVICE_HEARTBEAT,
            device_id=source_device or device_id,
            payload=payload,
        )

    @classmethod
    async def build_task_submit(
        cls,
        task_info: TaskInfo,
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build task submission message"""
        return AIPMessage(
            type=V3MessageType.TASK_SUBMIT,
            device_id=source_device or "system",
            task_id=task_info.task_id,
            payload=task_info.to_dict(),
        )

    @classmethod
    async def build_task_result(
        cls,
        task_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build task result message"""
        payload = {
            'task_id': task_id,
            'success': success,
            'result': result,
            'error_message': error_message,
            'timestamp': time.time()
        }
        return AIPMessage(
            type=V3MessageType.TASK_RESULT,
            device_id=source_device or "system",
            task_id=task_id,
            payload=payload,
        )

    @classmethod
    async def build_error(
        cls,
        error_code: ErrorCode,
        error_message: str,
        original_msg_type: Optional[V3MessageType] = None,
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build error message"""
        payload = {
            'error_code': error_code.value,
            'error_code_name': error_code.name,
            'error_message': error_message,
            'original_msg_type': original_msg_type.value if original_msg_type else None
        }
        return AIPMessage(
            type=V3MessageType.ERROR,
            device_id=source_device or "system",
            error=error_message,
            payload=payload,
        )

    @classmethod
    async def build_broadcast(
        cls,
        broadcast_type: str,
        data: Dict[str, Any],
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build broadcast message"""
        payload = {
            'broadcast_type': broadcast_type,
            'data': data,
            'timestamp': time.time()
        }
        return AIPMessage(
            type=V3MessageType.COORD_BROADCAST,
            device_id=source_device or "system",
            payload=payload,
        )


# =============================================================================
# Protocol Handler & Router — 抽象消息处理
# =============================================================================

class ProtocolHandler(ABC):
    """Abstract base class for protocol handlers"""

    @abstractmethod
    async def handle_message(self, message: AIPMessage) -> Optional[AIPMessage]:
        """Handle incoming message"""
        pass

    @abstractmethod
    async def handle_error(self, error: Exception, message: Optional[AIPMessage] = None) -> AIPMessage:
        """Handle protocol error"""
        pass


class MessageRouter:
    """Message routing system (v3.0)"""

    def __init__(self):
        self.handlers: Dict[V3MessageType, List[ProtocolHandler]] = {}
        self.default_handler: Optional[ProtocolHandler] = None
        self.middleware: List[Callable[[AIPMessage], AIPMessage]] = []

    def register_handler(
        self,
        msg_type: V3MessageType,
        handler: ProtocolHandler
    ) -> None:
        """Register handler for message type"""
        if msg_type not in self.handlers:
            self.handlers[msg_type] = []
        self.handlers[msg_type].append(handler)
        logger.info(f"Registered handler for {msg_type.value}")

    def set_default_handler(self, handler: ProtocolHandler) -> None:
        """Set default handler for unhandled message types"""
        self.default_handler = handler

    def add_middleware(self, middleware: Callable[[AIPMessage], AIPMessage]) -> None:
        """Add middleware to message processing pipeline"""
        self.middleware.append(middleware)

    async def route(self, message: AIPMessage) -> List[AIPMessage]:
        """Route message to appropriate handlers"""
        for mw in self.middleware:
            message = mw(message)

        handlers = self.handlers.get(message.type, [])
        if not handlers and self.default_handler:
            handlers = [self.default_handler]

        responses = []
        for handler in handlers:
            try:
                response = await handler.handle_message(message)
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Handler error for {message.type}: {e}")
                error_response = await handler.handle_error(e, message)
                responses.append(error_response)

        return responses


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # v3.0 types (primary)
    'MessageType',
    'V3MessageType',
    'AIPMessage',
    'V3AIPMessage',
    # Data structures
    'DeviceType',
    'DeviceStatus',
    'TaskPriority',
    'TaskState',
    'ErrorCode',
    'DeviceCapabilities',
    'DeviceInfo',
    'TaskInfo',
    # Protocol utilities
    'ProtocolError',
    'ProtocolValidator',
    'MessageBuilder',
    'ProtocolHandler',
    'MessageRouter',
    # Legacy v2.0 (for binary wire compat only)
    'LegacyMessageType',
]
