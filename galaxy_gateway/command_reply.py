"""galaxy_gateway/command_reply.py — 回复该带哪个 ``correlation_id``。

回复要带**发送方管这次请求叫什么**：它给了 ``message_id`` 就用 ``message_id``（AIP v3 的常规
约定）；只给了 ``correlation_id`` 就用 ``correlation_id``；都没给才用网关自己生成的。

手表的信封里没有 ``message_id`` —— 它把相关 id（``cmd_N``）放在 ``correlation_id`` 上，回复回来时
按它认领（``ConversationRecorder.recordCommandResult``）。此前回复填的是网关临时生成的
``message_id``，手表认领不到，语音回复就从不进会话记录。

入口在解析时把这个名字写进 ``payload["_reply_to"]``（旧入口 ``handle_message`` 与规范入口的
``handle_device_command`` 各写一次），:func:`reply_id` 再读出来。
"""

from __future__ import annotations

from typing import Any

REPLY_TO_KEY = "_reply_to"


def request_name(message: dict, fallback: str = "") -> str:
    """发送方给这次请求起的名字（原始帧里的 ``message_id`` 优先，其次 ``correlation_id``）。"""
    return str(message.get("message_id") or message.get("correlation_id") or fallback)


def reply_id(aip_msg: Any) -> str:
    """回复该带的 ``correlation_id``。"""
    payload = getattr(aip_msg, "payload", None)
    reply_to = payload.get(REPLY_TO_KEY) if isinstance(payload, dict) else None
    return str(reply_to or aip_msg.message_id)
