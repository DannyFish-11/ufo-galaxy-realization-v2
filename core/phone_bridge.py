"""core/phone_bridge.py — 手机接管与对话桥接(跨设备整体方案阶段 3)。

所有者最初的设计:手机打开跨设备并登录后,中心派一个 Agent 到手机;手机上的 agent runtime 接管本地
正在跑的上下文,把本地这一整套并进网络。从此手机上的对话就是和中心智能体的对话,上下文还是那一份。

全部走对外 A2A(:mod:`core.a2a_link`),四段:

1. **接入握手**:手机报完能力 → 中心发 ``agent_dispatch``(桥接 Agent 的说明:代表哪个中心智能体、
   上下文归到哪个会话、手机本地有哪些动作、自治档位与要人确认的动作)→ 手机回 ``agent_installed``;
2. **上交上下文**:手机发 ``context_handoff``(最近对话、正在跑的本地循环进度、最近几次本地执行)→
   并进这台手机在中心的会话(:func:`core.session_memory_facade.record_session_turn`,智能体读的就是它);
3. **对话桥接**:手机上说的话(``conversation``)进中心智能体的同一个会话,回答以 ``conversation`` 回到
   手机界面;来源是 ``device_chat`` —— 算人发起的回合,不进电脑三态(设备上说的话都是同一套来源分类)。
   中心要手机做一整段事时用 ``devices__delegate``(``delegate_goal`` → 手机本地循环 →
   ``delegate_progress`` / ``delegate_result``);
4. **交还**:手机要关跨设备时发 ``context_return``(``body.request = true``)→ 中心交还摘要与没做完的事。

Agent 载体(阶段 5:别的电脑、Linux 服务器、云主机上的 ``python -m device_client --carrier``)走同一套:
报能力时声明 ``bridge_agent`` → 派过去 → ``devices__delegate`` 交整段目标。载体上的推理加行动循环要模型时
发 ``tool_call``(``llm.chat``),中心用自己的模型答(钥匙只在中心)。

接了桥接 Agent 的设备不分是什么,会话都叫 ``bridge:<设备号>``;来源都是 ``device_chat``。

手机上那一半在 ufo-galaxy-android ``app/.../bridge/BridgeAgentRuntime.kt``;载体那一半在
``device_client/carrier_agent.py``。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from core import a2a_link as a2a

logger = logging.getLogger("Galaxy.PhoneBridge")

BRIDGE_VERSION = "bridge/1"
#: 设备上(经桥接 Agent)说的话进中心时的来源名:算人发起的回合,不进电脑三态(见 core/presence_line.py)。
BRIDGE_CHAT_SOURCE = "device_chat"
#: 要人确认才做的手机动作(发给别人的、花钱的、删东西的)。
CONFIRM_ACTIONS = ("sms", "phone_call", "payment", "send_message", "delete")
MAX_RETURN_TURNS = 8
DEFAULT_DELEGATE_TIMEOUT_S = 180.0
MAX_DELEGATE_TIMEOUT_S = 600.0
#: 一次 llm.chat 带上来的消息总长上限(字符);载体的推理加行动循环每轮都会带上之前的轮次。
MAX_LLM_CHARS = 60000
#: 设备刚(重新)登记、还没报能力时,委派最多等它报能力多久(秒;登记后约半秒就报)。
REPORT_WAIT_S = 3.0
#: 声明过 / 装过桥接 Agent 的设备还没(重新)装上时,委派最多等它装上多久(秒)。
REINSTALL_WAIT_S = 15.0

# 事件循环只持后台任务的弱引用,不留强引用会被 GC 掉
_tasks: Set["asyncio.Task[Any]"] = set()


def bridge_session_id(device_id: str) -> str:
    """这台设备的对话在中心归到哪个会话(也是 A2A 链路的会话号)。不分设备是什么,都是 ``bridge:<设备号>``。"""
    return f"bridge:{device_id}"


@dataclass
class _Bridge:
    device_id: str
    session_id: str
    dispatch_msg_id: str = ""
    installed: bool = False
    installed_at: float = 0.0
    handoff_at: float = 0.0
    handoff_turns: int = 0
    seen_turns: Set[str] = field(default_factory=set)
    delegations: Dict[str, "asyncio.Future[Dict[str, Any]]"] = field(default_factory=dict)
    progress: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    returned_at: float = 0.0


_bridges: Dict[str, _Bridge] = {}
#: 设备(重新)登记的时刻,报完能力就删:这段时间里它能不能接 Agent 还不知道(登记会换掉元数据)。
_registered_at: Dict[str, float] = {}


def _bridge(device_id: str) -> _Bridge:
    b = _bridges.get(device_id)
    if b is None:
        b = _bridges[device_id] = _Bridge(device_id, bridge_session_id(device_id))
    return b


def bridge_state(device_id: str) -> Dict[str, Any]:
    """这台设备上的桥接 Agent 现在怎么样(设备卡与诊断看)。"""
    b = _bridges.get(device_id)
    if b is None:
        return {"installed": False}
    return {
        "installed": b.installed,
        # 这次进程里装上过:刚重连、还没重新装上的那几百毫秒里,它照样是能接 Agent 的设备
        "hosted": b.installed_at > 0,
        "session_id": b.session_id,
        "handoff_turns": b.handoff_turns,
        "open_delegations": sorted(b.delegations),
    }


def reset_bridges() -> None:
    """测试用。"""
    _bridges.clear()
    _registered_at.clear()


def _member(device_id: str) -> Optional[Dict[str, Any]]:
    """这台成员的视图与元数据;不在名册里返回 None。"""
    try:
        from core.device_onboarding.service import get_onboarding_service
        from core.unified.device_manager import get_unified_device_manager

        d = get_unified_device_manager().get_device(device_id)
        if d is None:
            return None
        return {"view": get_onboarding_service().member_view(d), "metadata": dict(d.metadata or {})}
    except Exception as exc:  # noqa: BLE001
        logger.debug("phone bridge: member %s unavailable: %s", device_id, exc)
        return None


def _can_take_agent(device_id: str) -> bool:
    from core.device_onboarding.device_card import can_take_agent

    b = _bridges.get(device_id)
    if b is not None and b.installed_at > 0:
        return True  # 装上过;重新登记会先换掉元数据,报能力那一帧还没到
    m = _member(device_id)
    return bool(m) and can_take_agent(m["view"], m["metadata"])


def _spec(device_id: str) -> Dict[str, Any]:
    """桥接 Agent 的说明。"""
    tools: List[Dict[str, str]] = []
    m = _member(device_id)
    if m:
        try:
            from core.device_onboarding.device_card import build_device_card

            tools = build_device_card(m["view"], m["metadata"]).get("actions", [])
        except Exception as exc:  # noqa: BLE001 — 说明里少了动作清单不该挡住握手
            logger.debug("phone bridge: action list unavailable for %s: %s", device_id, exc)
    try:
        from core.autonomy_policy import autonomy_level

        autonomy = autonomy_level().value
    except Exception:  # noqa: BLE001
        autonomy = "guided"
    return {
        "bridge_version": BRIDGE_VERSION,
        "center_agent": a2a.CENTER_AGENT,
        "session_id": bridge_session_id(device_id),
        "tools": tools,
        "autonomy": autonomy,
        "confirm_actions": list(CONFIRM_ACTIONS),
        "conversation": {"uplink": a2a.Kind.CONVERSATION.value, "source": BRIDGE_CHAT_SOURCE},
        "context_handoff": ["dialog", "loop_progress", "trajectory"],
    }


async def dispatch_bridge(device_id: str) -> bool:
    """中心 → 手机:派一个桥接 Agent 过去。只派给能接 Agent 的设备;上一份还没确认的不重派。

    每次手机(重新)报能力都会走到这里:手机那边已经装着时只回一句「装着呢」,上下文不会再交一遍。
    """
    if not _can_take_agent(device_id):
        return False
    b = _bridge(device_id)
    link = a2a.link_for(device_id, b.session_id)
    if b.dispatch_msg_id and any(e.msg_id == b.dispatch_msg_id for e in link.unacked()):
        return False  # 上一份还在路上(重新登记时 a2a.resend_unacked 已经补发)
    env, _sent = await a2a.send(device_id, a2a.Kind.AGENT_DISPATCH, _spec(device_id), session_id=b.session_id)
    b.dispatch_msg_id = env.msg_id
    return True


def declares_bridge_support(capability_report: Dict[str, Any]) -> bool:
    """设备在报能力时声明了能装桥接 Agent(``bridge_agent: "bridge/1"``,顶层或 payload 里)。"""
    payload = capability_report.get("payload") if isinstance(capability_report.get("payload"), dict) else {}
    declared = capability_report.get("bridge_agent") or payload.get("bridge_agent") or ""
    return str(declared).split("/")[0] == BRIDGE_VERSION.split("/")[0]


def note_registered(device_id: str) -> None:
    """设备(重新)登记上了:它那边的 Agent 是不是还在,要等它回了这次的派遣才算数。

    不重置的话,重连后、报能力之前的那一小段里,中心会以为 Agent 还装着(载体进程可能已经换了一个)。
    """
    _registered_at[device_id] = time.monotonic()
    b = _bridges.get(device_id)
    if b is not None:
        b.installed = False


def note_reported(device_id: str) -> None:
    """设备报完能力了(能不能接 Agent 此刻已知)。"""
    _registered_at.pop(device_id, None)


def _declared(device_id: str) -> bool:
    m = _member(device_id)
    return bool(m) and m["metadata"].get("can_host_agent") is True


async def _settle(device_id: str) -> None:
    """委派前等设备说清楚:刚登记、还没报能力的等它报;声明过或装过桥接 Agent、还没(重新)装上的等它装上。

    真后端实测查出:后端重启或设备重连后的那半秒里,交整段目标会被当场拒成「不能接整段目标」。
    从没声明过的设备(「手和眼」式电脑、旧版 App)不等,照样当场说明。
    """
    since = _registered_at.get(device_id)
    while device_id in _registered_at and since is not None and time.monotonic() - since < REPORT_WAIT_S:
        await asyncio.sleep(0.1)
    b = _bridges.get(device_id)
    if (b is not None and b.installed) or not ((b is not None and b.installed_at > 0) or _declared(device_id)):
        return
    deadline = time.monotonic() + REINSTALL_WAIT_S
    while time.monotonic() < deadline and not (device_id in _bridges and _bridges[device_id].installed):
        await asyncio.sleep(0.2)


def schedule_dispatch(device_id: str) -> None:
    """报能力的入口里调:在后台派,不挡住这条连接上后面的帧。"""
    try:
        task = asyncio.get_running_loop().create_task(dispatch_bridge(device_id))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ── 手机发来的 ─────────────────────────────────────────────────────────────────


async def _on_installed(device_id: str, env: a2a.Envelope) -> None:
    b = _bridge(device_id)
    b.installed = True
    b.installed_at = time.time()
    resumed = bool(env.body.get("resumed"))
    logger.info(
        "phone bridge %s on %s (%s)", "resumed" if resumed else "installed", device_id, env.body.get("runtime") or ""
    )


def _turn_key(role: str, text: str, ts: Any) -> str:
    return hashlib.sha1(f"{role}\x00{ts}\x00{text}".encode("utf-8")).hexdigest()


def _render_state_note(body: Dict[str, Any]) -> str:
    """把手机交上来的进度 / 轨迹写成一句给智能体看的话。"""
    parts = []
    progress = body.get("loop_progress")
    if isinstance(progress, dict) and progress:
        step, total, action = progress.get("step"), progress.get("total"), progress.get("action")
        parts.append(f"手机上正在跑的本地任务:第 {step}/{total} 步" + (f"({action})" if action else ""))
    traj = body.get("trajectory")
    if isinstance(traj, list) and traj:
        items = []
        for t in traj[-5:]:
            if isinstance(t, dict):
                items.append(f"{t.get('action', '')}[{t.get('status', '')}]")
            else:
                items.append(str(t))
        parts.append("手机最近自己做过:" + ";".join(items))
    return "(手机交接过来的本地状态)" + " · ".join(parts) if parts else ""


async def _on_context_handoff(device_id: str, env: a2a.Envelope) -> None:
    from core.session_memory_facade import record_session_turn

    b = _bridge(device_id)
    body = env.body
    dialog = body.get("dialog") if isinstance(body.get("dialog"), list) else []
    count = 0
    for turn in dialog:
        if not isinstance(turn, dict):
            continue
        role = "assistant" if str(turn.get("role")) in ("assistant", "agent", "local_model") else "user"
        text = str(turn.get("text") or turn.get("content") or "").strip()
        if not text:
            continue
        key = _turn_key(role, text, turn.get("ts"))
        if key in b.seen_turns:
            continue  # 重连后又交了一遍的,不重复记
        b.seen_turns.add(key)
        await record_session_turn(
            conversation_session_id=b.session_id,
            role=role,
            content=text,
            device_id=device_id,
            trace_id=env.trace_id,
            metadata={"source": "phone_handoff", "local_ts": turn.get("ts")},
        )
        count += 1
    note = _render_state_note(body)
    if note:
        await record_session_turn(
            conversation_session_id=b.session_id,
            role="system",
            content=note,
            device_id=device_id,
            trace_id=env.trace_id,
            metadata={"source": "phone_handoff"},
        )
    b.handoff_turns += count
    b.handoff_at = time.time()
    logger.info("phone bridge: %s handed over %d turn(s)", device_id, count)


async def _converse(device_id: str, env: a2a.Envelope, text: str) -> None:
    b = _bridge(device_id)
    reply, ok = "", False
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime

        result = await get_desktop_presence_runtime().handle_request(
            message=text,
            source=BRIDGE_CHAT_SOURCE,
            device_id=device_id,
            session_id=b.session_id,
        )
        ok = bool(result.get("success", True))
        reply = str(result.get("response") or result.get("reply") or "")
        if not reply:
            reply = "做完了。" if ok else f"没处理成:{result.get('error') or '原因不明'}"
    except Exception as exc:  # noqa: BLE001 — 回一句失败,不让手机一直等
        logger.warning("phone bridge: conversation failed for %s: %s", device_id, exc, exc_info=True)
        reply = f"没处理成:{exc}"
    await a2a.send(
        device_id,
        a2a.Kind.CONVERSATION,
        {"role": "assistant", "text": reply, "in_reply_to": env.msg_id, "success": ok},
        session_id=b.session_id,
        task_id=env.task_id,
        trace_id=env.trace_id,
    )


async def _on_conversation(device_id: str, env: a2a.Envelope) -> None:
    """手机上说的一句话 → 中心智能体的同一个会话 → 回答回到手机。

    一轮对话要几秒到几分钟,在后台跑:这台手机后面的帧(确认、进度)不必等它。
    """
    text = str(env.body.get("text") or "").strip()
    if not text:
        return
    task = asyncio.get_running_loop().create_task(_converse(device_id, env, text))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _on_delegate_progress(device_id: str, env: a2a.Envelope) -> None:
    b = _bridge(device_id)
    if env.task_id in b.delegations:
        b.progress.setdefault(env.task_id, []).append(dict(env.body))


async def _on_delegate_result(device_id: str, env: a2a.Envelope) -> None:
    fut = _bridge(device_id).delegations.pop(env.task_id, None)
    if fut is not None and not fut.done():
        fut.set_result(dict(env.body))


async def _on_context_return(device_id: str, env: a2a.Envelope) -> None:
    """手机要关跨设备:交还这段对话的摘要与没做完的事,然后视为卸下桥接 Agent。"""
    if not env.body.get("request"):
        return
    b = _bridge(device_id)
    turns: List[Dict[str, str]] = []
    try:
        from core.session_memory_facade import get_session_context

        for t in get_session_context(b.session_id, max_turns=MAX_RETURN_TURNS) or []:
            if isinstance(t, dict):
                turns.append({"role": str(t.get("role") or ""), "text": str(t.get("content") or "")[:500]})
    except Exception as exc:  # noqa: BLE001
        logger.debug("phone bridge: session context unavailable: %s", exc)
    said = [t["text"] for t in turns if t["role"] == "assistant" and t["text"]]
    summary = said[-1][:300] if said else ""
    open_items = [{"task_id": tid, "kind": "delegate_goal"} for tid in sorted(b.delegations)]
    await a2a.send(
        device_id,
        a2a.Kind.CONTEXT_RETURN,
        {"summary": summary, "open_items": open_items, "turns": turns},
        session_id=b.session_id,
        trace_id=env.trace_id,
    )
    b.installed = False
    b.returned_at = time.time()
    logger.info("phone bridge: context returned to %s", device_id)


# ── 派出去的 Agent 向中心要东西(阶段 5:载体的模型经中心) ───────────────────────


def _portable_messages(raw: Any) -> List[Dict[str, str]]:
    """载体那边推理加行动循环用的消息,换成各家模型都认的形状(不依赖 tool_call_id)。"""
    out: List[Dict[str, str]] = []
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "user")
        content = str(m.get("content") or "")
        if role == "assistant" and m.get("tool_calls_raw"):
            calls = "; ".join(
                f"{c.get('name', '')}({json.dumps(c.get('arguments', {}), ensure_ascii=False)})"
                for c in m["tool_calls_raw"]
                if isinstance(c, dict)
            )
            content = (content + "\n" if content else "") + f"[调用工具] {calls}"
        elif role == "tool":
            role, content = "user", f"[工具 {m.get('name', '')} 的结果] {content}"
        elif role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": content})
    return out


def _portable_tool_calls(raw: Any) -> Optional[List[Dict[str, Any]]]:
    """模型回的工具调用(OpenAI 形状或扁平形状)→ ``[{name, arguments: dict}]``。"""
    calls = []
    for tc in raw or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = tc.get("name") or fn.get("name") or ""
        args = tc.get("arguments", fn.get("arguments", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                args = {}
        if name:
            calls.append({"name": str(name), "arguments": args if isinstance(args, dict) else {}})
    return calls or None


async def _llm_chat_for(device_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    messages = _portable_messages(body.get("messages"))
    if not messages:
        return {"success": False, "error": "需要 messages"}
    if sum(len(m["content"]) for m in messages) > MAX_LLM_CHARS:
        return {"success": False, "error": f"带上来的对话太长(上限 {MAX_LLM_CHARS} 字)"}
    tools = body.get("tools") if isinstance(body.get("tools"), list) else None
    try:
        from core.multi_llm_router import get_llm_router

        resp = await get_llm_router().chat(messages=messages, tools=tools or None)
    except Exception as exc:  # noqa: BLE001 — 模型调不通作为结果回给载体
        logger.info("bridge: llm.chat for %s failed: %s", device_id, exc)
        return {"success": False, "error": str(exc)}
    if getattr(resp, "provider", "") == "none":
        # 路由一个模型都调不通时不抛异常,回一句说明(给人看的降级);对载体那是失败,不是答案 ——
        # 当成答案的话,载体会把「还没有可用的 AI 服务」当作做完了的总结报回来(真后端实测查出)
        return {"success": False, "error": str(getattr(resp, "content", "") or "中心没有可用的模型")}
    return {
        "success": True,
        "content": str(getattr(resp, "content", "") or ""),
        "tool_calls": _portable_tool_calls(getattr(resp, "tool_calls", None)),
    }


async def _answer_tool_call(device_id: str, env: a2a.Envelope) -> None:
    b = _bridge(device_id)
    tool = str(env.body.get("tool") or "")
    if not b.installed:
        res: Dict[str, Any] = {"success": False, "error": "这台设备上没有装桥接 Agent"}
    elif tool == "llm.chat":
        res = await _llm_chat_for(device_id, env.body)
    else:
        res = {"success": False, "error": f"中心不提供 {tool!r}(可用:llm.chat)"}
    await a2a.send(
        device_id,
        a2a.Kind.TOOL_RESULT,
        {"call_id": str(env.body.get("call_id") or env.msg_id), **res},
        session_id=b.session_id,
        task_id=env.task_id,
        trace_id=env.trace_id,
    )


async def _on_tool_call(device_id: str, env: a2a.Envelope) -> None:
    """派出去的 Agent 调中心的能力(现在只有 ``llm.chat``)。在后台答,不挡这台设备后面的帧。"""
    task = asyncio.get_running_loop().create_task(_answer_tool_call(device_id, env))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


a2a.register_handler(a2a.Kind.AGENT_INSTALLED, _on_installed)
a2a.register_handler(a2a.Kind.CONTEXT_HANDOFF, _on_context_handoff)
a2a.register_handler(a2a.Kind.CONVERSATION, _on_conversation)
a2a.register_handler(a2a.Kind.DELEGATE_PROGRESS, _on_delegate_progress)
a2a.register_handler(a2a.Kind.DELEGATE_RESULT, _on_delegate_result)
a2a.register_handler(a2a.Kind.CONTEXT_RETURN, _on_context_return)
a2a.register_handler(a2a.Kind.TOOL_CALL, _on_tool_call)


# ── 中心要手机做一整段事 ──────────────────────────────────────────────────────


async def delegate(
    device_id: str,
    goal: str,
    *,
    constraints: Optional[List[str]] = None,
    timeout: float = DEFAULT_DELEGATE_TIMEOUT_S,
    session_id: str = "",
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """把一整段目标交给装了桥接 Agent 的设备(手机本地循环、载体),等它的结果。

    ``steps``(``[{action, params}]``)给了就照这串动作按顺序做,不用对方的模型;不给就由对方自己规划。
    """
    from core.device_onboarding.device_card import record_dispatch, record_result

    goal = (goal or "").strip()
    if not goal and not steps:
        return {"success": False, "error": "需要 goal(或 steps)"}
    await _settle(device_id)
    if not _can_take_agent(device_id):
        return {
            "success": False,
            "error": f"「{device_id}」不能接整段目标(看设备卡的 can_take_agent),改用 devices__invoke",
        }
    b = _bridge(device_id)
    if not b.installed:
        return {
            "success": False,
            "error": f"「{device_id}」上还没有桥接 Agent(没连着,或 App 版本太旧);单个动作可用 devices__invoke",
        }
    timeout = max(5.0, min(float(timeout or DEFAULT_DELEGATE_TIMEOUT_S), MAX_DELEGATE_TIMEOUT_S))
    task_id = f"dlg_{uuid.uuid4().hex[:12]}"
    fut: "asyncio.Future[Dict[str, Any]]" = asyncio.get_running_loop().create_future()
    b.delegations[task_id] = fut
    graph_task = record_dispatch(device_id, "delegate_goal", session_id)
    _env, sent = await a2a.send(
        device_id,
        a2a.Kind.DELEGATE_GOAL,
        {
            "goal": goal,
            "constraints": [str(c) for c in (constraints or [])],
            **({"steps": [s for s in steps if isinstance(s, dict)]} if steps else {}),
        },
        session_id=b.session_id,
        task_id=task_id,
    )
    try:
        result = await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        b.delegations.pop(task_id, None)
        record_result(graph_task, False, error="timeout")
        hint = "" if sent else "(设备此刻没连着,连上后会补发)"
        return {
            "success": False,
            "task_id": task_id,
            "error": f"{timeout:.0f} 秒内没有结果{hint}",
            "progress": b.progress.pop(task_id, []),
        }
    ok = bool(result.get("success"))
    record_result(graph_task, ok, summary=str(result.get("summary") or ""), error=str(result.get("error") or ""))
    return {**result, "success": ok, "task_id": task_id, "progress": b.progress.pop(task_id, [])}
