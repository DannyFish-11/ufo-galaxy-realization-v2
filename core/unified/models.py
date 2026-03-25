"""
core/unified/models.py
======================
Galaxy 系统统一强类型 Pydantic 数据模型。

所有统一模块必须使用此文件中定义的模型进行数据流转，禁止弱类型 dict 传递。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# 枚举定义
# ============================================================================


class UnifiedDeviceType(str, Enum):
    """设备类型（统一大类，对齐 core.device_types.DeviceType）"""

    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    BROWSER = "browser"
    CLOUD = "cloud"
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    ROBOT = "robot"
    CAMERA = "camera"
    IOT = "iot"
    UNKNOWN = "unknown"


class UnifiedDeviceStatus(str, Enum):
    """设备在线状态"""

    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    INITIALIZING = "initializing"
    DISCONNECTED = "disconnected"


class UnifiedConnectionState(str, Enum):
    """连接状态"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    CLOSED = "closed"


class UnifiedMessageType(str, Enum):
    """消息类型"""

    COMMAND = "command"
    RESPONSE = "response"
    HEARTBEAT = "heartbeat"
    ACK = "ack"
    EVENT = "event"
    ERROR = "error"


# ============================================================================
# 设备模型
# ============================================================================


class UnifiedDevice(BaseModel):
    """统一设备信息模型"""

    device_id: str
    device_name: str = "unknown"
    device_type: UnifiedDeviceType = UnifiedDeviceType.UNKNOWN
    status: UnifiedDeviceStatus = UnifiedDeviceStatus.OFFLINE
    ip_address: Optional[str] = None
    port: Optional[int] = None
    capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: Optional[datetime] = None
    # source 字段标记设备信息来源，便于调试
    source: str = "unknown"
    # state_version 单调递增版本号，每次状态写入后自增；用于冲突检测（prefer-latest 策略）
    state_version: int = 0
    # updated_at 最后一次状态更新时间戳（UTC），用于时间戳冲突策略
    updated_at: Optional[datetime] = None

    model_config = {"use_enum_values": True}

    def is_online(self) -> bool:
        return self.status in (UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value)


# ============================================================================
# 连接模型
# ============================================================================


class UnifiedConnectionInfo(BaseModel):
    """统一连接信息模型"""

    connection_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    device_id: str
    state: UnifiedConnectionState = UnifiedConnectionState.DISCONNECTED
    connected_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    # last_seen: float epoch timestamp updated on every heartbeat/message
    last_seen: float = 0.0
    # routable: True when the device is reachable via the active transport
    routable: bool = False
    retry_count: int = 0
    last_error: Optional[str] = None
    total_reconnects: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


# ============================================================================
# 消息模型
# ============================================================================


class UnifiedMessage(BaseModel):
    """统一消息模型"""

    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: UnifiedMessageType = UnifiedMessageType.COMMAND
    device_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"use_enum_values": True}


# ============================================================================
# 命令/响应模型
# ============================================================================


class DeviceCommand(BaseModel):
    """发往设备的命令"""

    command_id: str = Field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:12]}")
    device_id: str
    command: str
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: float = 15.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DeviceCommandResult(BaseModel):
    """设备命令执行结果"""

    command_id: str
    device_id: str
    success: bool
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    executed_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# LLM 路由模型
# ============================================================================


class LLMTaskType(str, Enum):
    """LLM 任务类型"""

    REASONING = "reasoning"
    FAST_RESPONSE = "fast_response"
    CODING = "coding"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    PLANNING = "planning"
    AGENT_CONTROL = "agent_control"
    GENERAL = "general"


class LLMRequest(BaseModel):
    """统一 LLM 请求模型"""

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    messages: List[Dict[str, str]]
    task_type: LLMTaskType = LLMTaskType.GENERAL
    preferred_provider: Optional[str] = None
    max_tokens: int = 2048
    temperature: float = 0.7
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class LLMResponse(BaseModel):
    """统一 LLM 响应模型"""

    request_id: str
    provider: str
    model: str
    content: str
    usage: Dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
