"""galaxy_gateway/device_turns.py —— 设备发来的哪些帧是交给智能体跑一整轮的，不能在这条连接的读循环里等（第 13 轮）。

为什么
======
规范设备入口（``galaxy_gateway/routes/websocket.py::_handle_android_ws``）一帧一帧地读，每一帧都等处理完才读下一帧。
手表说一句话（``voice_query``）就是智能体的一整轮：调模型、调工具，遇到危险动作还要**在手表上**问人批准
（所有者的决定：手表 / 手机发起的在那台设备上批）。可手表的回答（``human_input``）走的是**同一条连接** ——
读循环正等着这一轮结束，读不到这个回答。

第 13 轮真跑：手表上说「用节点删文件」，0.3 秒手表上出现「要执行……吗」，点了「批准」，15 秒后照样按「超时、没人应答」不执行；
批、拒、不理三次，结果全是超时。这一轮里手表的心跳也一样读不到。

现在这几种帧放到后台跑，回包照样带着手表自己的 ``correlation_id`` 回去（手表按它认领）；其余的帧（认证、登记、能力、心跳、
通话信令 —— 有先后的）照旧按到达顺序一帧一帧处理。
"""

from __future__ import annotations

from typing import Any, Dict

#: 交给智能体跑一整轮的设备命令（可能要等人点头、跑很久）
AGENT_TURN_COMMANDS = frozenset({"voice_query"})


def _command(message: Dict[str, Any]) -> tuple:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    command = str(payload.get("command") or message.get("command") or "")
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    return command, inner


def runs_an_agent_turn(message: Dict[str, Any]) -> bool:
    """这一帧要交给智能体跑一整轮吗（是 → 后台跑，读循环接着读下一帧）。"""
    if not isinstance(message, dict) or message.get("type") != "command":
        return False
    command, inner = _command(message)
    if command in AGENT_TURN_COMMANDS:
        return True
    if command != "human_input":
        return False
    decision_id = str(inner.get("decision_id") or "")
    if not decision_id:
        return True  # 主动开口（不答任何一问）：交给智能体
    try:
        from core.interaction.pending_decision_registry import get_pending_decision_registry

        # 答的是正在等的那一问 → 马上处理（快，而且等着的那一轮就靠它）；答的是早已过期的 → 退回去交给智能体
        return get_pending_decision_registry().get(decision_id) is None
    except Exception:  # noqa: BLE001 — 查不了就按原来的顺序处理
        return False


__all__ = ["AGENT_TURN_COMMANDS", "runs_an_agent_turn"]
