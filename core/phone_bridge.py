"""core/phone_bridge.py — 手机接管与对话桥接(跨设备整体方案阶段 3)。

所有者最初的设计:手机打开跨设备并登录后,中心派一个 Agent 到手机;手机上的 agent runtime 接管本地
正在跑的上下文,把本地这一整套并进网络。从此手机上的对话就是和中心智能体的对话,上下文还是那一份。

全部走对外 A2A(:mod:`core.a2a_link`),四段:

1. **接入握手**:手机报完能力 → 中心发 ``agent_dispatch``(桥接 Agent 的说明:代表哪个中心智能体、
   上下文归到哪个会话、手机本地有哪些动作、自治档位与要人确认的动作)→ 手机回 ``agent_installed``;
2. **上交上下文**:手机发 ``context_handoff``(最近对话、正在跑的本地循环进度、最近几次本地执行)→
   并进这台手机在中心的会话(:func:`core.session_memory_facade.record_session_turn`,智能体读的就是它);
3. **对话桥接**:手机上说的话(``conversation``)进中心智能体的同一个会话,回答以 ``conversation`` 回到
   手机界面;来源是 ``phone_chat`` —— 算人发起的回合,不进电脑三态(与手表同一套来源分类)。
   中心要手机做一整段事时用 ``devices__delegate``(``delegate_goal`` → 手机本地循环 →
   ``delegate_progress`` / ``delegate_result``);
4. **交还**:手机要关跨设备时发 ``context_return``(``body.request = true``)→ 中心交还摘要与没做完的事。

手机上那一半在 ufo-galaxy-android ``app/.../bridge/BridgeAgentRuntime.kt``。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from core import a2a_link as a2a

logger = logging.getLogger("Galaxy.PhoneBridge")

BRIDGE_VERSION = "bridge/1"
#: 手机上说的话进中心时的来源名:算人发起的回合,不进电脑三态(见 core/presence_line.py)。
PHONE_CHAT_SOURCE = "phone_chat"
#: 要人确认才做的手机动作(发给别人的、花钱的、删东西的)。
CONFIRM_ACTIONS = ("sms", "phone_call", "payment", "send_message", "delete")
MAX_RETURN_TURNS = 8
DEFAULT_DELEGATE_TIMEOUT_S = 180.0
MAX_DELEGATE_TIMEOUT_S = 600.0

# 事件循环只持后台任务的弱引用,不留强引用会被 GC 掉
_tasks: Set["asyncio.Task[Any]"] = set()


def bridge_session_id(device_id: str) -> str:
    """这台手机的对话在中心归到哪个会话(也是 A2A 链路的会话号)。"""
    return f"phone:{device_id}"


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
        "session_id": b.session_id,
        "handoff_turns": b.handoff_turns,
        "open_delegations": sorted(b.delegations),
    }


def reset_bridges() -> None:
    """测试用。"""
    _bridges.clear()


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
        "conversation": {"uplink": a2a.Kind.CONVERSATION.value, "source": PHONE_CHAT_SOURCE},
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
            source=PHONE_CHAT_SOURCE,
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


a2a.register_handler(a2a.Kind.AGENT_INSTALLED, _on_installed)
a2a.register_handler(a2a.Kind.CONTEXT_HANDOFF, _on_context_handoff)
a2a.register_handler(a2a.Kind.CONVERSATION, _on_conversation)
a2a.register_handler(a2a.Kind.DELEGATE_PROGRESS, _on_delegate_progress)
a2a.register_handler(a2a.Kind.DELEGATE_RESULT, _on_delegate_result)
a2a.register_handler(a2a.Kind.CONTEXT_RETURN, _on_context_return)


# ── 中心要手机做一整段事 ──────────────────────────────────────────────────────


async def delegate(
    device_id: str,
    goal: str,
    *,
    constraints: Optional[List[str]] = None,
    timeout: float = DEFAULT_DELEGATE_TIMEOUT_S,
    session_id: str = "",
) -> Dict[str, Any]:
    """把一整段目标交给装了桥接 Agent 的设备(手机本地循环),等它的结果。"""
    from core.device_onboarding.device_card import record_dispatch, record_result

    goal = (goal or "").strip()
    if not goal:
        return {"success": False, "error": "需要 goal"}
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
        {"goal": goal, "constraints": [str(c) for c in (constraints or [])]},
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
