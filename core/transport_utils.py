"""
core/transport_utils.py — 传输工具函数

提供业务层统一的传输标记函数，自动选择最优传输。
所有业务层代码应使用这些函数，不再硬编码 "websocket"。
"""

from typing import Any, Dict, Optional


def mark_transport(
    message: Dict[str, Any],
    device_id: str = "",
    preferred: Optional[str] = None,
) -> Dict[str, Any]:
    """标记消息传输类型。

    如果指定了 preferred，使用 preferred。
    否则标记为 "auto"，由 AIPTransport 自动选择。

    Args:
        message: 消息字典
        device_id: 目标设备ID（用于自动选择）
        preferred: 首选传输类型（None=自动选择）

    Returns:
        添加了 _transport 字段的消息字典
    """
    msg = dict(message)  # 复制避免修改原对象
    if preferred:
        msg["_transport"] = preferred
    else:
        msg["_transport"] = "auto"  # AIPTransport 自动选择
    return msg


def auto_transport(device_id: str = "") -> str:
    """返回自动传输标记。

    业务层代码使用此函数代替硬编码 "websocket"。
    AIPTransport 会根据 device_id 自动选择最优传输。
    """
    return "auto"
