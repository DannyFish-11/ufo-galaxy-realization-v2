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
``ask_human__notify`` 不再自己挑设备(设计文档 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 4.2:发给谁是模型的判断):

* 点名了 ``device_ids`` 的,调那几台**自己报的**能显示一句话的动作 —— 设备自述里 ``effect`` 是 ``notify``、
  参数收 ``text`` 的那个(手表的 ``notify``、手机的 ``notification``),走 ``devices__invoke`` 同一条路(过边界、
  进任务流程图);设备没报这样的动作就照实说送不到;
* 没点名的,发给发起这次请求的那台设备;没有发起设备(电脑这边、智能体自己)就回一句「看设备卡片指定设备」。

还没有设备自述的旧版设备(没报 ``effect``,认不出哪个动作能显示一句话)照旧收一条 ``agent_message`` 帧
(``push_agent_message``,旧版手表认得:弹通知、记进会话);它只发给点名的设备,不再按声明替谁挑设备。

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

from core.interaction.pending_decision_registry import EmitCallback, _default_emit

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
    """把一句话推给点名的设备上的人(``agent_message`` 帧)。不等任何回应。``devices`` 不给就谁也不发。

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
    targets = list(devices or [])
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
        logger.info("agent_message 没有点名任何设备:%s", msg["message_id"])
    return {"message_id": msg["message_id"], "delivered": delivered, "failed": failed, "targets": targets}


#: 智能体的内置工具定义(并入 core/openclawd.py 的 _ASK_HUMAN_BUILTIN_TOOLS)。
#: 与 ``ask_human__request`` 同族:那个是"问你并等答案",这个是"告诉你,不等"。
ASK_HUMAN_NOTIFY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_human__notify",
        "description": (
            "Tell the human something WITHOUT waiting for a reply, on a device you pick. "
            "Pick from devices__list: a device whose actions include one with effect 'notify' that takes 'text'. "
            "With device_ids it shows the text through that action on each device; without device_ids it goes to "
            "the device this request came from. You can also call that action yourself with devices__invoke. "
            "Use for things they should know but need not answer: a long task finished, something noteworthy was "
            "found, a reminder they asked for. If you need an answer or approval, use ask_human__request instead. "
            "Returns {delivered, failed, reasons}; empty 'delivered' means no device received it — do not claim "
            "you told them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to tell them. Short — small screens show it."},
                "title": {"type": "string", "description": "Optional short title."},
                "device_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which devices to show it on (from devices__list).",
                },
                "reply_expected": {
                    "type": "boolean",
                    "description": "Offer a quick-reply box where the device supports it (default false).",
                },
            },
            "required": ["text"],
        },
    },
}


def message_action(device_id: str) -> Dict[str, Any]:
    """这台设备自己报的、能把一句话显示给人的动作:``effect`` 是 ``notify`` 且参数收 ``text``。没有就是空字典。"""
    from core.device_self import described
    from core.unified.device_manager import get_unified_device_manager

    try:
        d = get_unified_device_manager().get_device(device_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask_human__notify: 读不到设备 %s 的自述,当它没有消息动作: %s", device_id, exc)
        return {}
    for a in described(getattr(d, "metadata", None) or {}).get("actions") or []:
        props = (a.get("params") or {}).get("properties") or {}
        if a.get("effect") == "notify" and "text" in props:
            return a
    return {}


def _described(device_id: str) -> bool:
    """这台设备报过设备自述没有(新版设备都报)。"""
    from core.device_self import described
    from core.unified.device_manager import get_unified_device_manager

    try:
        d = get_unified_device_manager().get_device(device_id)
    except Exception:  # noqa: BLE001
        return False
    return described(getattr(d, "metadata", None) or {}).get("source") == "self_description"


def _origin_device() -> str:
    """发起这次请求的设备;电脑这边发起的、或不在一次请求里,是空串。"""
    try:
        from core.liminal_activity import current_runtime_session

        rs = current_runtime_session()
    except Exception:  # noqa: BLE001
        return ""
    if rs is None or getattr(rs, "host_bound", False):
        return ""
    return str(getattr(rs, "origin_device_id", "") or "")


async def dispatch_notify_tool(arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    """执行 ``ask_human__notify``:调点名的设备(或发起这次请求的那台)自己报的消息动作。"""
    from core.device_onboarding.agent_tools import _invoke

    args = arguments or {}
    text = str(args.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "ask_human__notify requires 'text'"}
    picked = [str(d) for d in (args.get("device_ids") or []) if str(d).strip()]
    if not picked:
        origin = _origin_device()
        picked = [origin] if origin else []
    if not picked:
        return {
            "success": False,
            "error": "没指定发到哪台设备:看 devices__list 的设备卡片,挑一台有 effect 为 notify、收 text 的动作的,"
            "给 device_ids,或直接用 devices__invoke 调那个动作",
        }
    delivered: List[str] = []
    failed: List[str] = []
    reasons: Dict[str, str] = {}
    for did in picked:
        action = message_action(did)
        if not action and not _described(did):
            # 旧版设备(没有设备自述):照旧推一条 agent_message 帧
            out = await push_agent_message(
                text=text,
                title=str(args.get("title") or ""),
                conversation_id=session_id,
                reply_expected=bool(args.get("reply_expected")),
                devices=[did],
            )
            (delivered if out["delivered"] else failed).append(did)
            if not out["delivered"]:
                reasons[did] = "没送到"
            continue
        if not action:
            failed.append(did)
            reasons[did] = "这台设备没报能显示一句话的动作(effect 为 notify、收 text)"
            continue
        accepts = (action.get("params") or {}).get("properties") or {}
        params: Dict[str, Any] = {"text": text[:MAX_TEXT_CHARS]}
        extras = {
            "title": str(args.get("title") or "").strip()[:MAX_TITLE_CHARS],
            "reply_expected": bool(args.get("reply_expected")),
            "conversation_id": session_id,
        }
        params.update({k: v for k, v in extras.items() if k in accepts and v not in ("", False)})
        try:
            out = await _invoke({"device_id": did, "action": action["name"], "params": params}, session_id)
        except Exception as exc:  # noqa: BLE001 — 一台失败不影响其余
            out = {"success": False, "error": str(exc)}
        if out.get("success"):
            delivered.append(did)
        else:
            failed.append(did)
            reasons[did] = str(out.get("error") or out.get("ask_user") or "没送到")
    # 一台都没送到 ≠ 成功:让智能体知道"没人收到",别在回复里说"已经告诉你了"。
    return {"success": bool(delivered), "delivered": delivered, "failed": failed, "reasons": reasons}
