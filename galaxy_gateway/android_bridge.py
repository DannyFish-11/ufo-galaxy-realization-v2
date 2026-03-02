"""
Android Bridge Service
UFO Galaxy - 服务端与安卓端对接桥接层

此模块负责：
1. 处理安卓设备的注册和管理
2. 将服务端任务转换为安卓可执行的命令
3. 处理安卓端返回的结果
4. 维护安卓设备状态

与安卓端 AIPMessageV3.kt 完全对齐

Author: UFO Galaxy Team
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

class DeviceType(str, Enum):
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
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    CLOUD = "cloud"
    EMBEDDED = "embedded"
    UNKNOWN = "unknown"


# =============================================================================
# 消息类型定义 (与 AIPMessageV3.kt 完全对齐)
# =============================================================================

class MessageType(str, Enum):
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
    
    # === 错误处理 ===
    ERROR = "error"
    ERROR_RECOVERY = "error_recovery"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CONTINUE = "continue"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    NONE = "none"


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
    
    async def handle_message(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理来自安卓设备的消息"""
        msg_type_str = message.get("type")
        device_id = message.get("device_id")
        
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
            return await handler(websocket, message)
        else:
            logger.debug(f"No handler for message type: {msg_type}")
            return None
    
    async def _handle_device_register(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理设备注册"""
        device_id = message.get("device_id")
        
        async with self._lock:
            device = AndroidDevice.from_registration(message)
            device.websocket = websocket
            self._devices[device_id] = device
        
        logger.info(f"Android device registered: {device_id} ({device.model})")
        
        return MessageBuilder.device_register_ack(
            device_id=device_id,
            success=True,
            session_id=str(uuid.uuid4()),
            message="Registration successful"
        )
    
    async def _handle_heartbeat(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理心跳"""
        device_id = message.get("device_id")
        
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].last_heartbeat = time.time()
                self._devices[device_id].connected = True
        
        return MessageBuilder.heartbeat_ack(device_id)
    
    async def _handle_task_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        """处理任务结果"""
        task_id = message.get("task_id")
        device_id = message.get("device_id")
        
        logger.info(f"Task result received: {task_id} from {device_id}")
        
        # 完成等待的 Future
        if task_id in self._pending_responses:
            future = self._pending_responses.pop(task_id)
            if not future.done():
                future.set_result(message)
        
        # 更新设备状态
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = None
    
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
        """处理错误"""
        device_id = message.get("device_id")
        error_code = message.get("error_code")
        error_message = message.get("error_message")
        
        logger.error(f"Error from {device_id}: [{error_code}] {error_message}")
    
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


# =============================================================================
# 全局实例
# =============================================================================

android_bridge = AndroidBridge()
