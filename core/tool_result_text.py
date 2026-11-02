"""core/tool_result_text.py —— 一次工具调用的结果,交给模型的那段文字(第 10 轮真跑查出)。

主循环(``OpenClawd`` 的 ReAct)与 Agent 工厂的工具循环原先都是::

    str(result.get("result", result.get("error", "")))

只认 ``result`` 一个键。可智能体自家的工具族把结果放在别的键里:``devices__list`` 是 ``members`` / ``candidates``,
``tuning__list`` 是 ``topics``,``home__devices`` 是 ``devices``,``nodes__list`` 是 ``actions`` / ``groups`` ——
**模型收到的是一条空的工具消息**,设备卡、可调参数、家里有什么、节点有哪些动作,它从来没看到过;
真跑时假模型拿到空串,答了一句「(没拿到)」。有 ``result`` 的那些,交过去的又是 Python 的 ``repr``(单引号、``True``)。

现在一处说了算:

* 有 ``result``、别的键只是 ``success`` → 交 ``result``;
* 失败、只有 ``error`` → 交 ``error``(与原来一样);
* 其余 → 整个结果去掉 ``success`` 与内部键(``_`` 开头)交过去 —— 缺的参数表、几个候选、档位与谁批的都在里面。

字典与列表一律 JSON(中文原样),不交 ``repr``。
"""

from __future__ import annotations

import json
from typing import Any

_INTERNAL = "_"


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def tool_result_text(result: Any) -> str:
    """把一次工具调用的结果变成交给模型的文字。"""
    if not isinstance(result, dict):
        return _text(result)
    rest = {k: v for k, v in result.items() if k != "success" and not str(k).startswith(_INTERNAL)}
    if set(rest) == {"result"}:
        return _text(rest["result"])
    if set(rest) == {"error"}:
        return _text(rest["error"])
    return _text(rest) if rest else ""


__all__ = ["tool_result_text"]
