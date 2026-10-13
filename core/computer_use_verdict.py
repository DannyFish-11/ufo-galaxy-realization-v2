"""core/computer_use_verdict.py — Computer Use 的结果走真相链:模型说「做完了」是自报,不是裁决
==========================================================================================

所有者 2026-10-13 选 A:Computer Use 做完的任务也进结果真相链。原先闭环里模型回一个 ``done`` 就算完 ——
``success`` 直接等于模型的自报,只记进操作记忆,没有任何东西核对过屏幕上到底成了没有。

现在模型的 ``done`` 只记为 ``claimed_done``(自报),裁决另起:

1. **独立核对**:重新取一张**当前**屏幕,交给一个**只看任务与这张屏幕**的核对请求(它看不到规划过程、
   看不到模型的自报),回「做完了 / 没做完 / 说不准」。
2. **裁决**:由规范执法函数 :func:`core.execution_evidence_model.classify_execution_evidence` 给出四值
   ``EvidenceTrustLevel``,不是分数:

   * 核对说做完了 → ``locally_executed`` + 证据链完整 → ``trusted``;
   * 核对说没做完 → ``partially_completed`` → ``quarantine``(没收口);
   * 没法核对(没有新鲜屏幕、没有能看图的模型、回答认不出) → ``locally_executed`` 证据链不完整 → ``provisional``
     —— 照实标「没法独立核对」,不当成失败,也不当成确认。

3. **没收口的**:与 ``task_result`` 同一条规矩 —— 「自动重试,失败再隔离」。后台(``RETRY_DELAY_S`` 秒后)把
   **没做完的部分**再交给闭环做一次、再核对一次;仍不行就进隔离队列(:mod:`core.truth_chain_recovery`,
   ``kind="computer_use"``),面板「没收口的结果」里人可以「再试一次」「认可」或「知道了」。
   人正在用电脑时不在后台动键鼠 —— 直接进队列,原因写清。

模型自己说放弃(``fail``)、步数用完、原地打转、看不到屏幕 —— 这些本来就没说做完,回答里照实说了失败,
不进队列(那不是「账对不上」,是「没做成」)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.ComputerUse.Verdict")

KIND = "computer_use"

CHECK_VERIFIED = "verified"
CHECK_NOT_DONE = "not_done"
CHECK_UNVERIFIABLE = "unverifiable"

_CHECK_SYSTEM = (
    "你是独立的核对员。给你一个桌面任务和一张**当前**屏幕截图,只根据这张截图判断这个任务是否已经完成。"
    "你看不到任何人的操作过程,也不要相信任何「已经完成」的说法 —— 只看屏幕上的事实。"
    '只回一行 JSON:{"done": true 或 false, "reason": "一句话依据"};截图看不出来就回 {"done": null, "reason": "…"}。'
)

#: 核对请求的期限,与闭环里一次规划调用的期限相同(``core.windows_execution_arbiter._sync_dispatch_budget_s`` 按它多算一步)
CHECK_TIMEOUT_S = 60.0

Perceive = Callable[[], Awaitable[Optional[str]]]
Ask = Callable[[str, str], Awaitable[Optional[Dict[str, Any]]]]


async def _default_perceive() -> Optional[str]:
    from core.computer_use_loop import _default_perceive as perceive

    return await perceive()


def _parse(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return out if isinstance(out, dict) else None


async def _default_ask(instruction: str, screen_b64: str) -> Optional[Dict[str, Any]]:
    """问一次核对员。没有能用的模型(``provider="none"``)返回 ``None``。"""
    from core.multi_llm_router import get_llm_router

    messages = [
        {"role": "system", "content": _CHECK_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"任务:{instruction}\n\n这是现在的屏幕。这个任务完成了吗?"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screen_b64}"}},
            ],
        },
    ]
    resp = await get_llm_router().chat(messages=messages, task_type="agent_control", max_tokens=200)
    if getattr(resp, "provider", "") == "none":
        return None
    return _parse(getattr(resp, "content", "") or "")


async def independent_check(
    instruction: str, *, perceive: Optional[Perceive] = None, ask: Optional[Ask] = None
) -> Tuple[str, str]:
    """(``verified`` / ``not_done`` / ``unverifiable``, 依据)。只看任务与当前屏幕。"""
    screen = await (perceive or _default_perceive)()
    if not screen:
        return CHECK_UNVERIFIABLE, "没有新鲜的屏幕画面,没法独立核对"
    try:
        said = await asyncio.wait_for((ask or _default_ask)(instruction, screen), CHECK_TIMEOUT_S)
    except asyncio.TimeoutError:
        return CHECK_UNVERIFIABLE, f"核对请求 {CHECK_TIMEOUT_S:.0f} 秒没回,没法独立核对"
    except Exception as exc:  # noqa: BLE001 — 核对本身失败 ≠ 任务失败
        logger.warning("computer_use 独立核对出错: %s", exc)
        return CHECK_UNVERIFIABLE, f"核对请求出错({type(exc).__name__}),没法独立核对"
    if said is None:
        return CHECK_UNVERIFIABLE, "没有能看图的模型来核对"
    reason = str(said.get("reason") or "").strip()[:200]
    if said.get("done") is True:
        return CHECK_VERIFIED, reason or "核对员看当前屏幕确认已完成"
    if said.get("done") is False:
        return CHECK_NOT_DONE, reason or "核对员看当前屏幕认为没完成"
    return CHECK_UNVERIFIABLE, reason or "核对员从这张屏幕看不出来"


def classify(check: str) -> str:
    """独立核对的结论 → 四值裁决(规范执法函数给,不在这里自己定)。"""
    from core.execution_evidence_model import ExecutionEvidenceState, classify_execution_evidence

    if check == CHECK_VERIFIED:
        level = classify_execution_evidence(ExecutionEvidenceState.locally_executed, truth_chain_complete=True)
    elif check == CHECK_NOT_DONE:
        level = classify_execution_evidence(ExecutionEvidenceState.partially_completed)
    else:
        level = classify_execution_evidence(ExecutionEvidenceState.locally_executed, truth_chain_complete=False)
    return level.value


def _someone_is_using_the_computer() -> bool:
    try:
        from core.presence_line import foreground_request_active

        return bool(foreground_request_active())
    except Exception:  # noqa: BLE001 — 判不出来就当有人在用,宁可不在后台动手
        return True


def _continue_instruction(instruction: str, reason: str) -> str:
    return f"{instruction}\n\n(上一次以为做完了,但对着屏幕核对没通过:{reason}。从当前屏幕继续,只做还没完成的部分。)"


async def rerun_once(message: Dict[str, Any], by_human: bool = False) -> Tuple[bool, str]:
    """隔离队列的重跑器:把没做完的部分再交给闭环做一次,再独立核对一次。回 ``(收口没有, 原因)``。

    后台自动的那一次:人正在用电脑就不动手。人在面板上点「再试一次」:就是那个人要做,照做。
    """
    if not by_human and _someone_is_using_the_computer():
        return False, "人正在用电脑,没有在后台动键鼠"
    from core.computer_use_loop import run_computer_use_task

    instruction = str(message.get("instruction") or "")
    if not instruction:
        return False, "没留下任务内容,没法再做"
    result = await run_computer_use_task(
        _continue_instruction(instruction, str(message.get("reason") or "")), verify=False
    )
    if result.get("stop_reason") != "done":
        return False, f"再做一次没做完({result.get('stop_reason')}):{str(result.get('message') or '')[:120]}"
    check, why = await independent_check(instruction)
    if classify(check) == "trusted":
        return True, why
    return False, why


async def settle(
    instruction: str,
    result: Dict[str, Any],
    *,
    perceive: Optional[Perceive] = None,
    ask: Optional[Ask] = None,
    schedule: bool = True,
) -> Dict[str, Any]:
    """闭环跑完之后定结论。只处理「模型说做完了」;别的结果原样返回。"""
    if result.get("stop_reason") != "done":
        return result
    check, why = await independent_check(instruction, perceive=perceive, ask=ask)
    level = classify(check)
    out = {**result, "claimed_done": True, "check": check, "verdict": level, "verdict_reason": why}
    out.setdefault("task_id", f"cu_{uuid.uuid4().hex[:12]}")
    card = str(result.get("run_id") or "")
    if level == "trusted":
        out["success"] = True
        _island(card, "做完了", "对着屏幕核对过", why, "success")
        return out
    if level == "provisional":
        out["success"] = True
        out["message"] = f"{result.get('message') or '做完了'}(没法独立核对:{why})"
        _island(card, "做完了", "没法独立核对", why, "info")
        return out
    out["success"] = False
    out["message"] = f"说做完了,但对着屏幕核对没通过:{why}"
    if not schedule:
        _island(card, "核对没通过", why, why, "warning")
        return out
    from core.truth_chain_recovery import get_truth_chain_recovery, register_rerunner

    register_rerunner(KIND, rerun_once)
    record = {
        "task_id": out["task_id"],
        "result_status": "claimed_done",
        "incomplete_reason": why,
        "steps": len(result.get("steps") or []),
    }
    if _someone_is_using_the_computer():
        # 人在用电脑:不排后台重跑,直接进队列,由人决定
        get_truth_chain_recovery().isolate(
            out["task_id"], KIND, record, {"instruction": instruction, "reason": why}, why
        )
        out["follow_up"] = "人正在用电脑,没有在后台再试;已进「没收口的结果」"
        _island(card, "核对没通过", "已进「没收口的结果」", why, "warning", action="panel")
        return out
    get_truth_chain_recovery().schedule_rerun(out["task_id"], KIND, record, {"instruction": instruction, "reason": why})
    out["follow_up"] = "后台再做一次没完成的部分;还不行会进「没收口的结果」"
    _island(card, "核对没通过", "稍后在后台再做一次没完成的部分", why, "warning")
    return out


def _island(card_id: str, title: str, subtitle: str, body: str, tone: str, *, action: str = "") -> None:
    """灵动岛上把「桌面操作」那张卡原地换成结论(core.island_cards)。没有卡号(不是闭环跑出来的)就不推。"""
    if not card_id:
        return
    from core.island_cards import post_card

    post_card(
        card_id, kind="computer_use", title=title, subtitle=subtitle, body=body, tone=tone, ttl_s=12, action=action
    )


def register() -> None:
    """进程起来时登记重跑器(隔离队列里留下的 computer_use 条目,人点「再试一次」时要用)。"""
    from core.truth_chain_recovery import register_rerunner

    register_rerunner(KIND, rerun_once)


__all__ = [
    "CHECK_NOT_DONE",
    "CHECK_TIMEOUT_S",
    "CHECK_UNVERIFIABLE",
    "CHECK_VERIFIED",
    "KIND",
    "classify",
    "independent_check",
    "register",
    "rerun_once",
    "settle",
]
