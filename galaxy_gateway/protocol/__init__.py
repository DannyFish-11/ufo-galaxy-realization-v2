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

from .actions import (
    LEGACY_ACTION_MAP,
    ActionType,
    AppLaunchPayload,
    ClickPayload,
    ClipboardPayload,
    KeyPressPayload,
    ScreenshotPayload,
    ScrollPayload,
    ShellPayload,
    SwipePayload,
    TypePayload,
    get_payload_schema,
    normalize_action_name,
    validate_action_payload,
)

# 从 .aip_v3 转出的符号分四类：枚举类型（AIPDeviceType / DevicePlatform /
# DeviceCapability / MessageType / TaskStatus / ResultStatus）、数据结构（Rect /
# UIElement / DeviceInfo / Command / CommandResult / AIPMessage）、消息构造与校验
# 工具函数（create_* / parse_message / validate_message），以及统一协议桥
# UnifiedMessageTypes。DeviceType 是 AIPDeviceType 的向后兼容别名。
#
# 分类说明写在这里而不是括号内：isort 会把括号内的分节注释collapse 成一条分号连
# 接的尾注释（"# 枚举类型; 数据结构; 工具函数; ..."），既丢失了原意，又让 isort
# 自身不再幂等 —— 跑完 isort+black 之后 isort 仍报未排序，两道门永远无法同时绿。
from .aip_v3 import AIPDeviceType
from .aip_v3 import AIPDeviceType as DeviceType
from .aip_v3 import (
    AIPMessage,
    Command,
    CommandResult,
    DeviceCapability,
    DeviceInfo,
    DevicePlatform,
    MessageType,
    Rect,
    ResultStatus,
    TaskStatus,
    UIElement,
    UnifiedMessageTypes,
    create_error_message,
    create_gui_click_message,
    create_gui_input_message,
    create_gui_scroll_message,
    create_heartbeat_message,
    create_register_message,
    create_screenshot_message,
    create_task_message,
    parse_message,
    validate_message,
)
from .compat import normalize_action_in_payload, parse_message_compat
from .ingress_classifier import INGRESS_CLASSIFIER_AUTHORITY, IngressMessageClass, classify_ingress_kind
from .normalized_ingress_event import IngressEventKind, NormalizedIngressEvent
from .normalized_ingress_event import from_aip_message as ingress_event_from_aip_message
from .normalized_ingress_event import from_normalized_dict as ingress_event_from_dict
from .normalized_ingress_event import to_normalized_ingress_event

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
