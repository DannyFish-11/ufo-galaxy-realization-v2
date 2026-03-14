"""
AIP v3.0 - Agent Interaction Protocol (统一版本)

此文件是 Galaxy 系统的协议单一事实来源。
所有平台（Android, Windows, Linux, iOS, 云端）必须遵循此协议定义。

基于 Microsoft UFO AIP 协议扩展，增加跨平台支持。
"""

from enum import Enum, IntEnum, Flag, auto
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from datetime import datetime
import uuid


# ============================================================================
# 设备类型定义 (统一所有平台)
# ============================================================================

class AIPDeviceType(str, Enum):
    """AIP v3.0 细分设备类型定义 - 覆盖所有支持的平台"""
    
    # === 移动端 ===
    ANDROID_PHONE = "android_phone"
    ANDROID_TABLET = "android_tablet"
    ANDROID_TV = "android_tv"
    ANDROID_CAR = "android_car"
    ANDROID_WEAR = "android_wear"
    
    IOS_PHONE = "ios_phone"
    IOS_TABLET = "ios_tablet"
    IOS_WATCH = "ios_watch"
    
    # === 桌面端 ===
    WINDOWS_DESKTOP = "windows_desktop"
    WINDOWS_LAPTOP = "windows_laptop"
    WINDOWS_WSL = "windows_wsl"
    
    MACOS_DESKTOP = "macos_desktop"
    MACOS_LAPTOP = "macos_laptop"
    
    LINUX_DESKTOP = "linux_desktop"
    LINUX_SERVER = "linux_server"
    LINUX_RASPBERRY = "linux_raspberry"
    
    # === 云端 ===
    CLOUD_HUAWEI = "cloud_huawei"
    CLOUD_ALIYUN = "cloud_aliyun"
    CLOUD_TENCENT = "cloud_tencent"
    CLOUD_AWS = "cloud_aws"
    CLOUD_AZURE = "cloud_azure"
    
    # === 嵌入式/IoT ===
    EMBEDDED_ESP32 = "embedded_esp32"
    EMBEDDED_ARDUINO = "embedded_arduino"
    IOT_GENERIC = "iot_generic"
    
    # === 容器/虚拟 ===
    CONTAINER_DOCKER = "container_docker"
    VIRTUAL_VM = "virtual_vm"
    
    # === 通用 ===
    UNKNOWN = "unknown"


class DevicePlatform(str, Enum):
    """设备平台大类"""
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    CLOUD = "cloud"
    EMBEDDED = "embedded"
    UNKNOWN = "unknown"


# ============================================================================
# 设备能力定义
# ============================================================================

class DeviceCapability(Flag):
    """设备能力标志 - 用于能力协商"""
    
    NONE = 0
    
    # 基础能力
    NETWORK = auto()
    STORAGE = auto()
    COMPUTE = auto()
    
    # GUI 能力
    GUI_READ = auto()
    GUI_WRITE = auto()
    GUI_SCREENSHOT = auto()
    GUI_STREAM = auto()
    
    # 输入能力
    INPUT_TOUCH = auto()
    INPUT_KEYBOARD = auto()
    INPUT_MOUSE = auto()
    INPUT_VOICE = auto()
    
    # 传感器
    SENSOR_GPS = auto()
    SENSOR_CAMERA = auto()
    SENSOR_MIC = auto()
    SENSOR_MOTION = auto()
    
    # 系统能力
    SYSTEM_SHELL = auto()
    SYSTEM_ROOT = auto()
    SYSTEM_INSTALL = auto()
    SYSTEM_NOTIFICATION = auto()
    
    # 通信能力
    COMM_BLUETOOTH = auto()
    COMM_NFC = auto()
    COMM_WIFI_DIRECT = auto()


# ============================================================================
# 消息类型定义
# ============================================================================

class MessageType(str, Enum):
    """消息类型 - 统一客户端和服务端 (CANONICAL — 新代码应导入此定义)"""
    
    # === 设备管理 ===
    DEVICE_REGISTER = "device_register"
    DEVICE_REGISTER_ACK = "device_register_ack"
    DEVICE_UNREGISTER = "device_unregister"
    DEVICE_HEARTBEAT = "heartbeat"
    DEVICE_HEARTBEAT_ACK = "heartbeat_ack"
    DEVICE_STATUS = "device_status"
    DEVICE_CAPABILITIES = "device_capabilities"
    
    # === 任务调度 ===
    TASK_SUBMIT = "task_submit"
    TASK_ASSIGN = "task_assign"
    TASK_STATUS = "task_status"
    TASK_RESULT = "task_result"
    TASK_CANCEL = "task_cancel"
    TASK_PROGRESS = "task_progress"
    TASK_END = "task_end"
    
    # === 命令执行 ===
    COMMAND = "command"
    COMMAND_RESULT = "command_result"
    COMMAND_BATCH = "command_batch"
    
    # === GUI 操作 ===
    GUI_CLICK = "gui_click"
    GUI_SWIPE = "gui_swipe"
    GUI_INPUT = "gui_input"
    GUI_SCROLL = "gui_scroll"
    GUI_SCREENSHOT = "gui_screenshot"
    GUI_ELEMENT_QUERY = "gui_element_query"
    GUI_ELEMENT_WAIT = "gui_element_wait"
    GUI_SCREEN_CONTENT = "gui_screen_content"
    
    # === 屏幕/媒体 ===
    SCREEN_CAPTURE = "screen_capture"
    SCREEN_STREAM_START = "screen_stream_start"
    SCREEN_STREAM_STOP = "screen_stream_stop"
    SCREEN_STREAM_DATA = "screen_stream_data"
    
    # === 文件操作 ===
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    FILE_LIST = "file_list"
    FILE_TRANSFER = "file_transfer"
    
    # === 进程管理 ===
    PROCESS_START = "process_start"
    PROCESS_STOP = "process_stop"
    PROCESS_LIST = "process_list"
    PROCESS_STATUS = "process_status"
    
    # === 协调同步 ===
    COORD_SYNC = "coord_sync"
    COORD_BROADCAST = "coord_broadcast"
    COORD_LOCK = "coord_lock"
    COORD_UNLOCK = "coord_unlock"
    
    # === Agent 控制（与 AgentMessageHandler.kt 对齐）===
    TASK_EXECUTE = "task_execute"
    AGENT_PING = "agent_ping"
    AGENT_CONFIG_UPDATE = "agent_config_update"
    AGENT_RESTART = "agent_restart"

    # === UI 树操作（与 AgentMessageHandler.kt 对齐）===
    UI_TREE_REQUEST = "ui_tree_request"
    ACTION_EXECUTE = "action_execute"
    ACTION_SEQUENCE_EXECUTE = "action_sequence_execute"

    # === 应用/系统控制（与 AgentMessageHandler.kt 对齐）===
    APP_START = "app_start"
    APP_STOP = "app_stop"
    SYSTEM_COMMAND = "system_command"

    # === 能力/诊断上报 ===
    CAPABILITY_REPORT = "capability_report"
    CAPABILITY_REPORT_ACK = "capability_report_ack"
    DIAGNOSTICS_PAYLOAD = "diagnostics_payload"

    # === 唤醒与会话漫游 ===
    WAKE_EVENT = "wake_event"
    SESSION_MIGRATE = "session_migrate"
    SESSION_MIGRATE_ACK = "session_migrate_ack"
    DIAGNOSTICS_PAYLOAD_ACK = "diagnostics_payload_ack"

    # === 视觉请求 ===
    VISION_REQUEST = "vision_request"
    VISION_RESULT = "vision_result"

    # === 高层自治目标执行 ===
    GOAL_EXECUTION = "goal_execution"
    GOAL_EXECUTION_RESULT = "goal_execution_result"

    # === 多设备并行任务 ===
    PARALLEL_SUBTASK = "parallel_subtask"
    PARALLEL_RESULT = "parallel_result"

    # === 错误处理 ===
    ERROR = "error"
    ERROR_RECOVERY = "error_recovery"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    CONTINUE = "continue"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResultStatus(str, Enum):
    """执行结果状态"""
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    NONE = "none"


# ============================================================================
# 核心数据结构
# ============================================================================

class Rect(BaseModel):
    """矩形坐标"""
    x: int
    y: int
    width: int
    height: int
    
    @property
    def center_x(self) -> int:
        return self.x + self.width // 2
    
    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


class UIElement(BaseModel):
    """UI 元素信息"""
    element_id: Optional[str] = None
    class_name: Optional[str] = None
    text: Optional[str] = None
    content_description: Optional[str] = None
    view_id: Optional[str] = None
    bounds: Optional[Rect] = None
    is_clickable: bool = False
    is_editable: bool = False
    is_focusable: bool = False
    is_enabled: bool = True
    is_checked: bool = False
    children: List["UIElement"] = Field(default_factory=list)


class DeviceInfo(BaseModel):
    """设备信息"""
    device_id: str
    device_type: AIPDeviceType = AIPDeviceType.UNKNOWN
    platform: DevicePlatform = DevicePlatform.UNKNOWN
    name: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    sdk_version: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    capabilities: int = 0  # DeviceCapability flags
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Command(BaseModel):
    """命令定义"""
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    tool_type: str = "action"  # action, data_collection
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30  # 秒


class CommandResult(BaseModel):
    """命令执行结果"""
    command_id: str
    status: ResultStatus = ResultStatus.NONE
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0  # 秒


# ============================================================================
# AIP 消息定义
# ============================================================================

class AIPMessage(BaseModel):
    """AIP v3.0 统一消息格式"""
    
    # 协议版本
    version: str = "3.0"
    
    # 消息标识
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None  # 用于关联请求和响应
    
    # 消息类型
    type: MessageType
    
    # 设备信息
    device_id: str
    device_type: Optional[AIPDeviceType] = None
    
    # 时间戳
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # 任务相关
    task_id: Optional[str] = None
    task_status: Optional[TaskStatus] = None
    # task_type 用于区分 goal_execution / parallel_subtask 等高层任务类型
    task_type: Optional[str] = None

    # 命令相关
    commands: List[Command] = Field(default_factory=list)
    results: List[CommandResult] = Field(default_factory=list)
    
    # 通用数据载荷
    payload: Dict[str, Any] = Field(default_factory=dict)
    
    # 错误信息
    error: Optional[str] = None
    
    model_config = ConfigDict()

    @field_serializer("timestamp")
    @classmethod
    def _serialize_timestamp(cls, v: datetime) -> str:
        return v.isoformat()


# ============================================================================
# 快捷消息构造函数
# ============================================================================

def create_register_message(
    device_id: str,
    device_type: AIPDeviceType,
    device_info: DeviceInfo
) -> AIPMessage:
    """创建设备注册消息"""
    return AIPMessage(
        type=MessageType.DEVICE_REGISTER,
        device_id=device_id,
        device_type=device_type,
        payload={"device_info": device_info.model_dump()}
    )


def create_heartbeat_message(device_id: str) -> AIPMessage:
    """创建心跳消息"""
    return AIPMessage(
        type=MessageType.DEVICE_HEARTBEAT,
        device_id=device_id
    )


def create_task_message(
    device_id: str,
    task_id: str,
    commands: List[Command]
) -> AIPMessage:
    """创建任务消息"""
    return AIPMessage(
        type=MessageType.TASK_ASSIGN,
        device_id=device_id,
        task_id=task_id,
        commands=commands
    )


def create_gui_click_message(
    device_id: str,
    x: int,
    y: int,
    task_id: Optional[str] = None
) -> AIPMessage:
    """创建 GUI 点击消息"""
    return AIPMessage(
        type=MessageType.GUI_CLICK,
        device_id=device_id,
        task_id=task_id,
        payload={"x": x, "y": y}
    )


def create_gui_input_message(
    device_id: str,
    text: str,
    element_id: Optional[str] = None,
    task_id: Optional[str] = None
) -> AIPMessage:
    """创建 GUI 输入消息"""
    return AIPMessage(
        type=MessageType.GUI_INPUT,
        device_id=device_id,
        task_id=task_id,
        payload={"text": text, "element_id": element_id}
    )


def create_screenshot_message(
    device_id: str,
    task_id: Optional[str] = None
) -> AIPMessage:
    """创建截图请求消息"""
    return AIPMessage(
        type=MessageType.GUI_SCREENSHOT,
        device_id=device_id,
        task_id=task_id
    )


def create_error_message(
    device_id: str,
    error: str,
    correlation_id: Optional[str] = None
) -> AIPMessage:
    """创建错误消息"""
    return AIPMessage(
        type=MessageType.ERROR,
        device_id=device_id,
        correlation_id=correlation_id,
        error=error
    )


# ============================================================================
# Parallel-result aggregation payload (Phase-3)
# ============================================================================

class ParallelSubtaskItem(BaseModel):
    """单个并行子任务结果条目。"""
    model_config = ConfigDict(extra="allow")

    group_id:      str
    subtask_index: int
    device_id:     str
    task_id:       Optional[str] = None
    status:        str = "unknown"   # pending / running / success / failed / timeout
    result:        Optional[Dict[str, Any]] = None
    error:         Optional[str] = None
    latency_ms:    Optional[float] = None


class ParallelResultPayload(BaseModel):
    """
    AIP v3 ``parallel_result`` 消息的 payload 结构。

    用于在设备与服务端之间传递并行任务组的聚合结果，
    也作为 OpenClawd 返回给调用方的规范格式。
    """
    model_config = ConfigDict(extra="allow")

    group_id:       str
    subtask_results: List[ParallelSubtaskItem] = Field(default_factory=list)
    summary_status: str = "unknown"   # "success" | "partial" | "failed"
    succeeded:      int = 0
    failed:         int = 0
    total:          int = 0

    @classmethod
    def from_tracker_dict(cls, data: Dict[str, Any]) -> "ParallelResultPayload":
        """
        从 ``ParallelGroupTracker.aggregate().to_dict()`` 转换而来的工厂方法。
        兼容 compat 层直接传入已规范化字典。
        """
        items = [
            ParallelSubtaskItem(**item)
            for item in data.get("device_results", [])
        ]
        return cls(
            group_id=data.get("group_id", ""),
            subtask_results=items,
            summary_status=data.get("summary_status", "unknown"),
            succeeded=data.get("succeeded", 0),
            failed=data.get("failed", 0),
            total=data.get("total", len(items)),
        )




def parse_message(data: Union[str, dict]) -> AIPMessage:
    """解析 AIP 消息"""
    if isinstance(data, str):
        import json
        data = json.loads(data)
    return AIPMessage.model_validate(data)


def validate_message(message: AIPMessage) -> bool:
    """验证消息完整性"""
    if not message.device_id:
        return False
    if not message.type:
        return False
    return True


# ============================================================================
# Unified Protocol Bridge - AIP v2.0 ↔ v3.0
# ============================================================================

_V2_AVAILABLE = False
_V2ExtendedMessageType = None
_V2MessageTypeRegistry = None

try:
    from galaxy_gateway.aip_protocol_v2 import (
        ExtendedMessageType as _V2ExtendedMessageType,
        MessageTypeRegistry as _V2MessageTypeRegistry,
    )
    _V2_AVAILABLE = True
except ImportError:
    pass


class UnifiedMessageTypes:
    """
    Single access point for all AIP message types across v2.0 and v3.0.

    Usage:
        from galaxy_gateway.protocol.aip_v3 import UnifiedMessageTypes
        all_types = UnifiedMessageTypes.get_all_types()
        is_valid = UnifiedMessageTypes.is_valid("peer_announce")
    """

    @classmethod
    def get_all_types(cls) -> list:
        """Return all valid message type strings from v2 and v3 (de-duplicated)"""
        v3_types = [t.value for t in MessageType]
        if _V2_AVAILABLE and _V2ExtendedMessageType is not None:
            v2_ext_types = [t.value for t in _V2ExtendedMessageType]
            return list(dict.fromkeys(v3_types + v2_ext_types))
        return v3_types

    @classmethod
    def is_valid(cls, msg_type: str) -> bool:
        """Check if a message type string is valid across any protocol version"""
        return msg_type in cls.get_all_types()

    @classmethod
    def get_v2_extended(cls):
        """Get v2.0 ExtendedMessageType enum (or None if unavailable)"""
        return _V2ExtendedMessageType if _V2_AVAILABLE else None

    @classmethod
    def get_v3_message_type(cls):
        """Get v3.0 MessageType enum"""
        return MessageType

    @classmethod
    def get_registry(cls):
        """Get v2.0 MessageTypeRegistry (or None if unavailable)"""
        return _V2MessageTypeRegistry if _V2_AVAILABLE else None
