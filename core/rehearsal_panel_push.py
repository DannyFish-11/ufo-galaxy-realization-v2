"""core/rehearsal_panel_push.py — 把阈限态预演的每一步推给面板（WS ``type="rehearsal"``）。

``core/liminal_rehearsal.py`` 的文档写着「每步经 StateEventBus 的 skill.invoked 事件推到面板,推演过程可见」。
实测不成立：那条总线到面板只经 ``core.lumiv_websocket_bridge`` 的通配回调 —— 它对 ``skill.*`` 只做一件事：
安排一次**防抖的整份 panel_feed 推送**（设备清单）。步骤内容本身一个字都没到过面板，面板也没有任何地方画它。

这里补上那一段：每一步一帧 ``{"type": "rehearsal", "payload": {...}}``，走与对话消息同一条
``/ws/desktop-presence``、同一个广播（不走 IPC presence-state，理由同 ``_broadcast_conversation``：那条通道
被当作在场状态，塞别的 type 会污染它）。面板那侧见 ``electron/renderer/panel/src/ui/rehearsal.ts``。

payload 只放**类型化字段**，且每一项都截断：步骤名、第几轮、工具名、是否模拟、步数、未通过原因、任务摘要。
工具参数与模拟出的响应**不推** —— 那是推演的内部状态，推出去既无必要也可能带着用户数据。

非阻塞、永不抛出：推不出去只是面板少一行，预演本身照常。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("Galaxy.RehearsalPanelPush")

REHEARSAL_STEPS = ("attempt_start", "validation_reject", "tool_simulated", "attempt_success", "attempt_failed")

_TEXT_LIMITS = {"tool": 80, "feedback": 200, "task": 120}

_BACKGROUND: Set["asyncio.Task[Any]"] = set()


def rehearsal_frame(step: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把一步整理成推给面板的那一帧；认不出的步骤返回 ``None``（不推，不猜）。"""
    if step not in REHEARSAL_STEPS:
        return None
    body: Dict[str, Any] = {"step": step, "simulated": payload.get("simulated", True) is not False}
    attempt = payload.get("attempt")
    if isinstance(attempt, int):
        body["attempt"] = attempt
    steps = payload.get("steps")
    if isinstance(steps, int):
        body["steps"] = steps
    for key, limit in _TEXT_LIMITS.items():
        value = payload.get(key)
        if isinstance(value, str) and value:
            body[key] = value[:limit]
    return {"type": "rehearsal", "payload": body}


def push_rehearsal_step(step: str, payload: Dict[str, Any]) -> None:
    """在当前事件循环里排一次广播。不在循环里（同步调用方）就不推 —— 不为一行显示去阻塞调用方。"""
    frame = rehearsal_frame(step, payload)
    if frame is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        bridge = GalaxyPresenceBridge.get_instance()
        task = loop.create_task(bridge._ws_broadcast(frame))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
    except Exception as exc:  # noqa: BLE001 — 推不出去只是面板少一行
        logger.debug("预演步骤未推到面板: %s", exc)


__all__ = ["REHEARSAL_STEPS", "push_rehearsal_step", "rehearsal_frame"]
