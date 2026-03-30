"""
AIP v3.0 协议模块 — 规范协议路径
====================================

**Canonical protocol path**: ``galaxy_gateway.protocol`` (this package).

The single authoritative protocol definition for the Galaxy system is
``galaxy_gateway.protocol.aip_v3`` (AIP v3.0).  All platform clients
(Android, Windows, Linux, iOS, cloud) must use this protocol definition.

Protocol authority chain::

    galaxy_gateway.protocol.aip_v3     — CANONICAL (AIP v3.0 types + helpers)
    galaxy_gateway.protocol.compat     — Shim: legacy → v3 conversion only
    galaxy_gateway.aip_protocol_v2     — HARD DISABLED (raises ImportError)

Do **not** import ``galaxy_gateway.aip_protocol_v2`` directly — it will raise
:class:`ImportError`.  Legacy message payloads can be normalized to v3 via::

    from galaxy_gateway.protocol.compat import parse_message_compat

导出所有协议相关的类和函数。
"""

from .compat import parse_message_compat, normalize_action_in_payload
from .normalized_ingress_event import (
    NormalizedIngressEvent,
    IngressEventKind,
    to_normalized_ingress_event,
    from_aip_message as ingress_event_from_aip_message,
    from_normalized_dict as ingress_event_from_dict,
)
from .actions import (
    ActionType,
    LEGACY_ACTION_MAP,
    ClickPayload,
    SwipePayload,
    ScrollPayload,
    TypePayload,
    KeyPressPayload,
    ScreenshotPayload,
    AppLaunchPayload,
    ShellPayload,
    ClipboardPayload,
    normalize_action_name,
    validate_action_payload,
    get_payload_schema,
)
from .aip_v3 import (
    # 枚举类型
    AIPDeviceType,
    AIPDeviceType as DeviceType,  # backward compat alias
    DevicePlatform,
    DeviceCapability,
    MessageType,
    TaskStatus,
    ResultStatus,

    # 数据结构
    Rect,
    UIElement,
    DeviceInfo,
    Command,
    CommandResult,
    AIPMessage,

    # 工具函数
    create_register_message,
    create_heartbeat_message,
    create_task_message,
    create_gui_click_message,
    create_gui_input_message,
    create_gui_scroll_message,
    create_screenshot_message,
    create_error_message,
    parse_message,
    validate_message,

    # Unified protocol bridge
    UnifiedMessageTypes,
)

__all__ = [
    # Legacy compat / shim
    "parse_message_compat",
    "normalize_action_in_payload",
    # PR-56: Canonical Normalized Ingress Event
    "NormalizedIngressEvent",
    "IngressEventKind",
    "to_normalized_ingress_event",
    "ingress_event_from_aip_message",
    "ingress_event_from_dict",
    # Canonical action vocabulary
    "ActionType",
    "LEGACY_ACTION_MAP",
    "ClickPayload",
    "SwipePayload",
    "ScrollPayload",
    "TypePayload",
    "KeyPressPayload",
    "ScreenshotPayload",
    "AppLaunchPayload",
    "ShellPayload",
    "ClipboardPayload",
    "normalize_action_name",
    "validate_action_payload",
    "get_payload_schema",
    # AIP v3 types
    "DeviceType",
    "DevicePlatform",
    "DeviceCapability",
    "MessageType",
    "TaskStatus",
    "ResultStatus",
    "Rect",
    "UIElement",
    "DeviceInfo",
    "Command",
    "CommandResult",
    "AIPMessage",
    "create_register_message",
    "create_heartbeat_message",
    "create_task_message",
    "create_gui_click_message",
    "create_gui_input_message",
    "create_gui_scroll_message",
    "create_screenshot_message",
    "create_error_message",
    "parse_message",
    "validate_message",
    "UnifiedMessageTypes",
]
