"""
Android Bridge Service — Android 动作适配器（PR-S4）
=======================================================

架构角色
--------
``AndroidBridge`` 是一个 **Android-specific action / payload 翻译适配器**，
不是独立的 presence 或 dispatch authority。

职责（保留）:
  1. 处理 AIP v3 WebSocket 协议的收发与规范化。
  2. 将服务端任务翻译为 Android 可执行的 AIP 命令（action/payload translation）。
  3. 处理安卓端返回的结果并触发记忆回流。
  4. 维护 WebSocket 连接句柄的 **传输/会话层本地缓存**（transport session cache）。

职责（已移除 — PR-2 / PR-S3 / PR-S4）:
  ✗ 不持有独立的设备 presence 权威（presence authority 在 UDM + UCM）。
  ✗ 不持有独立的任务 dispatch 权威（dispatch authority 在 DeviceRouter）。
  ✗ ``self._devices`` 不是设备事实来源（SSOT 在 UDM）。

与安卓端 AIPMessageV3.kt 完全对齐。

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
    def goal_execution_result(cls, device_id: str, payload: Dict[str, Any],
                              correlation_id: Optional[str] = None,
                              trace_id: Optional[str] = None) -> Dict[str, Any]:
        """goal_execution / parallel_subtask 结果回传（Android → Gateway）

        对应 Android GoalResultPayload，字段：
            task_id, correlation_id, status, result, details,
            group_id, subtask_index, latency_ms, device_id, device_role, steps
        """
        msg = cls._base_message(MessageType.GOAL_EXECUTION_RESULT, device_id)
        msg["payload"] = payload
        if correlation_id:
            msg["correlation_id"] = correlation_id
        if trace_id:
            msg["trace_id"] = trace_id
        return msg

    @classmethod
    def task_progress(cls, device_id: str, task_id: str,
                      progress: float, step: int = 0,
                      message: str = "") -> Dict[str, Any]:
        """任务进度上报"""
        msg = cls._base_message(MessageType.TASK_PROGRESS, device_id)
        msg["task_id"] = task_id
        msg["progress"] = progress
        msg["step"] = step
        if message:
            msg["message"] = message
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
    Android 桥接服务 — transport registration + runtime presence adapter。

    负责管理所有安卓设备的连接、任务分发和结果收集。

    架构角色 (PR-2)
    ---------------
    AndroidBridge 是 **transport/session adapter**，不是独立的设备事实源。

    - 设备注册 / 心跳 / 断联 / 重连的 **canonical 状态写入** 经由
      ``UnifiedDeviceManager`` (UDM) 完成，UDM 是唯一的写入 SSOT。
    - ``self._devices`` 仅保留为 **transport/session operational cache**，
      用于维护 WebSocket 连接句柄与轻量级连接态，不再充当主设备注册表。
    - 所有外部代码若需要权威设备状态，应查询 UDM，而非直接读取 ``_devices``。
    """
    
    def __init__(self):
        # transport/session operational cache — NOT the canonical device registry.
        # Use UnifiedDeviceManager (UDM) as the authoritative device state store.
        self._devices: Dict[str, AndroidDevice] = {}
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._lock = asyncio.Lock()
        
        # 注册默认处理器
        self._register_default_handlers()
        
        logger.info("AndroidBridge initialized")

    # =========================================================================
    # UDM canonical write/patch helpers (PR-2)
    # =========================================================================

    def _write_registration_to_udm(self, device_id: str, message: Dict[str, Any]) -> None:
        """Write canonical device identity/state to UnifiedDeviceManager on registration.

        This is the authoritative canonical write path for Android device
        registration.  The local ``_devices`` transport cache is updated
        *after* this call succeeds.

        Args:
            device_id: The device identifier extracted from the registration message.
            message:   The normalised AIP v3 registration payload.
        """
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            from core.unified.models import UnifiedDevice, UnifiedDeviceType

            udm = UnifiedDeviceManager()

            # Normalise capabilities bitmask → string list
            raw_caps = message.get("capabilities", 0)
            if isinstance(raw_caps, int):
                caps_list = DeviceCapability.to_list(raw_caps)
            elif isinstance(raw_caps, (list, tuple)):
                caps_list = [str(c) for c in raw_caps]
            else:
                caps_list = []

            # Determine device_type
            raw_device_type = str(message.get("device_type", "android_phone")).lower()
            try:
                utype = UnifiedDeviceType(raw_device_type)
            except ValueError:
                utype = UnifiedDeviceType.ANDROID

            metadata = {
                "model": message.get("model", ""),
                "os_version": message.get("os_version", ""),
                "sdk_version": message.get("sdk_version"),
                "screen_width": message.get("screen_width"),
                "screen_height": message.get("screen_height"),
                "platform": message.get("platform", "android"),
                "app_version": message.get("app_version", ""),
            }
            # Drop None values to keep metadata clean
            metadata = {k: v for k, v in metadata.items() if v is not None}

            device = UnifiedDevice(
                device_id=device_id,
                device_name=str(message.get("name") or "Android Device"),
                device_type=utype,
                capabilities=caps_list,
                metadata=metadata,
                source="android_bridge",
            )
            udm.register_device(device)
            logger.info(
                "android_bridge: wrote registration to UDM (SSOT): device_id=%s",
                device_id,
                extra={"event": "android_bridge_udm_register", "device_id": device_id},
            )
        except Exception as exc:
            logger.warning(
                "android_bridge: UDM registration write failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_runtime_state_to_udm(
        self,
        device_id: str,
        patch: Dict[str, Any],
        source: str = "android_bridge",
    ) -> None:
        """Patch canonical runtime state in UnifiedDeviceManager.

        Args:
            device_id: Target device identifier.
            patch:     Partial state fields to update (see UDM ``upsert_device_state`` docs).
            source:    Source label for audit trail.
        """
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            result = udm.upsert_device_state(device_id, patch, source=source)
            if result is None:
                logger.debug(
                    "android_bridge: _patch_runtime_state_to_udm: device not in UDM yet, skipping: %s",
                    device_id,
                )
        except Exception as exc:
            logger.warning(
                "android_bridge: UDM state patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_heartbeat_to_udm(self, device_id: str) -> None:
        """Record heartbeat in UDM canonical state (updates last_heartbeat + keeps ONLINE).

        Also updates the UCM presence backbone (last_seen + routable).

        Args:
            device_id: Device that sent the heartbeat.
        """
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            UnifiedDeviceManager().heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UDM heartbeat patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

        # ── Presence backbone: update UCM last_seen / routable ──
        try:
            from core.unified.connection_manager import get_unified_connection_manager
            get_unified_connection_manager().update_heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM heartbeat patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_disconnect_to_udm(self, device_id: str) -> None:
        """Mark device as DISCONNECTED in UDM without removing canonical identity.

        Also marks the device offline in UCM presence backbone.

        Args:
            device_id: Device that disconnected.
        """
        self._patch_runtime_state_to_udm(
            device_id,
            {"status": "disconnected"},
            source="android_bridge_disconnect",
        )

        # ── Presence backbone: mark offline in UCM ──
        try:
            from core.unified.connection_manager import get_unified_connection_manager
            get_unified_connection_manager().mark_offline(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM mark_offline failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_reconnect_to_udm(self, device_id: str) -> None:
        """Mark device as ONLINE in UDM on reconnect (no duplicate identity created).

        Also patches the UCM presence backbone so routable=True is restored.

        Args:
            device_id: Device that reconnected.
        """
        self._patch_runtime_state_to_udm(
            device_id,
            {"status": "online"},
            source="android_bridge_reconnect",
        )

        # ── Presence backbone: update UCM heartbeat to restore routable ──
        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
            # Attempt update_heartbeat; if device isn't in UCM yet, that's OK
            ucm.update_heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM reconnect patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )
    
    # ─────────────────────────────────────────────────────────────────────────
    #  设备 Fan-out 辅助方法（PARALLEL_SUBTASK / 多设备协作）
    # ─────────────────────────────────────────────────────────────────────────

    async def _fan_out_task_assign(
        self,
        task_id: str,
        task_type: str,
        goal: str,
        device_ids: List[str],
        session_id: str,
        trace_id: str,
        max_steps: int = 10,
        constraints: Optional[List[str]] = None,
        group_id: Optional[str] = None,
        require_local_agent: bool = True,
    ) -> Dict[str, Any]:
        """将 task_assign 扇出（fan-out）到多台设备。

        用于 PARALLEL_SUBTASK 的服务器端 fan-out：
        1. 查询 UnifiedDeviceManager 获取目标设备的 WebSocket 连接
        2. 向每台设备下发独立的 task_assign（包含 subtask_index）
        3. 返回汇总状态（而非等待所有设备完成）

        注意：这是 fire-and-forget 的异步广播，不等待设备执行结果。
        设备执行完毕后通过 GOAL_EXECUTION_RESULT 回传结果。

        Args:
            task_id: 父任务 ID
            task_type: task_assign 类型（parallel_subtask / goal_execution）
            goal: 自然语言目标
            device_ids: 目标设备 ID 列表
            session_id: 会话 ID
            trace_id: 追踪 ID
            max_steps: 最大步数
            constraints: 约束条件
            group_id: 分组 ID（用于结果汇聚）
            require_local_agent: 是否要求本地执行

        Returns:
            汇总状态（fan-out 到的设备数 / 失败数）
        """
        constraints = constraints or []
        results = {"fanout": 0, "failed": 0, "device_ids": [], "errors": []}

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
        except Exception as ucm_err:
            logger.warning(
                "PARALLEL_SUBTASK fan-out: UCM 不可用，跳过 fan-out | error=%s",
                ucm_err,
            )
            return {"fanout": 0, "failed": len(device_ids), "device_ids": [], "errors": [str(ucm_err)]}

        for idx, device_id in enumerate(device_ids):
            try:
                task_assign_payload: Dict[str, Any] = {
                    "task_id": task_id,
                    "goal": goal,
                    "constraints": constraints,
                    "max_steps": max_steps,
                    "require_local_agent": require_local_agent,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "runtime_session_id": trace_id,
                    "success": True,
                    "group_id": group_id,
                    "subtask_index": idx,  # 每台设备分配不同 subtask_index
                }

                msg = MessageBuilder.task_assign(
                    device_id=device_id,
                    task_id=task_id,
                    task_type=task_type,
                    payload=task_assign_payload,
                )
                msg["trace_id"] = trace_id
                msg["session_id"] = session_id

                # 通过 UCM 查找设备的 WebSocket 连接并下发
                sent = await ucm.send_to_device(device_id, msg)
                if sent:
                    results["fanout"] += 1
                    results["device_ids"].append(device_id)
                    logger.debug(
                        "PARALLEL_SUBTASK fan-out → device_id=%s subtask_index=%s",
                        device_id, idx,
                    )
                else:
                    results["failed"] += 1
                    results["errors"].append(f"device {device_id}: WebSocket not connected")

            except Exception as fan_err:
                results["failed"] += 1
                results["errors"].append(f"device {device_id}: {fan_err}")
                logger.warning(
                    "PARALLEL_SUBTASK fan-out → device_id=%s failed: %s",
                    device_id, fan_err,
                )

        logger.info(
            "PARALLEL_SUBTASK fan-out 完成: fanout=%s failed=%s total=%s",
            results["fanout"], results["failed"], len(device_ids),
        )
        return results

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
        self._message_handlers[MessageType.TASK_SUBMIT] = self._handle_task_submit
        self._message_handlers[MessageType.GOAL_EXECUTION] = self._handle_goal_execution
        self._message_handlers[MessageType.PARALLEL_SUBTASK] = self._handle_parallel_subtask
        self._message_handlers[MessageType.GOAL_EXECUTION_RESULT] = self._handle_goal_execution_result
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
        1. 通过 compat 层将所有协议版本（AIP/1.0、2.0、3.0）统一规范化为 AIP v3 dict。
           legacy 消息（无 version 字段或 version < 3.0）在此处被转换；
           纯 v3 消息直接透传。
        2. 检查强制字段（type、device_id）——缺失时返回带明确错误码的 error 消息。
        3. 派发到对应处理器。
        """
        # Step 1 — Normalise to AIP v3 via compat layer.
        # Legacy (v1/v2) messages are converted here; v3 messages pass through unchanged.
        # This is the single authoritative normalisation point: no legacy parsing
        # branches exist below this line.
        # normalise_to_v3_dict is used (not parse_message_compat) so that
        # extra application-level fields (platform, model, etc.) are preserved.
        device_id_pre = message.get("device_id", "unknown") if isinstance(message, dict) else "unknown"
        try:
            from galaxy_gateway.protocol.compat import normalise_to_v3_dict
            message = normalise_to_v3_dict(message)
        except Exception as norm_err:
            logger.warning(
                "android_bridge: failed to normalise message via compat: %s", norm_err,
                extra={
                    "event": "aip_normalise_error",
                    "device_id": device_id_pre,
                    "reason": str(norm_err),
                },
            )
            return MessageBuilder.error(
                device_id_pre,
                "PROTOCOL_PARSE_ERROR",
                f"Failed to parse message: {norm_err}",
                details={"reason": str(norm_err)},
            )

        device_id = message.get("device_id")
        msg_type_str = message.get("type")

        # Step 2 — Validate hard-required fields; return an explicit error when absent.
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

        # Step 3 — Resolve the MessageType enum value.
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
        """处理设备注册，失败时向网关日志输出结构化错误。

        Registration flow (PR-2):
        1. Write canonical identity/state to UDM (SSOT).
        2. Update local ``_devices`` as transport/session cache only.
        """
        device_id = message.get("device_id")

        try:
            # Step 1 — canonical write to UDM (SSOT); must happen before local cache update.
            self._write_registration_to_udm(device_id, message)

            # Step 2 — update local transport/session cache.
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
        """处理心跳，未注册设备仍回 ACK 并输出警告。

        Heartbeat flow (PR-2):
        1. Patch canonical runtime state in UDM (last_heartbeat + ONLINE).
        2. Keep local transport cache in sync for operational use.
        """
        device_id = message.get("device_id")

        # Step 1 — canonical patch to UDM.
        self._patch_heartbeat_to_udm(device_id)

        # Step 2 — update local transport cache.
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
        """处理设备状态上报（battery, cpu, memory 等）。

        Status update flow (PR-2):
        1. Patch canonical runtime state in UDM (last_heartbeat + metadata).
        2. Keep local transport cache in sync.
        """
        device_id = message.get("device_id")
        status_payload = message.get("status") or message.get("payload") or {}

        # Step 1 — canonical patch to UDM (merge status metadata, update last_seen).
        if device_id:
            meta_patch: Dict[str, Any] = {}
            if isinstance(status_payload, dict) and status_payload:
                meta_patch["metadata"] = {"device_status_report": status_payload}
            self._patch_runtime_state_to_udm(device_id, meta_patch, source="android_bridge_status")

        # Step 2 — update local transport cache.
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

    async def _handle_task_submit(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 TASK_SUBMIT — Android → Gateway 的自然语言任务提交。

        AIP v3 链路：Step 3 (Android → Gateway) — Android 发送 task_submit，
        Gateway 内部通过 DesktopPresenceRuntime → OpenClawd 处理，
        然后返回 task_assign（Step 6: Gateway → Android）。

        Android payload 格式（TaskSubmitPayload）:
            task_text: str       — 自然语言任务描述
            device_id: str       — 设备标识
            session_id: str      — 会话标识
            task_id: str         — 任务 ID（可选）
            context: dict        — 额外上下文

        返回 task_assign 消息，Android 端据此执行本地闭环自动化
        或将 goal 继续用于后续 command_result 上报。
        """
        payload = message.get("payload", {})
        device_id = message.get("device_id") or payload.get("device_id", "unknown")
        session_id = payload.get("session_id") or message.get("session_id") or "android_default"
        trace_id = message.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
        task_id = payload.get("task_id") or message.get("task_id") or str(uuid.uuid4())
        task_text = payload.get("task_text", "").strip()

        if not task_text:
            return MessageBuilder.error(
                device_id,
                "INVALID_TASK_SUBMIT",
                "task_submit missing or empty 'task_text' field",
                correlation_id=task_id,
            )

        logger.info(
            "TASK_SUBMIT received: task_id=%s device_id=%s session_id=%s text=%r",
            task_id, device_id, session_id, task_text[:80],
        )

        # ── 通过 DesktopPresenceRuntime（runtime shell）→ OpenClawd（subject core）处理 ──
        result: Dict[str, Any] = {
            "success": False,
            "response": "Processing failed",
        }

        # entry_mode 决定是否允许 Android 桥接到远程 Agent Runtime
        # "local" → require_local_agent=True（Android 本地执行闭环）
        # "cross_device" → require_local_agent=False（Android 尝试 AgentRuntimeBridge 远程执行）
        entry_mode = str(message.get("entry_mode", "local")).lower()
        require_local_agent = (entry_mode == "local")

        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            runtime = get_desktop_presence_runtime()
            result = await runtime.handle_request(
                message=task_text,
                source="chat",
                device_id=device_id,
                session_id=session_id,
                runtime_session_id=trace_id,
                entry_mode=entry_mode,
            )
        except Exception as runtime_err:
            logger.error(
                "TASK_SUBMIT: DesktopPresenceRuntime 处理失败 | task_id=%s error=%s",
                task_id, runtime_err, exc_info=True,
            )
            return MessageBuilder.error(
                device_id,
                "RUNTIME_ERROR",
                f"Subject core processing error: {runtime_err}",
                correlation_id=task_id,
            )

        # ── 从 OpenClawd 结果中提取字段，构建 task_assign 返回 ──
        success = result.get("success", False)
        response_text = result.get("response", "") or str(result.get("reply", ""))
        runtime_session_id = result.get("runtime_session_id", "")

        # 当本地执行失败或 OpenClawd 无响应时，fallback 到 Android 本地执行
        if not success or response_text == "":
            require_local_agent = True

        # 将 OpenClawd 返回的自然语言响应作为 goal 传给 Android
        goal = response_text if response_text else task_text
        constraints: List[str] = []
        if not success:
            constraints.append(f"Processing failed: {result.get('error', 'unknown error')}")
        if runtime_session_id:
            constraints.append(f"session: {runtime_session_id}")

        task_assign_payload: Dict[str, Any] = {
            "task_id": task_id,
            "goal": goal,
            "constraints": constraints,
            "max_steps": 10,
            "require_local_agent": require_local_agent,
            "trace_id": trace_id,
            "session_id": session_id,
            "runtime_session_id": runtime_session_id,
            "success": success,
        }

        logger.info(
            "TASK_SUBMIT → task_assign: task_id=%s require_local_agent=%s goal=%r",
            task_id, require_local_agent, goal[:80],
        )

        return MessageBuilder.task_assign(
            device_id=device_id,
            task_id=task_id,
            task_type="task_submit",
            payload=task_assign_payload,
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  GOAL_EXECUTION — 高层自主目标执行（AIP v3 Phase 3）
    #  链路: Android → Gateway → DesktopPresenceRuntime → TASK_ASSIGN → Android
    #        Android 执行 → GOAL_EXECUTION_RESULT → Gateway
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_goal_execution(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 GOAL_EXECUTION — Android 高层自治目标下发。

        与 _handle_task_submit 类似，但专用于 goal_execution 类型：
        1. 解析 GoalExecutionPayload（goal / task_id / group_id / subtask_index 等）
        2. 通过 DesktopPresenceRuntime 处理
        3. 返回 task_assign（Android 据此执行本地 goal）

        Android → Python payload 字段（GoalExecutionPayload）：
            goal: str              自然语言目标描述
            task_id: str           任务 ID
            group_id: str?         分组 ID（多设备并行时使用）
            subtask_index: int?    组内序号（多设备并行时使用）
            max_steps: int         最大步数（默认 10）
            timeout_ms: int?       超时毫秒
            constraints: List[str] 约束条件
            metadata: Dict         额外元数据
        """
        payload = message.get("payload", {})
        device_id = message.get("device_id") or payload.get("device_id", "unknown")
        session_id = payload.get("session_id") or message.get("session_id") or "android_default"
        trace_id = payload.get("trace_id") or message.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
        task_id = payload.get("task_id") or message.get("task_id") or str(uuid.uuid4())
        goal = payload.get("goal", "").strip()

        if not goal:
            return MessageBuilder.error(
                device_id,
                "INVALID_GOAL_EXECUTION",
                "goal_execution missing or empty 'goal' field",
                correlation_id=task_id,
            )

        logger.info(
            "GOAL_EXECUTION received: task_id=%s device_id=%s group_id=%s goal=%r",
            task_id, device_id, payload.get("group_id"), goal[:80],
        )

        # 通过 DesktopPresenceRuntime 处理
        result: Dict[str, Any] = {"success": False, "response": ""}
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            runtime = get_desktop_presence_runtime()
            result = await runtime.handle_request(
                message=goal,
                source="chat",
                device_id=device_id,
                session_id=session_id,
                runtime_session_id=trace_id,
                entry_mode="local",
            )
        except Exception as runtime_err:
            logger.error(
                "GOAL_EXECUTION: DesktopPresenceRuntime 处理失败 | task_id=%s error=%s",
                task_id, runtime_err, exc_info=True,
            )
            return MessageBuilder.error(
                device_id,
                "RUNTIME_ERROR",
                f"Subject core processing error: {runtime_err}",
                correlation_id=task_id,
            )

        # 从结果中提取字段，构建 task_assign 下发 Android
        success = result.get("success", False)
        response_text = result.get("response", "") or str(result.get("reply", ""))
        runtime_session_id = result.get("runtime_session_id", "")

        goal_task_assign_payload: Dict[str, Any] = {
            "task_id": task_id,
            "goal": response_text if response_text else goal,
            "constraints": payload.get("constraints", []),
            "max_steps": payload.get("max_steps", 10),
            "require_local_agent": True,  # goal_execution 强制本地执行
            "trace_id": trace_id,
            "session_id": session_id,
            "runtime_session_id": runtime_session_id,
            "success": success,
            "group_id": payload.get("group_id"),
            "subtask_index": payload.get("subtask_index"),
        }

        logger.info(
            "GOAL_EXECUTION → task_assign: task_id=%s goal=%r",
            task_id, response_text[:80] if response_text else goal[:80],
        )

        return MessageBuilder.task_assign(
            device_id=device_id,
            task_id=task_id,
            task_type="goal_execution",
            payload=goal_task_assign_payload,
        )

    # ─────────────────────────────────────────────────────────────────────────
    #  PARALLEL_SUBTASK — 多设备并行任务子项（AIP v3 Phase 3）
    #  链路: Android → Gateway → (分发到多设备) → GOAL_EXECUTION_RESULT → Gateway
    #  注意: Android GalaxyConnectionService 直接在设备端执行 parallel_subtask，
    #  Gateway 此处负责协调分发（实际分发逻辑由 Node_71 处理）
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_parallel_subtask(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 PARALLEL_SUBTASK — 服务器端多设备 Fan-out 协调。

        与 goal_execution 的区别：
        - parallel_subtask 有 group_id + subtask_index，用于结果汇聚
        - 服务器端做 fan-out：查询所有已连接设备，向每台设备下发独立的 task_assign

        流程：
        1. 解析 parallel_subtask payload
        2. 通过 DesktopPresenceRuntime 将 goal 转换为可执行文本
        3. 查询 UnifiedDeviceManager 获取所有已连接的 Android 设备
        4. 向每台设备发送独立的 task_assign（包含 subtask_index）
        5. 返回 fan-out 结果（异步，不等待设备执行完成）

        Android 端每个设备执行完子任务后，通过 GOAL_EXECUTION_RESULT 回传结果。
        """
        payload = message.get("payload", {})
        device_id = message.get("device_id") or payload.get("device_id", "unknown")
        session_id = payload.get("session_id") or message.get("session_id") or "android_default"
        trace_id = payload.get("trace_id") or message.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
        task_id = payload.get("task_id") or message.get("task_id") or str(uuid.uuid4())
        goal = payload.get("goal", "").strip()
        group_id = payload.get("group_id") or f"group_{uuid.uuid4().hex[:8]}"
        constraints = payload.get("constraints", [])
        max_steps = payload.get("max_steps", 10)

        if not goal:
            return MessageBuilder.error(
                device_id,
                "INVALID_PARALLEL_SUBTASK",
                "parallel_subtask missing or empty 'goal' field",
                correlation_id=task_id,
            )

        logger.info(
            "PARALLEL_SUBTASK received: task_id=%s device_id=%s group_id=%s goal=%r",
            task_id, device_id, group_id, goal[:80],
        )

        # ── Step 1: 通过 DesktopPresenceRuntime 规范化 goal ──────────────
        result: Dict[str, Any] = {"success": False, "response": ""}
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            runtime = get_desktop_presence_runtime()
            result = await runtime.handle_request(
                message=goal,
                source="chat",
                device_id=device_id,
                session_id=session_id,
                runtime_session_id=trace_id,
                entry_mode="local",
            )
        except Exception as runtime_err:
            logger.error(
                "PARALLEL_SUBTASK: DesktopPresenceRuntime 处理失败 | task_id=%s error=%s",
                task_id, runtime_err, exc_info=True,
            )
            return MessageBuilder.error(
                device_id,
                "RUNTIME_ERROR",
                f"Subject core processing error: {runtime_err}",
                correlation_id=task_id,
            )

        response_text = result.get("response", "") or str(result.get("reply", ""))
        runtime_session_id = result.get("runtime_session_id", "")

        # ── Step 2: 查询所有已连接设备 ───────────────────────────────────
        all_device_ids: List[str] = []
        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
            # 过滤 Android 设备（ANDROID 类型）
            # get_all_devices() 返回 Dict[device_id, device_info]
            all_device_ids = [
                device_id
                for device_id, d in ucm.get_all_devices().items()
                if d.get("device_type", "").upper() in ("ANDROID", "MOBILE", "PHONE")
                or device_id.startswith("android_")
                or d.get("online")  # 只要在线的都考虑
            ]
            logger.debug(
                "PARALLEL_SUBTASK: 发现 %d 台 Android 设备",
                len(all_device_ids),
            )
        except Exception as ucm_err:
            logger.warning(
                "PARALLEL_SUBTASK: UCM 查询失败，使用空设备列表 | error=%s",
                ucm_err,
            )

        # 排除当前发送者设备（避免重复执行）
        target_device_ids = [d for d in all_device_ids if d != device_id]

        # ── Step 3: Fan-out 到多台设备 ───────────────────────────────────
        fanout_summary: Dict[str, Any] = {"fanout": 0, "failed": 0, "device_ids": [], "errors": []}
        if target_device_ids:
            fanout_summary = await self._fan_out_task_assign(
                task_id=task_id,
                task_type="parallel_subtask",
                goal=response_text if response_text else goal,
                device_ids=target_device_ids,
                session_id=session_id,
                trace_id=trace_id,
                max_steps=max_steps,
                constraints=constraints,
                group_id=group_id,
                require_local_agent=True,
            )
        else:
            logger.info(
                "PARALLEL_SUBTASK: 无其他在线设备，fallback 到单设备执行 | task_id=%s",
                task_id,
            )

        # ── Step 4: 返回结果给调用方（fire-and-forget，不等待执行）───────
        if fanout_summary["fanout"] > 0:
            # 成功 fan-out，返回汇总（不阻塞等待设备执行）
            logger.info(
                "PARALLEL_SUBTASK → fan-out 成功: task_id=%s fanout=%s devices=%s",
                task_id, fanout_summary["fanout"], fanout_summary["device_ids"],
            )
            return MessageBuilder.goal_execution_result(
                device_id=device_id,
                payload={
                    "status": "dispatched",
                    "task_id": task_id,
                    "correlation_id": task_id,
                    "group_id": group_id,
                    "fanout_count": fanout_summary["fanout"],
                    "dispatched_to": fanout_summary["device_ids"],
                    "dispatch_failed": fanout_summary["failed"],
                    "runtime_session_id": runtime_session_id,
                    "message": f"Parallel task dispatched to {fanout_summary['fanout']} device(s)",
                },
                correlation_id=task_id,
                trace_id=trace_id,
            )
        else:
            # 无 fan-out 结果（无设备或 UCM 异常），fallback 到本地单设备执行
            parallel_task_assign_payload: Dict[str, Any] = {
                "task_id": task_id,
                "goal": response_text if response_text else goal,
                "constraints": constraints,
                "max_steps": max_steps,
                "require_local_agent": True,
                "trace_id": trace_id,
                "session_id": session_id,
                "runtime_session_id": runtime_session_id,
                "success": True,
                "group_id": group_id,
                "subtask_index": 0,
            }

            logger.info(
                "PARALLEL_SUBTASK → task_assign(fallback): task_id=%s goal=%r",
                task_id, response_text[:80] if response_text else goal[:80],
            )

            return MessageBuilder.task_assign(
                device_id=device_id,
                task_id=task_id,
                task_type="parallel_subtask",
                payload=parallel_task_assign_payload,
            )

    # ─────────────────────────────────────────────────────────────────────────
    #  GOAL_EXECUTION_RESULT — 结果回传（Android → Gateway）

    # ─────────────────────────────────────────────────────────────────────────
    #  GOAL_EXECUTION_RESULT — 结果回传（Android → Gateway）
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_goal_execution_result(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 GOAL_EXECUTION_RESULT — Android/设备执行结果回传。

        Android 执行完 goal_execution 或 parallel_subtask 后发送此消息。
        对应 Android: GoalResultPayload（见 AipModels.kt）

        Android payload 字段（GoalResultPayload）：
            task_id: str
            correlation_id: str (= task_id)
            status: str (success / failure / error / disabled)
            result: str?  成功时的结果摘要
            details: str? 错误详情
            group_id: str?
            subtask_index: int?
            latency_ms: int
            device_id: str
            device_role: str?
            steps: List[StepResult]

        处理策略：
        - 记录到 TaskMemory（供 LLM 上下文注入）
        - 记录到 cross_device_execution_chain（PR-7 规范链）
        - 触发 OpenClawd 反馈（如果有对话反馈路径）
        """
        payload = message.get("payload", {})
        device_id = message.get("device_id") or payload.get("device_id", "unknown")
        task_id = payload.get("task_id") or message.get("correlation_id") or "unknown"
        correlation_id = payload.get("correlation_id") or task_id
        trace_id = payload.get("trace_id") or message.get("trace_id") or ""
        status = payload.get("status", "unknown")
        result_text = payload.get("result") or payload.get("details", "")
        latency_ms = payload.get("latency_ms", 0)
        group_id = payload.get("group_id")
        subtask_index = payload.get("subtask_index")

        logger.info(
            "GOAL_EXECUTION_RESULT received: task_id=%s device_id=%s status=%s "
            "group_id=%s subtask_index=%s latency=%sms",
            task_id, device_id, status, group_id, subtask_index, latency_ms,
        )

        # ── 持久化到 TaskMemory（容错保护）─────────────────────────────
        if store_task_result is not None:
            try:
                await store_task_result(
                    task_id=task_id,
                    device_id=device_id,
                    status=status,
                    result=result_text,
                    trace_id=trace_id,
                    latency_ms=latency_ms,
                    route_mode=payload.get("route_mode", "cross_device"),
                    steps=payload.get("steps", []),
                )
                logger.debug(
                    "GOAL_EXECUTION_RESULT: task_memory 写入成功 task_id=%s",
                    task_id,
                )
            except Exception as mem_err:
                logger.warning(
                    "GOAL_EXECUTION_RESULT: task_memory 写入失败（非致命）task_id=%s error=%s",
                    task_id, mem_err,
                )
        else:
            logger.debug(
                "GOAL_EXECUTION_RESULT: store_task_result 不可用，跳过内存回流 task_id=%s",
                task_id,
            )

        # ── 触发 OpenClawd 反馈（如果有对应会话）────────────────────────
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            runtime = get_desktop_presence_runtime()
            if hasattr(runtime, "on_goal_execution_result"):
                await runtime.on_goal_execution_result(
                    task_id=task_id,
                    device_id=device_id,
                    status=status,
                    result=result_text,
                    trace_id=trace_id,
                )
        except Exception as feedback_err:
            logger.debug(
                "GOAL_EXECUTION_RESULT: OpenClawd 反馈失败（非致命）task_id=%s error=%s",
                task_id, feedback_err,
            )

        # GOAL_EXECUTION_RESULT 是最终回传（fire-and-forget），返回 None
        # Android 不等待响应，结果已通过 store_task_result 持久化
        return None

    async def _handle_agent_ping(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理 agent_ping 请求，返回 heartbeat_ack"""
        device_id = message.get("device_id")
        logger.debug(f"Agent ping from {device_id}")
        return MessageBuilder.heartbeat_ack(device_id)

    async def _handle_capability_report(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理设备能力上报，持久化 supported_actions 并同步到 CapabilityRegistry。

        能力命名规则（稳定且可被 LLM tool schema 使用）：
            ``gateway__<device_id>__<action_name>``

        新字段（Round 3）
        -----------------
        ``capability_schemas`` : list[dict]
            每个元素描述一条能力的完整 schema::

                {
                  "action"    : "tap",
                  "params"    : { ... },      # 可选 JSON Schema
                  "returns"   : { ... },      # 可选
                  "version"   : "1.0",        # 可选
                  "exec_mode" : "local",      # "local"|"remote"|"both"，缺省 "both"
                  "tags"      : ["ui", ...]   # 可选标签
                }

        若客户端仅上报 ``supported_actions``（旧格式），则以 exec_mode="both"
        补全，保持向后兼容。
        """
        device_id = message.get("device_id")
        platform = message.get("platform")
        supported_actions = message.get("supported_actions", [])
        version = message.get("version")
        # Round 3: structured per-action schemas (optional, new clients send this)
        capability_schemas: list = message.get("capability_schemas") or []

        logger.info(
            "Capability report from %s: platform=%s, actions=%s, version=%s, schemas=%d",
            device_id, platform, supported_actions, version, len(capability_schemas),
        )

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].supported_actions = list(supported_actions)
                self._devices[device_id].last_heartbeat = time.time()

        # ── 1. Sync to GatewayCapabilityRegistry (exec_mode-aware) ────────────
        if device_id:
            try:
                from galaxy_gateway.capability_registry import get_gateway_capability_registry
                gw_reg = get_gateway_capability_registry()

                # Build a lookup from action → schema_dict for new-format clients
                schema_by_action: dict = {}
                for schema_entry in capability_schemas:
                    if isinstance(schema_entry, dict) and schema_entry.get("action"):
                        schema_by_action[schema_entry["action"]] = schema_entry

                upserted = 0
                for action in supported_actions:
                    action_str = action if isinstance(action, str) else str(action)
                    schema_dict = schema_by_action.get(action_str, {})
                    # Carry top-level version if not per-action (avoid dict copy when unnecessary)
                    if version and not schema_dict.get("version"):
                        schema_dict = {**schema_dict, "version": str(version)}
                    gw_reg.upsert(device_id, action_str, schema_dict)
                    upserted += 1

                logger.info(
                    "capability_report: upserted %d capabilities for device %s to GatewayCapabilityRegistry",
                    upserted,
                    device_id,
                )
            except Exception as gw_sync_err:
                logger.warning(
                    "capability_report: GatewayCapabilityRegistry sync failed: %s", gw_sync_err
                )

        # ── 2. Sync to LLM CapabilityRegistry (unchanged — backward compat) ───
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
        """Android GUI action adapter — translate click to AIP protocol and send.

        This is an Android-specific action translation adapter (PR-S3).  It does
        not hold independent dispatch authority; it uses send_to_device() for
        the transport substrate within the AndroidBridge session layer.
        """
        msg = MessageBuilder.gui_click(device_id, x, y, element_id)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def swipe(self, device_id: str, start_x: int, start_y: int,
                   end_x: int, end_y: int, duration_ms: int = 300) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate swipe to AIP protocol and send.

        This is an Android-specific action translation adapter (PR-S3).
        """
        msg = MessageBuilder.gui_swipe(device_id, start_x, start_y, end_x, end_y, duration_ms)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def input_text(self, device_id: str, text: str,
                        element_id: Optional[str] = None,
                        clear_first: bool = False) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate text input to AIP protocol and send.

        This is an Android-specific action translation adapter (PR-S3).
        """
        msg = MessageBuilder.gui_input(device_id, text, element_id, clear_first)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def screenshot(self, device_id: str, quality: int = 80,
                        scale: float = 1.0) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate screenshot request to AIP protocol and send.

        This is an Android-specific action translation adapter (PR-S3).
        """
        msg = MessageBuilder.gui_screenshot(device_id, quality, scale)
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=60.0)

    async def query_elements(self, device_id: str,
                            text: Optional[str] = None,
                            class_name: Optional[str] = None,
                            view_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate element query to AIP protocol and send.

        This is an Android-specific action translation adapter (PR-S3).
        """
        msg = MessageBuilder.gui_element_query(device_id, text, class_name, view_id)
        return await self.send_to_device(device_id, msg, wait_response=True)
    
    async def assign_task(self, device_id: str, task_id: str, task_type: str,
                         payload: Dict[str, Any], priority: int = 5,
                         timeout: int = 300) -> Optional[Dict[str, Any]]:
        """分配任务到设备 — delegates dispatch authority to DeviceRouter (PR-S3).

        Android-specific task message construction (action translation) stays
        in AndroidBridge.  Dispatch authority is delegated to
        DeviceRouter.dispatch_task() as the canonical single dispatch entry.

        Falls back to direct send_to_device() only when the device is not
        registered in DeviceRouter (compatibility mode).
        """
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = task_id

        # PR-S3: delegate dispatch authority to DeviceRouter.
        try:
            from galaxy_gateway.device_router import device_router as _device_router
            router_device = _device_router.devices.get(device_id)
            if router_device is not None:
                task_dict = {
                    "task_id": task_id,
                    "payload": {
                        "task_type": task_type,
                        "priority": priority,
                        **payload,
                    },
                }
                return await _device_router.dispatch_task(task_dict, router_device)
        except Exception as _router_err:
            logger.warning(
                "AndroidBridge.assign_task: DeviceRouter dispatch failed, "
                "falling back to send_to_device — %s", _router_err
            )

        # Compatibility fallback: transport via AndroidBridge transport layer when
        # the device is not registered in DeviceRouter.
        msg = MessageBuilder.task_assign(device_id, task_id, task_type, payload, priority, timeout)
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=float(timeout))
    
    def get_device(self, device_id: str) -> Optional[AndroidDevice]:
        """获取设备的传输/会话层缓存条目（transport cache view）。

        ⚠️  Transport cache only — NOT the canonical device state.
        Use ``UnifiedDeviceManager.get_device(device_id)`` for authoritative
        device identity and runtime state.
        """
        return self._devices.get(device_id)
    
    def get_all_devices(self) -> List[AndroidDevice]:
        """获取所有设备的传输/会话层缓存列表（transport cache view）。

        ⚠️  Transport cache only — reflects only devices with an active
        WebSocket session in this AndroidBridge instance.
        Use ``UnifiedDeviceManager.list_devices()`` for the canonical device
        registry, which includes devices registered via other paths.
        """
        return list(self._devices.values())
    
    def get_connected_devices(self) -> List[AndroidDevice]:
        """获取已连接设备的传输/会话层缓存列表（transport cache view）。

        ⚠️  Transport cache only — reflects transport-layer connection state,
        not the authoritative presence state managed by UCM / UDM.
        """
        return [d for d in self._devices.values() if d.connected]
    
    def get_android_devices(self) -> List[AndroidDevice]:
        """获取 Android 平台设备的传输/会话层缓存列表（transport cache view）。

        ⚠️  Transport cache only — reflects only Android devices with an
        active WebSocket session in this AndroidBridge instance.
        Use ``UnifiedDeviceManager.get_devices_by_type()`` for the canonical
        registry view of all known Android devices.
        """
        return [d for d in self._devices.values() 
                if d.platform == DevicePlatform.ANDROID and d.connected]
    
    async def disconnect_device(self, device_id: str):
        """断开设备连接。

        Disconnect flow (PR-2):
        1. Patch canonical runtime state in UDM to DISCONNECTED (identity preserved).
        2. Clear WebSocket reference in local transport cache.
        """
        # Step 1 — canonical patch to UDM; identity is preserved, only status changes.
        self._patch_disconnect_to_udm(device_id)

        # Step 2 — clear transport/session cache entry.
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
        """重新连接设备（WebSocket 断线重连时调用）。

        Reconnect flow (PR-2):
        1. Patch canonical runtime state in UDM to ONLINE (no duplicate identity created).
        2. Restore WebSocket reference in local transport cache.

        Returns:
            True if the device was already registered; False otherwise.
        """
        async with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                logger.warning(f"重连失败: 设备 {device_id} 未曾注册")
                return False
            device.websocket = websocket
            device.connected = True
            device.last_heartbeat = time.time()

        # Step 1 — patch canonical UDM state to ONLINE; existing identity is reused.
        self._patch_reconnect_to_udm(device_id)

        logger.info(f"设备重连成功: {device_id}")
        return True

    def get_device_health(self) -> Dict[str, Any]:
        """获取所有设备的健康状态摘要（transport cache view）。

        ⚠️  Transport cache only — health scores are derived from the local
        WebSocket session state (last heartbeat, connected flag).  For the
        canonical device health registry (circuit breaker state, quarantine,
        consecutive failures), use ``DeviceHealthRegistry`` or the
        ``/api/v1/devices/{id}/health`` endpoint.
        """
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
