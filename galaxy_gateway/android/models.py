"""
galaxy_gateway/android/models.py — Android device data models.

Extracted from android_bridge.py as part of PR-3 modularization.
Provides Rect, UIElement, and AndroidDevice dataclasses.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from galaxy_gateway.android.capabilities import DeviceCapability


# DeviceType / DevicePlatform — imported from canonical SSOT
from core.device_types import (  # noqa: E402
    AIPDeviceType as DeviceType,
    DevicePlatform,
)


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
            height=data.get("height", 0),
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
    supported_actions: List[str] = field(default_factory=list)
    # PR-7A: tracks whether capabilities were explicitly reported by the Android
    # device on registration, or whether the field carries its zero/absent default.
    # Absent capability evidence MUST NOT be treated as positive fitness evidence
    # by governance layers.
    capabilities_explicitly_reported: bool = False

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
            "capabilities_explicitly_reported": self.capabilities_explicitly_reported,
            "supported_actions": self.supported_actions,
            "connected": self.connected,
            "last_heartbeat": self.last_heartbeat,
            "current_task_id": self.current_task_id,
        }

    @classmethod
    def from_registration(cls, data: Dict) -> "AndroidDevice":
        """从注册消息创建设备

        PR-7A governance hardening: capabilities default to NONE (0) when the
        Android device does not report them.  Absent capability evidence must
        degrade governance decisions rather than be treated as an implicit grant
        of default capabilities.  Use ``capabilities_explicitly_reported`` to
        distinguish real evidence from the unverified absent state.
        """
        raw_caps = data.get("capabilities")
        if raw_caps is not None:
            caps = int(raw_caps)
            caps_reported = True
        else:
            # PR-7A: absent capability report → NONE, not optimistic default.
            caps = DeviceCapability.NONE
            caps_reported = False
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
            capabilities=caps,
            capabilities_explicitly_reported=caps_reported,
            connected=True,
            last_heartbeat=time.time(),
        )
