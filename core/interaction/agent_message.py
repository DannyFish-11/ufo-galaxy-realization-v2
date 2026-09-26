"""core/interaction/agent_message.py — 智能体主动跟你说一句话。

缺口是什么
==========
协议早就有 ``agent_message`` 这一类(``galaxy_gateway/protocol/aip_v3.AGENT_MESSAGE``),
手表那头也早就接好了:收到就弹通知、记进会话、按 ``message_id`` 去重。

但网关这头**没有任何代码发它**。于是智能体只能在两种情况下出现在手表上:
你先问了它一句(回复),或者它要你做个决定(``decision_request``,阻塞等答案)。
"跑完了告诉你一声""发现一件你该知道的事"—— 这类不需要你回答的话,没有路可走。

当初没加发送函数是有意的:一个没有调用方的发送函数只是摆设。现在调用方有了 ——
智能体的内置工具 ``ask_human__notify``(见 ``core/openclawd.py``),与
``ask_human__request`` 同族:一个是"问你并等答案",一个是"告诉你,不等"。

投递
====
与 ``request_human_decision`` 走同一条路:默认发给当前在线的手表与手机
(``_discover_target_devices``),经网关连接管理器送达(``_default_emit``)。
不另起一套 —— 两套投递逻辑早晚会对"发给谁"判出两种答案。

报文形状
========
字段**顶层与 payload 各放一份**。手表读顶层(见 galaxy-wearos AIPClient 的
``agent_message`` 分支),有的客户端只读 payload;两处都填,谁读都拿得到。
``message_id`` 由这里生成:手表靠它去重,断线补发不会记成两条、弹两次通知。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from core.interaction.pending_decision_registry import EmitCallback, _default_emit, _discover_target_devices

logger = logging.getLogger("Galaxy.Interaction.AgentMessage")

#: 手表通知一屏放不下太长的字;超出部分截断,完整内容仍进会话记录。
MAX_TEXT_CHARS = 2000
MAX_TITLE_CHARS = 60


def build_agent_message(
    *,
    text: str,
    title: str = "",
    conversation_id: str = "",
    requires_ack: bool = False,
    reply_expected: bool = False,
    message_id: str = "",
) -> Dict[str, Any]:
    """拼一条 ``agent_message``。纯函数,便于单测。"""
    body = str(text or "").strip()
    if not body:
        raise ValueError("agent_message 需要非空的 text")
    fields: Dict[str, Any] = {
        "message_id": message_id or f"am_{uuid.uuid4().hex}",
        "conversation_id": str(conversation_id or ""),
        "text": body[:MAX_TEXT_CHARS],
        "title": str(title or "").strip()[:MAX_TITLE_CHARS],
        "role": "assistant",
        "requires_ack": bool(requires_ack),
        "reply_expected": bool(reply_expected),
        "timestamp": time.time(),
    }
    return {"type": "agent_message", **fields, "payload": dict(fields)}


async def push_agent_message(
    *,
    text: str,
    title: str = "",
    conversation_id: str = "",
    requires_ack: bool = False,
    reply_expected: bool = False,
    devices: Optional[List[str]] = None,
    emit: Optional[EmitCallback] = None,
) -> Dict[str, Any]:
    """把一句话推给在线的手表/手机。不等任何回应。

    返回 ``{message_id, delivered: [...], failed: [...], targets: [...]}``。
    一台都没送到时 ``delivered`` 为空 —— 调用方(智能体)据此知道"没人收到",
    而不是以为已经告诉你了。
    """
    msg = build_agent_message(
        text=text,
        title=title,
        conversation_id=conversation_id,
        requires_ack=requires_ack,
        reply_expected=reply_expected,
    )
    _emit = emit or _default_emit
    targets = list(devices) if devices is not None else await _discover_target_devices()
    delivered: List[str] = []
    failed: List[str] = []
    for did in targets:
        try:
            await _emit(did, msg)
            delivered.append(did)
        except Exception as exc:  # noqa: BLE001 — 一台失败不影响其余
            logger.debug("agent_message → %s 失败: %s", did, exc)
            failed.append(did)
    if not targets:
        logger.info("agent_message 没有在线的手表/手机可送:%s", msg["message_id"])
    return {"message_id": msg["message_id"], "delivered": delivered, "failed": failed, "targets": targets}


#: 智能体的内置工具定义(并入 core/openclawd.py 的 _ASK_HUMAN_BUILTIN_TOOLS)。
#: 与 ``ask_human__request`` 同族:那个是"问你并等答案",这个是"告诉你,不等"。
ASK_HUMAN_NOTIFY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_human__notify",
        "description": (
            "Tell the human something on their watch/phone WITHOUT waiting for a reply. "
            "Use for things they should know but need not answer: a long task finished, "
            "something noteworthy was found, a reminder they asked for. "
            "If you need an answer or approval, use ask_human__request instead. "
            "Returns {message_id, delivered, failed, targets}; empty 'delivered' means "
            "no device received it — do not claim you told them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to tell them. Short — it shows on a watch."},
                "title": {"type": "string", "description": "Optional short notification title."},
                "reply_expected": {
                    "type": "boolean",
                    "description": "Offer a quick-reply box on the notification (default false).",
                },
            },
            "required": ["text"],
        },
    },
}


async def dispatch_notify_tool(arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    """执行 ``ask_human__notify``。智能体当前会话作为 conversation_id,设备据此归拢上下文。"""
    text = str((arguments or {}).get("text") or "").strip()
    if not text:
        return {"success": False, "error": "ask_human__notify requires 'text'"}
    try:
        out = await push_agent_message(
            text=text,
            title=str(arguments.get("title") or ""),
            conversation_id=session_id,
            reply_expected=bool(arguments.get("reply_expected")),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask_human__notify failed: %s", exc)
        return {"success": False, "error": str(exc)}
    # 一台都没送到 ≠ 成功:让智能体知道"没人收到",别在回复里说"已经告诉你了"。
    return {"success": bool(out["delivered"]), **out}
