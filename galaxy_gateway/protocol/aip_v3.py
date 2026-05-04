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
    TASK_STATUS_RESPONSE = "task_status_response"
    TASK_RESULT = "task_result"
    TASK_CANCEL = "task_cancel"
    TASK_CANCEL_ACK = "task_cancel_ack"
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
    # Android error-path alias for goal_execution_result — some Android flows
    # emit "goal_result" on failure/cancellation paths instead of the canonical
    # "goal_execution_result".  This alias must be mapped to the same handler
    # so the error path is not silently discarded on the canonical gateway.
    GOAL_RESULT = "goal_result"

    # === 多设备并行任务 ===
    PARALLEL_SUBTASK = "parallel_subtask"
    PARALLEL_RESULT = "parallel_result"

    # === 错误处理 ===
    ERROR = "error"
    ERROR_RECOVERY = "error_recovery"

    # === Agent 分发 (Phase 1) ===
    AGENT_DEPLOY = "agent_deploy"
    AGENT_DEPLOY_ACK = "agent_deploy_ack"
    AGENT_STATUS = "agent_status"
    AGENT_RESULT = "agent_result"

    # === 设备间中继 (Phase 2) ===
    RELAY_REQUEST = "relay_request"
    RELAY_FORWARD = "relay_forward"
    RELAY_REPLY = "relay_reply"
    RELAY_ACK = "relay_ack"

    # === 混合执行 (Phase 3) ===
    HYBRID_EXECUTE = "hybrid_execute"
    HYBRID_RESULT = "hybrid_result"
    HYBRID_DEGRADE = "hybrid_degrade"

    # === RAG & 代码执行 (Phase 4) ===
    RAG_QUERY = "rag_query"
    RAG_RESULT = "rag_result"
    CODE_EXECUTE = "code_execute"
    CODE_RESULT = "code_result"

    # === P2P Mesh (Phase 5) ===
    PEER_ANNOUNCE = "peer_announce"
    PEER_EXCHANGE = "peer_exchange"
    MESH_TOPOLOGY = "mesh_topology"

    # === Android Delegated Execution Signals (PR-16) ===
    DELEGATED_EXECUTION_SIGNAL = "delegated_execution_signal"

    # === Android Reconciliation Signal (PR-7-V2 / PR-06-Android) ===
    # Uplink: Android → V2 — explicit state reconciliation signal emitted by
    # Android RuntimeController to push participant/task/runtime truth into V2.
    RECONCILIATION_SIGNAL = "reconciliation_signal"

    # === Android Takeover Protocol ===
    # Downlink: V2 → Android — request Android to accept takeover
    TAKEOVER_REQUEST = "takeover_request"
    # Uplink: Android → V2 — Android response (accepted / rejected)
    TAKEOVER_RESPONSE = "takeover_response"

    # === Android Native Handoff V2 (PR-H) ===
    # Canonical downlink wire type — matches Android AipModels.kt HANDOFF_ENVELOPE_V2
    HANDOFF_ENVELOPE_V2 = "handoff_envelope_v2"
    # Canonical uplink wire type — Android sends this as the top-level result envelope
    # (PR-02-V2).  Individual ack/result/failure messages are routed through the same
    # handler; this type is kept as a first-class enum entry so future Android clients
    # may emit it directly.
    HANDOFF_ENVELOPE_V2_RESULT = "handoff_envelope_v2_result"
    # Legacy/compat input alias — kept for backward-compatible ingestion only;
    # no longer emitted as canonical output.
    HANDOFF_DISPATCH = "handoff_dispatch"
    HANDOFF_ACK = "handoff_ack"
    HANDOFF_RESULT = "handoff_result"
    HANDOFF_FAILURE = "handoff_failure"

    # === Android Lifecycle / Governance Uplink Reports ===
    # These types are emitted by GalaxyConnectionService.kt on the Android side
    # (MsgType.CANCEL_RESULT, DEVICE_READINESS_REPORT, DEVICE_GOVERNANCE_REPORT,
    # DEVICE_ACCEPTANCE_REPORT, DEVICE_STRATEGY_REPORT).  They were previously
    # absent from this enum which caused MessageType('cancel_result') to raise
    # ValueError and the gateway to return UNKNOWN_MESSAGE_TYPE to Android.
    # They are now registered here so the dispatch table can route them to
    # handle_generic_forward for structured ACK logging instead of an error.
    CANCEL_RESULT = "cancel_result"
    DEVICE_READINESS_REPORT = "device_readiness_report"
    DEVICE_GOVERNANCE_REPORT = "device_governance_report"
    DEVICE_ACCEPTANCE_REPORT = "device_acceptance_report"
    DEVICE_STRATEGY_REPORT = "device_strategy_report"

    # === Android Runtime-State Transparency Uplink (PR-RT) ===
    # These two types carry structured Android runtime state into V2.
    # DEVICE_STATE_SNAPSHOT: periodic full snapshot of the Android device
    #   runtime — llama/NCNN availability, model identity, readiness state,
    #   offline queue depth, fallback tier, warmup result, health score.
    # DEVICE_EXECUTION_EVENT: per-step execution phase event emitted during
    #   delegated execution — flow_id, task_id, phase, step_index, blocking.
    # Both are absorbed by core.android_device_state_store and made available
    # to V2 operator surfaces via /api/v1/operator/devices/ecosystem.
    DEVICE_STATE_SNAPSHOT = "device_state_snapshot"
    DEVICE_EXECUTION_EVENT = "device_execution_event"


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

    # PR-2: Unified envelope fields — trace propagation across all hops
    trace_id: Optional[str] = None
    """Distributed trace identifier propagated through planner → gateway → device."""

    runtime_session_id: Optional[str] = None
    """Session scope identifier tying commands to a single user/agent interaction."""

    idempotency_key: Optional[str] = None
    """Client-supplied dedup key. Auto-generated from task_id when absent in compat layer."""

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


def create_gui_scroll_message(
    device_id: str,
    x: int,
    y: int,
    direction: str = "down",
    delta: int = 300,
    task_id: Optional[str] = None,
) -> AIPMessage:
    """Create a canonical GUI scroll message.

    :param device_id: Target device identifier.
    :param x: X coordinate of the scroll origin.
    :param y: Y coordinate of the scroll origin.
    :param direction: Scroll direction — ``"up"``, ``"down"``, ``"left"``, or
        ``"right"`` (default ``"down"``).
    :param delta: Pixel distance or step count (default 300).
    :param task_id: Optional task identifier.
    """
    return AIPMessage(
        type=MessageType.GUI_SCROLL,
        device_id=device_id,
        task_id=task_id,
        payload={"x": x, "y": y, "direction": direction, "delta": delta},
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


def validate_message(message: AIPMessage) -> tuple:
    """Validate AIP message integrity.

    Returns a ``(valid: bool, error: Optional[str])`` tuple so callers can
    surface a human-readable reason when validation fails.

    Basic invariants checked:
    * ``device_id`` must be a non-empty string.
    * ``type`` must be set.
    * ``version`` must start with ``"3"`` (AIP v3+).

    :param message: The :class:`AIPMessage` to validate.
    :returns: ``(True, None)`` on success; ``(False, reason)`` on failure.
    """
    if not message.device_id:
        return False, "Missing or empty 'device_id'"
    if not message.type:
        return False, "Missing 'type'"
    version = getattr(message, "version", None) or ""
    if not version.startswith("3"):
        return False, f"AIP version {version!r} is not a supported v3 version"
    return True, None


# ============================================================================
# Unified Protocol Bridge - AIP v2.0 ↔ v3.0
# ============================================================================

class UnifiedMessageTypes:
    """
    Single access point for all AIP v3.0 message types.

    Usage:
        from galaxy_gateway.protocol.aip_v3 import UnifiedMessageTypes
        all_types = UnifiedMessageTypes.get_all_types()
        is_valid = UnifiedMessageTypes.is_valid("peer_announce")
    """

    @classmethod
    def get_all_types(cls) -> list:
        """Return all valid message type strings from v3 (canonical)."""
        return [t.value for t in MessageType]

    @classmethod
    def is_valid(cls, msg_type: str) -> bool:
        """Check if a message type string is valid in AIP v3."""
        return msg_type in cls.get_all_types()

    @classmethod
    def get_v2_extended(cls):
        """Deprecated: v2 ExtendedMessageType is no longer supported.
        All types are now part of :class:`MessageType` in v3."""
        return None

    @classmethod
    def get_v3_message_type(cls):
        """Get v3.0 MessageType enum."""
        return MessageType

    @classmethod
    def get_registry(cls):
        """Deprecated: v2 MessageTypeRegistry is no longer supported.
        Use :meth:`get_all_types` instead."""
        return None
