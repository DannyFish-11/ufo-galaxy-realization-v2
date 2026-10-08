"""galaxy_gateway/android/handlers/device_command.py — 规范入口上的设备命令与通话信令。

背景
====
手表（以及笔记本之类的"成员"）经 ``/ws/device/{id}`` 发来两类东西：

* ``command`` 帧：``voice_query``（人说的话，交给智能体）、``human_input``（回答智能体的
  提问）、``query_devices``、``interruptibility``（"现在能不能打扰他"的遥测）……
* ``voice_call_*``：人与智能体实时通话的信令。

它们的处理逻辑早就写好了，却挂在**没有挂载**的旧入口（``websocket_handler.handle_websocket``）
上。规范入口 ``android_bridge`` 对这两类帧没有处理器，掉进通用兜底，只回一个
"No specific handler registered" 的 ack —— 于是手表说的话到不了智能体，通话接不通。

这里不重写逻辑，只做接线：

* ``handle_device_command``：把规范入口的帧包成旧处理器认得的形状，**复用同一份**
  ``websocket_handler.handle_command``，用 ``send`` 回调收下回包，作为 ``handle_message``
  的返回值写回 socket。
* ``handle_voice_call``：转给 ``voice_call_route.maybe_handle_voice_message``，信令经
  ``websocket.send_json`` 直接回给这条连接。

两者都先过 :func:`~galaxy_gateway.android.ingress_trust.sender_is_trusted`：``voice_query``
会进智能体主链，``human_input`` 能批准一次高风险操作 —— 都不能让一条没认证过的连接去做。
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, Optional

from galaxy_gateway.android.ingress_trust import sender_is_trusted
from galaxy_gateway.command_reply import REPLY_TO_KEY, request_name

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


def _frame_parts(message: Dict[str, Any]) -> tuple:
    device_id = str(message.get("device_id") or "").strip()
    inner = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    return device_id, inner


async def handle_device_command(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理设备发来的 ``command`` 帧，返回要写回 socket 的 ``command_result``。"""
    from galaxy_gateway import websocket_handler as _wh

    device_id, inner = _frame_parts(message)
    request_id = request_name(message, str(uuid.uuid4()))
    aip_msg = SimpleNamespace(
        payload={**inner, REPLY_TO_KEY: request_id},
        device_id=device_id,
        message_id=request_id,
        correlation_id=str(message.get("correlation_id") or ""),
        task_id=None,
    )

    if not sender_is_trusted(bridge, websocket, device_id):
        logger.warning("command from an unauthenticated connection refused: device_id=%s", device_id)
        return _wh._command_result(aip_msg, {"success": False, "error": "unauthenticated"})

    replies: list = []

    async def _collect(response: Dict[str, Any]) -> None:
        replies.append(response)

    await _wh.handle_command(None, aip_msg, send=_collect)
    if replies:
        return replies[-1]
    # 旧处理器内部出错时只记日志、不回包 —— 手表会一直等一个不会来的结果。
    return _wh._command_result(aip_msg, {"success": False, "error": "command failed inside the gateway"})


async def handle_voice_call(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理 ``voice_call_*`` 信令。回包由通话路由经这条连接直接发出，所以返回 ``None``。"""
    from galaxy_gateway.voice_call_route import maybe_handle_voice_message, voice_route_key

    device_id, inner = _frame_parts(message)
    if not sender_is_trusted(bridge, websocket, device_id):
        logger.warning("voice call signalling from an unauthenticated connection refused: device_id=%s", device_id)
        return {
            "type": "voice_call_end",
            "device_id": device_id,
            "call_id": str(inner.get("call_id") or ""),
            "reason": "unauthenticated",
        }
    await maybe_handle_voice_message(
        voice_route_key(websocket), message.get("type"), inner, device_id, websocket.send_json
    )
    return None


def register_device_command_handlers(handlers: Dict[Any, Any], wrap: Any) -> None:
    """把命令与通话信令挂到规范入口的处理表上（``AndroidBridge._register_default_handlers`` 调）。"""
    from galaxy_gateway.protocol.aip_v3 import MessageType

    handlers[MessageType.COMMAND] = wrap(handle_device_command)
    for voice_type in (
        MessageType.VOICE_CALL_START,
        MessageType.VOICE_CALL_END,
        MessageType.VOICE_ICE,
        MessageType.VOICE_INTERRUPT,
    ):
        handlers[voice_type] = wrap(handle_voice_call)
