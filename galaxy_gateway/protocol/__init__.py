"""
AIP v3.0 协议模块

导出所有协议相关的类和函数
"""

from .aip_v3 import (
    # 枚举类型
    DeviceType,
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
    create_screenshot_message,
    create_error_message,
    parse_message,
    validate_message,
)

__all__ = [
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
    "create_screenshot_message",
    "create_error_message",
    "parse_message",
    "validate_message",
]
