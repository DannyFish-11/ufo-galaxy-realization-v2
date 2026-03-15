"""
Android Bridge Service
Galaxy - 服务端与安卓端对接桥接层

此模块负责：
1. 处理安卓设备的注册和管理
2. 将服务端任务转换为安卓可执行的命令
3. 处理安卓端返回的结果
4. 维护安卓设备状态

与安卓端 AIPMessageV3.kt 完全对齐

Author: Galaxy Team
Version: 3.0.0
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Callable, Set
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# 设备类型定义 (与 AIPMessageV3.kt 完全对齐)
# =============================================================================

# 统一设备类型 — 从 core.device_types 导入（单一事实来源）
# DeviceType = AIPDeviceType (细粒度28种)，DevicePlatform (平台大类)
from core.device_types import (  # noqa: E402
    AIPDeviceType as DeviceType,
    DevicePlatform,
)


# =============================================================================
# 消息类型 / 任务状态 / 结果状态 — 从协议 SSOT 导入
# galaxy_gateway/protocol/aip_v3.py 是单一事实来源；此处仅做再导出。
# =============================================================================
from galaxy_gateway.protocol.aip_v3 import (  # noqa: E402
    MessageType,
    TaskStatus,
    ResultStatus,
)


# =============================================================================
# OpenClawd 记忆回流 — 顶层导入使测试可以通过 patch() 注入 mock
# =============================================================================
try:
    from core.openclawd_memory_backflow import store_task_result
except ImportError:
    store_task_result = None  # type: ignore[assignment]


# =============================================================================
# 设备能力标志 (与 AIPMessageV3.kt 完全对齐)
# =============================================================================

class DeviceCapability:
    NONE = 0
    
    # 基础能力
    NETWORK = 1 << 0
    STORAGE = 1 << 1
    COMPUTE = 1 << 2
    
    # GUI 能力
    GUI_READ = 1 << 3
    GUI_WRITE = 1 << 4
    GUI_SCREENSHOT = 1 << 5
    GUI_STREAM = 1 << 6
    
    # 输入能力
    INPUT_TOUCH = 1 << 7
    INPUT_KEYBOARD = 1 << 8
    INPUT_MOUSE = 1 << 9
    INPUT_VOICE = 1 << 10
    
    # 传感器
    SENSOR_GPS = 1 << 11
    SENSOR_CAMERA = 1 << 12
    SENSOR_MIC = 1 << 13
    SENSOR_MOTION = 1 << 14
    
    # 系统能力
    SYSTEM_SHELL = 1 << 15
    SYSTEM_ROOT = 1 << 16
    SYSTEM_INSTALL = 1 << 17
    SYSTEM_NOTIFICATION = 1 << 18
    
    # 通信能力
    COMM_BLUETOOTH = 1 << 19
    COMM_NFC = 1 << 20
    COMM_WIFI_DIRECT = 1 << 21
    
    @classmethod
    def get_android_default(cls) -> int:
        """获取 Android 设备的默认能力"""
        return (cls.NETWORK | cls.STORAGE | cls.COMPUTE |
                cls.GUI_READ | cls.GUI_WRITE | cls.GUI_SCREENSHOT |
                cls.INPUT_TOUCH | cls.INPUT_VOICE |
                cls.SENSOR_GPS | cls.SENSOR_CAMERA | cls.SENSOR_MIC | cls.SENSOR_MOTION |
                cls.SYSTEM_NOTIFICATION |
                cls.COMM_BLUETOOTH | cls.COMM_NFC | cls.COMM_WIFI_DIRECT)
    
    @classmethod
    def has_capability(cls, capabilities: int, capability: int) -> bool:
        """检查是否具有某个能力"""
        return (capabilities & capability) != 0
    
    @classmethod
    def to_list(cls, capabilities: int) -> List[str]:
        """将能力标志转换为列表"""
        result = []
        capability_map = {
            cls.NETWORK: "network",
            cls.STORAGE: "storage",
            cls.COMPUTE: "compute",
            cls.GUI_READ: "gui_read",
            cls.GUI_WRITE: "gui_write",
            cls.GUI_SCREENSHOT: "gui_screenshot",
            cls.GUI_STREAM: "gui_stream",
            cls.INPUT_TOUCH: "input_touch",
            cls.INPUT_KEYBOARD: "input_keyboard",
            cls.INPUT_MOUSE: "input_mouse",
            cls.INPUT_VOICE: "input_voice",
            cls.SENSOR_GPS: "sensor_gps",
            cls.SENSOR_CAMERA: "sensor_camera",
            cls.SENSOR_MIC: "sensor_mic",
            cls.SENSOR_MOTION: "sensor_motion",
            cls.SYSTEM_SHELL: "system_shell",
            cls.SYSTEM_ROOT: "system_root",
            cls.SYSTEM_INSTALL: "system_install",
            cls.SYSTEM_NOTIFICATION: "system_notification",
            cls.COMM_BLUETOOTH: "comm_bluetooth",
            cls.COMM_NFC: "comm_nfc",
            cls.COMM_WIFI_DIRECT: "comm_wifi_direct",
        }
        for cap, name in capability_map.items():
            if cls.has_capability(capabilities, cap):
                result.append(name)
        return result


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class Rect:
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
    
    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Rect":
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            width=data.get("width", 0),
            height=data.get("height", 0)
        )


@dataclass
class UIElement:
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
    
    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.element_id:
            result["element_id"] = self.element_id
        if self.class_name:
            result["class_name"] = self.class_name
        if self.text:
            result["text"] = self.text
        if self.content_description:
            result["content_description"] = self.content_description
        if self.view_id:
            result["view_id"] = self.view_id
        if self.bounds:
            result["bounds"] = self.bounds.to_dict()
        result["is_clickable"] = self.is_clickable
        result["is_editable"] = self.is_editable
        result["is_focusable"] = self.is_focusable
        result["is_enabled"] = self.is_enabled
        result["is_checked"] = self.is_checked
        return result


@dataclass
class AndroidDevice:
    """安卓设备信息"""
    device_id: str
    device_type: DeviceType = DeviceType.ANDROID_PHONE
    platform: DevicePlatform = DevicePlatform.ANDROID
    name: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    sdk_version: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    capabilities: int = 0
    supported_actions: List[str] = field(default_factory=list)  # Action types this device can perform (e.g., tap, swipe, screenshot)

    # 连接状态
    connected: bool = False
    last_heartbeat: float = 0
    websocket: Any = None
    
    # 任务状态
    current_task_id: Optional[str] = None
    pending_tasks: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type.value,
            "platform": self.platform.value,
            "name": self.name,
            "model": self.model,
            "os_version": self.os_version,
            "sdk_version": self.sdk_version,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "capabilities": self.capabilities,
            "capabilities_list": DeviceCapability.to_list(self.capabilities),
            "supported_actions": self.supported_actions,
            "connected": self.connected,
            "last_heartbeat": self.last_heartbeat,
            "current_task_id": self.current_task_id
        }
    
    @classmethod
    def from_registration(cls, data: Dict) -> "AndroidDevice":
        """从注册消息创建设备"""
        return cls(
            device_id=data.get("device_id", str(uuid.uuid4())),
            device_type=DeviceType(data.get("device_type", "android_phone")),
            platform=DevicePlatform(data.get("platform", "android")),
            name=data.get("name"),
            model=data.get("model"),
            os_version=data.get("os_version"),
            sdk_version=data.get("sdk_version"),
            screen_width=data.get("screen_width"),
            screen_height=data.get("screen_height"),
            capabilities=data.get("capabilities", DeviceCapability.get_android_default()),
            connected=True,
            last_heartbeat=time.time()
        )


# =============================================================================
# 消息构建器
# =============================================================================

class MessageBuilder:
    """消息构建器 - 与 AIPMessageV3.kt 的 MessageBuilder 对齐"""
    
    PROTOCOL_VERSION = "3.0"
    
    @classmethod
    def _base_message(cls, msg_type: MessageType, device_id: str) -> Dict[str, Any]:
        return {
            "version": cls.PROTOCOL_VERSION,
            "type": msg_type.value,
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "timestamp": int(time.time() * 1000)
        }
    
    @classmethod
    def device_register_ack(cls, device_id: str, success: bool, 
                           session_id: Optional[str] = None,
                           message: Optional[str] = None) -> Dict[str, Any]:
        """设备注册确认"""
        msg = cls._base_message(MessageType.DEVICE_REGISTER_ACK, device_id)
        msg["success"] = success
        if session_id:
            msg["session_id"] = session_id
        if message:
            msg["message"] = message
        return msg
    
    @classmethod
    def heartbeat_ack(cls, device_id: str) -> Dict[str, Any]:
        """心跳确认"""
        return cls._base_message(MessageType.DEVICE_HEARTBEAT_ACK, device_id)
    
    @classmethod
    def task_assign(cls, device_id: str, task_id: str, task_type: str,
                   payload: Dict[str, Any], priority: int = 5,
                   timeout: int = 300) -> Dict[str, Any]:
        """分配任务"""
        msg = cls._base_message(MessageType.TASK_ASSIGN, device_id)
        msg["task_id"] = task_id
        msg["task_type"] = task_type
        msg["payload"] = payload
        msg["priority"] = priority
        msg["timeout"] = timeout
        return msg
    
    @classmethod
    def gui_click(cls, device_id: str, x: int, y: int,
                 element_id: Optional[str] = None) -> Dict[str, Any]:
        """GUI 点击命令"""
        msg = cls._base_message(MessageType.GUI_CLICK, device_id)
        msg["x"] = x
        msg["y"] = y
        if element_id:
            msg["element_id"] = element_id
        return msg
    
    @classmethod
    def gui_swipe(cls, device_id: str, start_x: int, start_y: int,
                 end_x: int, end_y: int, duration_ms: int = 300) -> Dict[str, Any]:
        """GUI 滑动命令"""
        msg = cls._base_message(MessageType.GUI_SWIPE, device_id)
        msg["start_x"] = start_x
        msg["start_y"] = start_y
        msg["end_x"] = end_x
        msg["end_y"] = end_y
        msg["duration_ms"] = duration_ms
        return msg
    
    @classmethod
    def gui_input(cls, device_id: str, text: str,
                 element_id: Optional[str] = None,
                 clear_first: bool = False) -> Dict[str, Any]:
        """GUI 输入命令"""
        msg = cls._base_message(MessageType.GUI_INPUT, device_id)
        msg["text"] = text
        if element_id:
            msg["element_id"] = element_id
        msg["clear_first"] = clear_first
        return msg
    
    @classmethod
    def gui_screenshot(cls, device_id: str, quality: int = 80,
                      scale: float = 1.0) -> Dict[str, Any]:
        """GUI 截图命令"""
        msg = cls._base_message(MessageType.GUI_SCREENSHOT, device_id)
        msg["quality"] = quality
        msg["scale"] = scale
        return msg
    
    @classmethod
    def gui_element_query(cls, device_id: str,
                         text: Optional[str] = None,
                         class_name: Optional[str] = None,
                         view_id: Optional[str] = None,
                         content_description: Optional[str] = None) -> Dict[str, Any]:
        """GUI 元素查询"""
        msg = cls._base_message(MessageType.GUI_ELEMENT_QUERY, device_id)
        if text:
            msg["text"] = text
        if class_name:
            msg["class_name"] = class_name
        if view_id:
            msg["view_id"] = view_id
        if content_description:
            msg["content_description"] = content_description
        return msg
    
    @classmethod
    def command(cls, device_id: str, command_type: str,
               params: Dict[str, Any]) -> Dict[str, Any]:
        """通用命令"""
        msg = cls._base_message(MessageType.COMMAND, device_id)
        msg["command_type"] = command_type
        msg["params"] = params
        return msg
    
    @classmethod
    def error(cls, device_id: str, error_code: str,
             error_message: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        """错误消息"""
        msg = cls._base_message(MessageType.ERROR, device_id)
        msg["error_code"] = error_code
        msg["error_message"] = error_message
        if details:
            msg["details"] = details
        return msg

    @classmethod
    def capability_report_ack(cls, device_id: str, accepted: bool = True,
                              message: Optional[str] = None) -> Dict[str, Any]:
        """能力上报确认"""
        msg = cls._base_message(MessageType.CAPABILITY_REPORT_ACK, device_id)
        msg["accepted"] = accepted
        if message:
            msg["message"] = message
        return msg

    @classmethod
    def diagnostics_payload_ack(cls, device_id: str, accepted: bool = True,
                                message: Optional[str] = None) -> Dict[str, Any]:
        """诊断数据确认"""
        msg = cls._base_message(MessageType.DIAGNOSTICS_PAYLOAD_ACK, device_id)
        msg["accepted"] = accepted
        if message:
            msg["message"] = message
        return msg

    @classmethod
    def vision_result(cls, device_id: str, task_id: str,
                      result: Dict[str, Any]) -> Dict[str, Any]:
        """视觉分析结果（以 task_assign 形式下发操作指令）"""
        return cls.task_assign(
            device_id=device_id,
            task_id=task_id,
            task_type="vision_action",
            payload=result,
        )


# =============================================================================
# Android Bridge 服务
# =============================================================================

class AndroidBridge:
    """
    Android 桥接服务
    
    负责管理所有安卓设备的连接、任务分发和结果收集
    """
    
    def __init__(self):
        self._devices: Dict[str, AndroidDevice] = {}
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._lock = asyncio.Lock()
        
        # 注册默认处理器
        self._register_default_handlers()
        
        logger.info("AndroidBridge initialized")
    
    def _register_default_handlers(self):
        """注册默认消息处理器"""
        self._message_handlers[MessageType.DEVICE_REGISTER] = self._handle_device_register
        self._message_handlers[MessageType.DEVICE_HEARTBEAT] = self._handle_heartbeat
        self._message_handlers[MessageType.TASK_RESULT] = self._handle_task_result
        self._message_handlers[MessageType.TASK_PROGRESS] = self._handle_task_progress
        self._message_handlers[MessageType.COMMAND_RESULT] = self._handle_command_result
        self._message_handlers[MessageType.ERROR] = self._handle_error

        # AgentMessageHandler.kt 对齐类型
        self._message_handlers[MessageType.TASK_EXECUTE] = self._handle_task_execute
        self._message_handlers[MessageType.TASK_CANCEL] = self._handle_generic_forward
        self._message_handlers[MessageType.TASK_STATUS] = self._handle_generic_forward
        self._message_handlers[MessageType.AGENT_PING] = self._handle_agent_ping
        self._message_handlers[MessageType.AGENT_CONFIG_UPDATE] = self._handle_generic_forward
        self._message_handlers[MessageType.AGENT_RESTART] = self._handle_generic_forward
        self._message_handlers[MessageType.UI_TREE_REQUEST] = self._handle_generic_forward
        self._message_handlers[MessageType.ACTION_EXECUTE] = self._handle_generic_forward
        self._message_handlers[MessageType.ACTION_SEQUENCE_EXECUTE] = self._handle_generic_forward
        self._message_handlers[MessageType.APP_START] = self._handle_generic_forward
        self._message_handlers[MessageType.APP_STOP] = self._handle_generic_forward
        self._message_handlers[MessageType.SYSTEM_COMMAND] = self._handle_generic_forward

        # 设备状态上报
        self._message_handlers[MessageType.DEVICE_STATUS] = self._handle_device_status

        # 任务生命周期：task_end 结束确认
        self._message_handlers[MessageType.TASK_END] = self._handle_task_end

        # 能力/诊断上报
        self._message_handlers[MessageType.CAPABILITY_REPORT] = self._handle_capability_report
        self._message_handlers[MessageType.DIAGNOSTICS_PAYLOAD] = self._handle_diagnostics_payload

        # 视觉请求
        self._message_handlers[MessageType.VISION_REQUEST] = self._handle_vision_request

        # Catch-all: 为所有未注册的消息类型添加通用日志处理器
        for msg_type in MessageType:
            if msg_type not in self._message_handlers:
                self._message_handlers[msg_type] = self._handle_unregistered

    async def _handle_unregistered(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """通用处理器 — 记录日志并返回 ACK，防止消息被静默丢弃"""
        msg_type = message.get("type", "unknown")
        device_id = message.get("device_id", "unknown")
        logger.info(f"Unhandled message type '{msg_type}' from device '{device_id}', returning ACK")
        return {
            "type": "ack",
            "device_id": device_id,
            "original_type": msg_type,
            "status": "received",
            "note": "No specific handler registered for this message type",
        }

    # Fields that are hard requirements — a message without these cannot be
    # meaningfully processed at all.
    _V3_MANDATORY_FIELDS: tuple = ("type", "device_id")

    # Fields that are required by the full AIP v3.0 spec but can be
    # auto-generated for backward compatibility when absent.
    _V3_AUTO_FILL_FIELDS: tuple = ("version", "timestamp", "message_id")

    async def handle_message(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理来自安卓设备的消息。

        验证流程：
        1. 强制校验 AIP v3.0+（version >= 3.0），低版本直接返回拒绝响应。
        2. 注入缺失的 trace_id / route_mode 并记录结构化日志。
        3. 自动补全 AIP/3.0 的可选元数据字段（timestamp、message_id）——
           当这些字段缺失时进行填充，保持向后兼容。
        4. 检查强制字段（type、device_id）——缺失时返回带明确错误码的 error 消息。
        5. 派发到对应处理器。
        """
        # Step 1 — Enforce AIP v3.0+; reject messages with lower version.
        try:
            from galaxy_gateway.protocol.compat import enforce_aip_v3, inject_trace_metadata, AIPVersionError
            try:
                enforce_aip_v3(message)
            except AIPVersionError as ver_err:
                raw_version = message.get("version", "<missing>")
                logger.warning(
                    "AIP version rejected in android_bridge",
                    extra={
                        "event": "aip_version_rejected",
                        "raw_version": raw_version,
                        "device_id": message.get("device_id", "unknown"),
                        "message_type": message.get("type"),
                        "reason": str(ver_err),
                    },
                )
                return MessageBuilder.error(
                    message.get("device_id") or "unknown",
                    "PROTOCOL_VERSION_REJECTED",
                    str(ver_err),
                    details={"required": "AIP v3.0+", "received": raw_version},
                )
            # Step 2 — Inject missing trace_id / route_mode.
            message = inject_trace_metadata(message)
        except ImportError:
            pass  # compat module not yet available during early bootstrap

        device_id = message.get("device_id")
        msg_type_str = message.get("type")

        # Step 3 — Auto-fill metadata fields that may be absent in legacy messages.
        # This keeps backward compatibility while ensuring all internal handlers
        # receive a complete v3-shaped dict.  Copy once, then fill in-place.
        needs_fill = (
            not message.get("timestamp")
            or not message.get("message_id")
        )
        if needs_fill:
            message = dict(message)
            if not message.get("timestamp"):
                message["timestamp"] = int(time.time() * 1000)
            if not message.get("message_id"):
                message["message_id"] = str(uuid.uuid4())

        # Step 4 — Validate hard-required fields; return an explicit error when absent.
        missing = [f for f in self._V3_MANDATORY_FIELDS if not message.get(f)]
        if missing:
            logger.warning(
                "handle_message: malformed message from %s — missing required fields: %s",
                device_id or "unknown",
                missing,
            )
            return MessageBuilder.error(
                device_id or "unknown",
                "MISSING_REQUIRED_FIELDS",
                f"AIP v3.0 required fields missing: {missing}",
                details={"missing_fields": missing, "received_type": msg_type_str},
            )

        # Step 5 — Resolve the MessageType enum value.
        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            logger.warning(f"Unknown message type: {msg_type_str}")
            return MessageBuilder.error(
                device_id or "unknown",
                "UNKNOWN_MESSAGE_TYPE",
                f"Unknown message type: {msg_type_str}"
            )

        handler = self._message_handlers.get(msg_type)
        if handler:
            response = await handler(websocket, message)
            # Propagate trace_id/route_mode into the response so downstream
            # components always see both fields.
            if response and isinstance(response, dict):
                trace_id = message.get("trace_id", "")
                route_mode = message.get("route_mode", "")
                resp_payload = response.get("payload")
                if isinstance(resp_payload, dict):
                    if trace_id:
                        resp_payload.setdefault("trace_id", trace_id)
                    if route_mode:
                        resp_payload.setdefault("route_mode", route_mode)
            return response
        else:
            logger.debug(f"No handler for message type: {msg_type}")
            return None
    
    async def _handle_device_register(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理设备注册，失败时向网关日志输出结构化错误"""
        device_id = message.get("device_id")

        try:
            async with self._lock:
                device = AndroidDevice.from_registration(message)
                device.websocket = websocket
                self._devices[device_id] = device

            logger.info(
                "Android device registered: device_id=%s model=%s platform=%s",
                device_id, device.model, device.platform,
            )

            return MessageBuilder.device_register_ack(
                device_id=device_id,
                success=True,
                session_id=str(uuid.uuid4()),
                message="Registration successful"
            )

        except Exception as exc:
            _SENSITIVE_FIELDS = frozenset({
                "websocket", "image_base64", "token", "password",
                "credential", "secret", "auth", "api_key",
            })
            safe_payload = {k: v for k, v in message.items() if k not in _SENSITIVE_FIELDS}
            logger.error(
                "Device registration failed: device_id=%s error=%s payload=%s",
                device_id, exc, safe_payload,
            )
            return MessageBuilder.device_register_ack(
                device_id=device_id or "unknown",
                success=False,
                message=f"Registration failed: {exc}",
            )

    async def _handle_heartbeat(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理心跳，未注册设备仍回 ACK 并输出警告"""
        device_id = message.get("device_id")

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].last_heartbeat = time.time()
                self._devices[device_id].connected = True
            else:
                logger.warning(
                    "Heartbeat from unregistered device: device_id=%s; ACK sent",
                    device_id,
                )

        return MessageBuilder.heartbeat_ack(device_id)

    async def _handle_device_status(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理设备状态上报（battery, cpu, memory 等）"""
        device_id = message.get("device_id")
        status_payload = message.get("status") or message.get("payload") or {}

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].last_heartbeat = time.time()
                self._devices[device_id].connected = True

        logger.info(
            "Device status update: device_id=%s status=%s",
            device_id, status_payload,
        )

        return {
            "version": "3.0",
            "type": "device_status_ack",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "status": "received",
        }

    async def _handle_task_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        """处理任务结果，完成 Future 并触发 OpenClawd 记忆回流"""
        task_id = message.get("task_id")
        device_id = message.get("device_id")
        result_status = message.get("status", "unknown")
        route_mode = message.get("route_mode", "cross_device")

        logger.info(
            "Task result received: task_id=%s device_id=%s status=%s",
            task_id, device_id, result_status,
        )

        # 完成等待的 Future
        if task_id in self._pending_responses:
            future = self._pending_responses.pop(task_id)
            if not future.done():
                future.set_result(message)

        # 更新设备状态
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = None

        # OpenClawd 记忆回流 — 将完成任务存入记忆 DB（使用模块级导入使之可测）
        if task_id and device_id and store_task_result is not None:
            try:
                await store_task_result(
                    task_id=task_id,
                    device_id=device_id,
                    route_mode=route_mode,
                    result=message,
                )
                logger.debug(
                    "Memory backflow stored: task_id=%s device_id=%s route_mode=%s",
                    task_id, device_id, route_mode,
                )
            except Exception as bf_err:
                logger.warning(
                    "Memory backflow failed (non-fatal): task_id=%s error=%s",
                    task_id, bf_err,
                )

    async def _handle_task_end(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理任务结束通知（task_submit → task_assign → task_progress → task_result → task_end）"""
        task_id = message.get("task_id")
        device_id = message.get("device_id")
        final_status = message.get("status", TaskStatus.COMPLETED.value)

        logger.info(
            "Task lifecycle ended: task_id=%s device_id=%s final_status=%s",
            task_id, device_id, final_status,
        )

        # 清理残余 pending future（若设备未回 task_result 而直接送 task_end）
        if task_id and task_id in self._pending_responses:
            future = self._pending_responses.pop(task_id)
            if not future.done():
                future.set_result(message)

        async with self._lock:
            if device_id and device_id in self._devices:
                self._devices[device_id].current_task_id = None

        return {
            "version": "3.0",
            "type": "task_end_ack",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "task_id": task_id,
            "timestamp": int(time.time() * 1000),
            "status": "acknowledged",
        }
    
    async def _handle_task_progress(self, websocket: Any, message: Dict[str, Any]) -> None:
        """处理任务进度"""
        task_id = message.get("task_id")
        progress = message.get("progress", 0)
        logger.debug(f"Task progress: {task_id} - {progress}%")
    
    async def _handle_command_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        """处理命令结果"""
        message_id = message.get("message_id")
        
        if message_id in self._pending_responses:
            future = self._pending_responses.pop(message_id)
            if not future.done():
                future.set_result(message)
    
    async def _handle_error(self, websocket: Any, message: Dict[str, Any]) -> None:
        """处理错误消息，使用结构化日志输出"""
        device_id = message.get("device_id")
        error_code = message.get("error_code")
        error_message = message.get("error_message")
        details = message.get("details")
        task_id = message.get("task_id")

        logger.error(
            "Error from device: device_id=%s error_code=%s error_message=%s task_id=%s details=%s",
            device_id, error_code, error_message, task_id, details,
        )

    async def _handle_generic_forward(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """通用占位处理器：记录日志并返回 ACK（后续可扩展为实际转发逻辑）"""
        msg_type = message.get("type")
        device_id = message.get("device_id")
        logger.debug(f"Received {msg_type} from {device_id}: forwarding")
        return {
            "type": f"{msg_type}_ack" if msg_type else "ack",
            "device_id": device_id,
            "status": "received",
            "message_id": message.get("message_id"),
        }

    async def _handle_task_execute(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 task_execute 请求"""
        device_id = message.get("device_id")
        # task_id 优先；若客户端未提供则回退到 message_id（兼容旧版协议）
        task_id = message.get("task_id") or message.get("message_id")
        task_type = message.get("task_type", "generic")
        payload = message.get("payload", {})
        logger.info(f"Task execute request from {device_id}: task_id={task_id}, type={task_type}")

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = task_id

        return MessageBuilder.task_assign(
            device_id=device_id,
            task_id=task_id,
            task_type=task_type,
            payload=payload
        )

    async def _handle_agent_ping(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理 agent_ping 请求，返回 heartbeat_ack"""
        device_id = message.get("device_id")
        logger.debug(f"Agent ping from {device_id}")
        return MessageBuilder.heartbeat_ack(device_id)

    async def _handle_capability_report(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理设备能力上报，持久化 supported_actions 并同步到 CapabilityRegistry。

        能力命名规则（稳定且可被 LLM tool schema 使用）：
            ``gateway__<device_id>__<action_name>``
        """
        device_id = message.get("device_id")
        platform = message.get("platform")
        supported_actions = message.get("supported_actions", [])
        version = message.get("version")
        logger.info(f"Capability report from {device_id}: platform={platform}, "
                    f"actions={supported_actions}, version={version}")

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].supported_actions = list(supported_actions)
                self._devices[device_id].last_heartbeat = time.time()

        # Sync reported capabilities into the global CapabilityRegistry so the
        # LLM can discover and dispatch to this device via natural language.
        if device_id and supported_actions:
            try:
                from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
                reg = CapabilityRegistry.get_instance()
                for action in supported_actions:
                    action_str = action if isinstance(action, str) else str(action)
                    cap_name = f"gateway__{device_id}__{action_str}"
                    reg.register(CapabilityItem(
                        name=cap_name,
                        description=f"Android device {device_id} action: {action_str} (platform={platform})",
                        source="gateway",
                        source_id=device_id,
                        available=True,
                        metadata={"device_id": device_id, "platform": platform, "action": action_str},
                    ))
                logger.info(
                    "capability_report: synced %d actions for device %s to CapabilityRegistry",
                    len(supported_actions),
                    device_id,
                )
            except Exception as sync_err:
                logger.warning("capability_report: CapabilityRegistry sync failed: %s", sync_err)

        return MessageBuilder.capability_report_ack(
            device_id=device_id or "unknown",
            accepted=True,
            message="capability_report accepted",
        )

    async def _handle_diagnostics_payload(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理诊断数据上报"""
        device_id = message.get("device_id")
        error_type = message.get("error_type")
        error_context = message.get("error_context")
        task_id = message.get("task_id")
        node_name = message.get("node_name")
        logger.warning(f"Diagnostics from {device_id}: error_type={error_type}, "
                       f"task_id={task_id}, node={node_name}, context={error_context}")

        return MessageBuilder.diagnostics_payload_ack(
            device_id=device_id or "unknown",
            accepted=True,
            message="diagnostics_payload accepted",
        )

    async def _handle_vision_request(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理视觉请求：Android 上传截图 → VisionPipeline 分析 → task_assign 回推"""
        device_id = message.get("device_id")
        task_id = message.get("task_id") or message.get("message_id") or str(uuid.uuid4())
        image_base64 = message.get("image_base64", "")
        mode = message.get("mode", "full")
        task_context = message.get("task_context", "")

        logger.info(f"Vision request from {device_id}: task_id={task_id}, mode={mode}")

        if not image_base64:
            return MessageBuilder.error(
                device_id or "unknown",
                "VISION_NO_IMAGE",
                "image_base64 is required for vision_request",
            )

        # 调用 VisionPipeline 进行分析
        vision_payload: Dict[str, Any] = {}
        try:
            from core.vision_pipeline import VisionPipeline
            pipeline = VisionPipeline()
            vision_result = await pipeline.understand(
                image_base64=image_base64,
                mode=mode,
                task_context=task_context,
            )
            vision_payload = {
                "success": vision_result.success,
                "analysis": vision_result.to_dict() if hasattr(vision_result, "to_dict") else {
                    k: v for k, v in vars(vision_result).items() if not k.startswith("_")
                },
            }
        except Exception as e:
            logger.warning(f"VisionPipeline unavailable, returning raw error: {e}")
            vision_payload = {"success": False, "error": str(e)}

        # 以 task_assign 形式把结果回推给 Android 设备
        response = MessageBuilder.vision_result(
            device_id=device_id or "unknown",
            task_id=task_id,
            result=vision_payload,
        )

        # 通过 WebSocket 主动推送（异步，不等待 ACK）
        try:
            if websocket is not None:
                await websocket.send_json(response)
        except Exception as e:
            logger.warning(f"Failed to push vision_result to {device_id}: {e}")

        return response
    
    # =========================================================================
    # 公共 API
    # =========================================================================
    
    async def send_to_device(self, device_id: str, message: Dict[str, Any],
                            wait_response: bool = False,
                            timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """发送消息到设备"""
        async with self._lock:
            device = self._devices.get(device_id)
        
        if not device or not device.connected:
            logger.warning(f"Device not connected: {device_id}")
            return None
        
        try:
            # 发送消息
            await device.websocket.send_json(message)
            
            if wait_response:
                # 等待响应
                message_id = message.get("message_id") or message.get("task_id")
                future = asyncio.get_event_loop().create_future()
                self._pending_responses[message_id] = future
                
                try:
                    return await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    self._pending_responses.pop(message_id, None)
                    logger.warning(f"Response timeout for message: {message_id}")
                    return None
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Failed to send message to {device_id}: {e}")
            return None
    
    async def click(self, device_id: str, x: int, y: int,
                   element_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """在设备上执行点击"""
        msg = MessageBuilder.gui_click(device_id, x, y, element_id)
        return await self.send_to_device(device_id, msg, wait_response=True)
    
    async def swipe(self, device_id: str, start_x: int, start_y: int,
                   end_x: int, end_y: int, duration_ms: int = 300) -> Optional[Dict[str, Any]]:
        """在设备上执行滑动"""
        msg = MessageBuilder.gui_swipe(device_id, start_x, start_y, end_x, end_y, duration_ms)
        return await self.send_to_device(device_id, msg, wait_response=True)
    
    async def input_text(self, device_id: str, text: str,
                        element_id: Optional[str] = None,
                        clear_first: bool = False) -> Optional[Dict[str, Any]]:
        """在设备上输入文本"""
        msg = MessageBuilder.gui_input(device_id, text, element_id, clear_first)
        return await self.send_to_device(device_id, msg, wait_response=True)
    
    async def screenshot(self, device_id: str, quality: int = 80,
                        scale: float = 1.0) -> Optional[Dict[str, Any]]:
        """获取设备截图"""
        msg = MessageBuilder.gui_screenshot(device_id, quality, scale)
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=60.0)
    
    async def query_elements(self, device_id: str,
                            text: Optional[str] = None,
                            class_name: Optional[str] = None,
                            view_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """查询设备上的 UI 元素"""
        msg = MessageBuilder.gui_element_query(device_id, text, class_name, view_id)
        return await self.send_to_device(device_id, msg, wait_response=True)
    
    async def assign_task(self, device_id: str, task_id: str, task_type: str,
                         payload: Dict[str, Any], priority: int = 5,
                         timeout: int = 300) -> Optional[Dict[str, Any]]:
        """分配任务到设备"""
        msg = MessageBuilder.task_assign(device_id, task_id, task_type, payload, priority, timeout)
        
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = task_id
        
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=float(timeout))
    
    def get_device(self, device_id: str) -> Optional[AndroidDevice]:
        """获取设备信息"""
        return self._devices.get(device_id)
    
    def get_all_devices(self) -> List[AndroidDevice]:
        """获取所有设备"""
        return list(self._devices.values())
    
    def get_connected_devices(self) -> List[AndroidDevice]:
        """获取所有已连接的设备"""
        return [d for d in self._devices.values() if d.connected]
    
    def get_android_devices(self) -> List[AndroidDevice]:
        """获取所有 Android 设备"""
        return [d for d in self._devices.values() 
                if d.platform == DevicePlatform.ANDROID and d.connected]
    
    async def disconnect_device(self, device_id: str):
        """断开设备连接"""
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].connected = False
                self._devices[device_id].websocket = None
                logger.info(f"Device disconnected: {device_id}")
    
    async def cleanup_stale_devices(self, timeout_seconds: float = 120.0):
        """清理超时的设备"""
        current_time = time.time()
        stale_devices = []

        async with self._lock:
            for device_id, device in self._devices.items():
                if device.connected and (current_time - device.last_heartbeat) > timeout_seconds:
                    stale_devices.append(device_id)

        for device_id in stale_devices:
            await self.disconnect_device(device_id)
            logger.warning(f"Device timed out: {device_id}")

    async def reconnect_device(self, device_id: str, websocket: Any) -> bool:
        """重新连接设备（WebSocket 断线重连时调用）"""
        async with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                logger.warning(f"重连失败: 设备 {device_id} 未曾注册")
                return False
            device.websocket = websocket
            device.connected = True
            device.last_heartbeat = time.time()
        logger.info(f"设备重连成功: {device_id}")
        return True

    def get_device_health(self) -> Dict[str, Any]:
        """获取所有设备的健康状态摘要"""
        now = time.time()
        healthy = 0
        stale = 0
        disconnected = 0
        device_details = []
        for d in self._devices.values():
            if not d.connected:
                disconnected += 1
                status = "disconnected"
            elif now - d.last_heartbeat > 60:
                stale += 1
                status = "stale"
            else:
                healthy += 1
                status = "healthy"
            device_details.append({
                "device_id": d.device_id,
                "model": d.model,
                "status": status,
                "last_heartbeat_ago_s": round(now - d.last_heartbeat, 1) if d.last_heartbeat else None,
            })
        return {
            "total": len(self._devices),
            "healthy": healthy,
            "stale": stale,
            "disconnected": disconnected,
            "devices": device_details,
        }


# =============================================================================
# 全局实例
# =============================================================================

android_bridge = AndroidBridge()
