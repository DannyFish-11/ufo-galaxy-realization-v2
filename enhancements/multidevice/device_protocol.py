"""
UFO Galaxy v5.0 - Device Protocol Module
AIP v2.0 Protocol Implementation

This module defines the AIP (Advanced Inter-device Protocol) v2.0 message format,
protocol buffer schemas, and message serialization/deserialization for device communication.

Features:
- Protocol buffer message definitions
- Message serialization/deserialization
- Protocol validation
- Cross-platform message handling
- Support for 500+ TPS

Author: UFO Galaxy Team
Version: 5.0.0
"""

import json
import struct
import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List, Callable, Union, Type
from enum import Enum, IntEnum
from abc import ABC, abstractmethod
import logging
import asyncio
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MessageType(IntEnum):
    """AIP v2.0 Message Types"""
    # Device Management
    DEVICE_REGISTER = 0x01
    DEVICE_UNREGISTER = 0x02
    DEVICE_HEARTBEAT = 0x03
    DEVICE_STATUS = 0x04
    DEVICE_DISCOVER = 0x05
    
    # Task Management
    TASK_SUBMIT = 0x10
    TASK_ASSIGN = 0x11
    TASK_STATUS = 0x12
    TASK_RESULT = 0x13
    TASK_CANCEL = 0x14
    
    # Coordination
    COORD_SYNC = 0x20
    COORD_BROADCAST = 0x21
    COORD_ROUTING = 0x22
    COORD_ELECTION = 0x23
    
    # Data Transfer
    DATA_REQUEST = 0x30
    DATA_RESPONSE = 0x31
    DATA_STREAM = 0x32
    
    # Control
    CONTROL_COMMAND = 0x40
    CONTROL_CONFIG = 0x41
    CONTROL_SHUTDOWN = 0x42
    
    # Error & Recovery
    ERROR_REPORT = 0x50
    RECOVERY_REQUEST = 0x51
    RECOVERY_RESPONSE = 0x52
    
    # Android Specific
    ANDROID_SCREEN = 0x60
    ANDROID_INPUT = 0x61
    ANDROID_INSTALL = 0x62


class DeviceType(IntEnum):
    """Device Types supported by UFO Galaxy"""
    UNKNOWN = 0
    LINUX_SERVER = 1
    LINUX_DESKTOP = 2
    ANDROID_PHONE = 3
    ANDROID_TABLET = 4
    ANDROID_TV = 5
    EMBEDDED = 6
    CONTAINER = 7
    VIRTUAL = 8


class DeviceStatus(IntEnum):
    """Device Status States"""
    OFFLINE = 0
    ONLINE = 1
    BUSY = 2
    ERROR = 3
    MAINTENANCE = 4
    DEGRADED = 5


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
    """AIP v2.0 Error Codes"""
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
        return cls(**data)


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
        data['device_type'] = DeviceType(data.get('device_type', 0))
        data['capabilities'] = DeviceCapabilities.from_dict(
            data.get('capabilities', {})
        )
        data['status'] = DeviceStatus(data.get('status', 1))
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


@dataclass
class AIPMessage:
    """
    AIP v2.0 Message Structure
    
    Format:
    - Header (16 bytes):
        - Magic (4 bytes): 0x55464F47 ('UFOG')
        - Version (2 bytes): 0x0200
        - Message Type (2 bytes)
        - Payload Length (4 bytes)
        - Sequence Number (4 bytes)
    - Body (variable): JSON payload
    - Footer (8 bytes):
        - Checksum (4 bytes)
        - Reserved (4 bytes)
    """
    msg_type: MessageType
    payload: Dict[str, Any]
    sequence: int = 0
    timestamp: float = field(default_factory=time.time)
    source_device: Optional[str] = None
    target_device: Optional[str] = None
    correlation_id: Optional[str] = None
    
    # Protocol constants
    MAGIC: int = 0x55464F47  # 'UFOG' in ASCII
    VERSION: int = 0x0200    # v2.0
    HEADER_SIZE: int = 16
    FOOTER_SIZE: int = 8
    
    def to_bytes(self) -> bytes:
        """Serialize message to bytes"""
        # Build payload with metadata
        full_payload = {
            'payload': self.payload,
            'timestamp': self.timestamp,
            'source_device': self.source_device,
            'target_device': self.target_device,
            'correlation_id': self.correlation_id
        }
        
        # Serialize payload to JSON
        payload_bytes = json.dumps(full_payload, ensure_ascii=False).encode('utf-8')
        payload_length = len(payload_bytes)
        
        # Build header
        header = struct.pack(
            '>IHHII',
            self.MAGIC,
            self.VERSION,
            self.msg_type.value,
            payload_length,
            self.sequence
        )
        
        # Calculate checksum
        checksum = self._calculate_checksum(payload_bytes)
        
        # Build footer
        footer = struct.pack('>II', checksum, 0)
        
        return header + payload_bytes + footer
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'AIPMessage':
        """Deserialize message from bytes"""
        if len(data) < cls.HEADER_SIZE + cls.FOOTER_SIZE:
            raise ProtocolError("Message too short")
        
        # Parse header
        magic, version, msg_type_val, payload_length, sequence = struct.unpack(
            '>IHHII', data[:cls.HEADER_SIZE]
        )
        
        # Validate magic
        if magic != cls.MAGIC:
            raise ProtocolError(f"Invalid magic: {hex(magic)}")
        
        # Validate version
        if version != cls.VERSION:
            raise ProtocolError(f"Unsupported version: {hex(version)}")
        
        # Extract payload
        payload_start = cls.HEADER_SIZE
        payload_end = payload_start + payload_length
        payload_bytes = data[payload_start:payload_end]
        
        # Validate checksum
        stored_checksum = struct.unpack('>I', data[payload_end:payload_end+4])[0]
        calculated_checksum = cls._calculate_checksum(payload_bytes)
        if stored_checksum != calculated_checksum:
            raise ProtocolError("Checksum mismatch")
        
        # Parse payload
        full_payload = json.loads(payload_bytes.decode('utf-8'))
        
        return cls(
            msg_type=MessageType(msg_type_val),
            payload=full_payload.get('payload', {}),
            sequence=sequence,
            timestamp=full_payload.get('timestamp', time.time()),
            source_device=full_payload.get('source_device'),
            target_device=full_payload.get('target_device'),
            correlation_id=full_payload.get('correlation_id')
        )
    
    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        """Calculate CRC32 checksum"""
        return hashlib.crc32(data) & 0xFFFFFFFF
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'msg_type': self.msg_type.value,
            'msg_type_name': self.msg_type.name,
            'payload': self.payload,
            'sequence': self.sequence,
            'timestamp': self.timestamp,
            'source_device': self.source_device,
            'target_device': self.target_device,
            'correlation_id': self.correlation_id
        }


class ProtocolError(Exception):
    """Protocol-related error"""
    pass


class ProtocolValidator:
    """AIP v2.0 Protocol Validator"""
    
    @staticmethod
    def validate_message(message: AIPMessage) -> tuple[bool, Optional[str]]:
        """Validate AIP message"""
        # Check message type
        if not isinstance(message.msg_type, MessageType):
            return False, f"Invalid message type: {message.msg_type}"
        
        # Check payload
        if not isinstance(message.payload, dict):
            return False, "Payload must be a dictionary"
        
        # Validate based on message type
        validators = {
            MessageType.DEVICE_REGISTER: ProtocolValidator._validate_register,
            MessageType.TASK_SUBMIT: ProtocolValidator._validate_task_submit,
            MessageType.DEVICE_HEARTBEAT: ProtocolValidator._validate_heartbeat,
        }
        
        validator = validators.get(message.msg_type)
        if validator:
            return validator(message.payload)
        
        return True, None
    
    @staticmethod
    def _validate_register(payload: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate device registration payload"""
        required = ['device_id', 'device_type', 'device_name']
        for field in required:
            if field not in payload:
                return False, f"Missing required field: {field}"
        return True, None
    
    @staticmethod
    def _validate_task_submit(payload: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate task submission payload"""
        required = ['task_id', 'task_type', 'payload']
        for field in required:
            if field not in payload:
                return False, f"Missing required field: {field}"
        return True, None
    
    @staticmethod
    def _validate_heartbeat(payload: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate heartbeat payload"""
        if 'device_id' not in payload:
            return False, "Missing required field: device_id"
        return True, None


class MessageBuilder:
    """Builder for AIP v2.0 Messages"""
    
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
            msg_type=MessageType.DEVICE_REGISTER,
            payload=device_info.to_dict(),
            sequence=await cls.get_next_sequence(),
            source_device=source_device
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
            msg_type=MessageType.DEVICE_HEARTBEAT,
            payload=payload,
            sequence=await cls.get_next_sequence(),
            source_device=source_device
        )
    
    @classmethod
    async def build_task_submit(
        cls,
        task_info: TaskInfo,
        source_device: Optional[str] = None
    ) -> AIPMessage:
        """Build task submission message"""
        return AIPMessage(
            msg_type=MessageType.TASK_SUBMIT,
            payload=task_info.to_dict(),
            sequence=await cls.get_next_sequence(),
            source_device=source_device
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
            msg_type=MessageType.TASK_RESULT,
            payload=payload,
            sequence=await cls.get_next_sequence(),
            source_device=source_device
        )
    
    @classmethod
    async def build_error(
        cls,
        error_code: ErrorCode,
        error_message: str,
        original_msg_type: Optional[MessageType] = None,
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
            msg_type=MessageType.ERROR_REPORT,
            payload=payload,
            sequence=await cls.get_next_sequence(),
            source_device=source_device
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
            msg_type=MessageType.COORD_BROADCAST,
            payload=payload,
            sequence=await cls.get_next_sequence(),
            source_device=source_device
        )


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
    """Message routing system"""
    
    def __init__(self):
        self.handlers: Dict[MessageType, List[ProtocolHandler]] = {}
        self.default_handler: Optional[ProtocolHandler] = None
        self.middleware: List[Callable[[AIPMessage], AIPMessage]] = []
    
    def register_handler(
        self,
        msg_type: MessageType,
        handler: ProtocolHandler
    ) -> None:
        """Register handler for message type"""
        if msg_type not in self.handlers:
            self.handlers[msg_type] = []
        self.handlers[msg_type].append(handler)
        logger.info(f"Registered handler for {msg_type.name}")
    
    def set_default_handler(self, handler: ProtocolHandler) -> None:
        """Set default handler for unhandled message types"""
        self.default_handler = handler
    
    def add_middleware(self, middleware: Callable[[AIPMessage], AIPMessage]) -> None:
        """Add middleware to message processing pipeline"""
        self.middleware.append(middleware)
    
    async def route(self, message: AIPMessage) -> List[AIPMessage]:
        """Route message to appropriate handlers"""
        # Apply middleware
        for mw in self.middleware:
            message = mw(message)
        
        # Get handlers
        handlers = self.handlers.get(message.msg_type, [])
        if not handlers and self.default_handler:
            handlers = [self.default_handler]
        
        # Process message
        responses = []
        for handler in handlers:
            try:
                response = await handler.handle_message(message)
                if response:
                    responses.append(response)
            except Exception as e:
                logger.error(f"Handler error: {e}")
                error_response = await handler.handle_error(e, message)
                responses.append(error_response)
        
        return responses


# Protocol buffer schema definitions (as Python code for reference)
PROTOBUF_SCHEMA = """
syntax = "proto3";

package ufo_galaxy.aip.v2;

// Device message
message Device {
    string device_id = 1;
    DeviceType device_type = 2;
    string device_name = 3;
    string device_model = 4;
    string os_version = 5;
    string app_version = 6;
    string ip_address = 7;
    int32 port = 8;
    DeviceCapabilities capabilities = 9;
    repeated string tags = 10;
    repeated string groups = 11;
    DeviceStatus status = 12;
    double registered_at = 13;
    double last_heartbeat = 14;
}

enum DeviceType {
    UNKNOWN = 0;
    LINUX_SERVER = 1;
    LINUX_DESKTOP = 2;
    ANDROID_PHONE = 3;
    ANDROID_TABLET = 4;
    ANDROID_TV = 5;
    EMBEDDED = 6;
    CONTAINER = 7;
    VIRTUAL = 8;
}

enum DeviceStatus {
    OFFLINE = 0;
    ONLINE = 1;
    BUSY = 2;
    ERROR = 3;
    MAINTENANCE = 4;
    DEGRADED = 5;
}

message DeviceCapabilities {
    int32 cpu_cores = 1;
    double memory_gb = 2;
    double storage_gb = 3;
    bool gpu_available = 4;
    double gpu_memory_gb = 5;
    double network_mbps = 6;
    bool supports_screen = 7;
    bool supports_audio = 8;
    bool supports_camera = 9;
    repeated string custom_features = 10;
}

// Task message
message Task {
    string task_id = 1;
    string task_type = 2;
    TaskPriority priority = 3;
    bytes payload = 4;
    string assigned_device = 5;
    double created_at = 6;
    double scheduled_at = 7;
    double started_at = 8;
    double completed_at = 9;
    TaskState state = 10;
    bytes result = 11;
    string error_message = 12;
    int32 retry_count = 13;
    int32 max_retries = 14;
    double timeout_seconds = 15;
}

enum TaskPriority {
    CRITICAL = 0;
    HIGH = 1;
    NORMAL = 2;
    LOW = 3;
    BACKGROUND = 4;
}

enum TaskState {
    PENDING = 0;
    SCHEDULED = 1;
    RUNNING = 2;
    COMPLETED = 3;
    FAILED = 4;
    CANCELLED = 5;
    TIMEOUT = 6;
}

// AIP Message wrapper
message AIPMessage {
    MessageType msg_type = 1;
    bytes payload = 2;
    uint32 sequence = 3;
    double timestamp = 4;
    string source_device = 5;
    string target_device = 6;
    string correlation_id = 7;
}

enum MessageType {
    DEVICE_REGISTER = 1;
    DEVICE_UNREGISTER = 2;
    DEVICE_HEARTBEAT = 3;
    DEVICE_STATUS = 4;
    DEVICE_DISCOVER = 5;
    TASK_SUBMIT = 16;
    TASK_ASSIGN = 17;
    TASK_STATUS = 18;
    TASK_RESULT = 19;
    TASK_CANCEL = 20;
    COORD_SYNC = 32;
    COORD_BROADCAST = 33;
    COORD_ROUTING = 34;
    COORD_ELECTION = 35;
    DATA_REQUEST = 48;
    DATA_RESPONSE = 49;
    DATA_STREAM = 50;
    CONTROL_COMMAND = 64;
    CONTROL_CONFIG = 65;
    CONTROL_SHUTDOWN = 66;
    ERROR_REPORT = 80;
    RECOVERY_REQUEST = 81;
    RECOVERY_RESPONSE = 82;
    ANDROID_SCREEN = 96;
    ANDROID_INPUT = 97;
    ANDROID_INSTALL = 98;
}
"""


# Export all public classes and functions
__all__ = [
    'MessageType',
    'DeviceType',
    'DeviceStatus',
    'TaskPriority',
    'TaskState',
    'ErrorCode',
    'DeviceCapabilities',
    'DeviceInfo',
    'TaskInfo',
    'AIPMessage',
    'ProtocolError',
    'ProtocolValidator',
    'MessageBuilder',
    'ProtocolHandler',
    'MessageRouter',
    'PROTOBUF_SCHEMA'
]
