"""读懂 ``AgentFactory.execute_agent_task`` 的回执:回答、成败、工具调用、用了哪家。

回执是 ``AgentFactory._run_agent`` 的形状::

    {"agent_id": ..., "status": "completed" | "simulated",
     "results": [{"output": "...", "provider": "...", "tool_calls": [...]} | {"error": "..."}]}

分裂执行时再套一层:``results`` 里是各个子 Agent 的回执(``split_and_parallel``),或者全部失败后
父 Agent 串行重跑的 ``fallback_result``(``split_fallback_serial``);整体超时只有顶层一个 ``error``。

``ExecutionPlanner`` 的单 Agent 路径原先只读顶层的 ``reply`` / ``result`` / ``success`` /
``tool_calls`` / ``provider`` —— 这几个键回执顶层**从来没有**。于是每一次单 Agent 执行都回
「任务已完成」,模型真正说的话被丢掉,失败也算成功,工具调用与厂商记录全空。真跑(本机假模型):
让它讲个笑话,回答是「任务已完成」。

``reply`` / ``result`` 在顶层时照旧优先(别的执行器、测试桩是这么给的)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

__all__ = ["AgentReceipt", "read_agent_receipt"]


@dataclass
class AgentReceipt:
    reply: str
    success: bool
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""


def _leaves(node: Any, out: List[Dict[str, Any]]) -> None:
    """回执树上真正执行过的那几个任务(有 output 或 error 的结点)。"""
    if not isinstance(node, dict):
        return
    if node.get("output") or node.get("error"):
        out.append(node)
    for child in node.get("results") or []:
        _leaves(child, out)
    _leaves(node.get("fallback_result"), out)


def read_agent_receipt(receipt: Dict[str, Any]) -> AgentReceipt:
    if not isinstance(receipt, dict):
        return AgentReceipt(reply=str(receipt or ""), success=bool(receipt))
    direct = receipt.get("reply") or receipt.get("result")
    if direct:
        return AgentReceipt(
            reply=str(direct),
            success=bool(receipt.get("success", True)),
            tool_calls=list(receipt.get("tool_calls") or []),
            provider=str(receipt.get("provider") or ""),
            model=str(receipt.get("model") or ""),
        )
    leaves: List[Dict[str, Any]] = []
    _leaves(receipt, leaves)
    done = [leaf for leaf in leaves if leaf.get("output") and not leaf.get("error")]
    calls = [tc for leaf in leaves for tc in (leaf.get("tool_calls") or []) if isinstance(tc, dict)]
    provider = next((str(leaf["provider"]) for leaf in done if leaf.get("provider")), "")
    model = next((str(leaf["model"]) for leaf in done if leaf.get("model")), "")
    if done and all(leaf.get("simulated") for leaf in done):
        # 没有模型时 Agent 只回一句「已处理任务(无 LLM 模式)」—— 那不是做了,是没做。
        return AgentReceipt(reply="没有可用的模型,这个任务没有真正执行。", success=False, tool_calls=calls)
    if done:
        return AgentReceipt(
            reply="\n".join(str(leaf["output"]) for leaf in done if not leaf.get("simulated")),
            success=True,
            tool_calls=calls,
            provider=provider,
            model=model,
        )
    errors = [str(leaf["error"]) for leaf in leaves if leaf.get("error")]
    if errors:
        return AgentReceipt(reply=f"这次没做成:{errors[0]}", success=False, tool_calls=calls)
    return AgentReceipt(reply="这次没有拿到任何结果。", success=False, tool_calls=calls)
