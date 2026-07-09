"""Omnigent function guardrail:会话累计成本超过 max_cost_usd 时要求人工确认。

以 omnigent 0.4.0 的 function policy 约定编写(guardrails.policies.<name>.function
指向 path + arguments)。Omnigent 为 alpha,策略回调的确切签名以目标机器上安装的
版本为准;若签名不符,M4 冒烟测试会暴露,届时按 BUILD_SPEC 的三选一流程上报。
"""

from __future__ import annotations

from typing import Any


def enforce(event: Any, *, max_cost_usd: float = 5.0, **_: Any) -> dict[str, Any]:
    cost = 0.0
    for source in (event, getattr(event, "session", None)):
        value = getattr(source, "total_cost_usd", None)
        if value is None and isinstance(source, dict):
            value = source.get("total_cost_usd")
        if value is not None:
            cost = float(value)
            break
    if cost >= max_cost_usd:
        return {
            "action": "ask",
            "reason": f"会话累计成本 ${cost:.2f} 已达上限 ${max_cost_usd:.2f},需人工确认后继续",
        }
    return {"action": "allow"}
