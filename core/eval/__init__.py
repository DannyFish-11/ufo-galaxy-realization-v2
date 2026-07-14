"""
core/eval/ — Agent 轨迹评估框架（L4 的"标尺"）
================================================

在改动记忆/规划/反思等"会影响智能"的东西之前，先有一把可量化的尺子：
给定一组任务用例，跑 agent、对其**输出与轨迹**打分，产出可对比的报告
（通过率/平均分/逐例明细 + 与基线对比的回归项）。

刻意与具体 agent 解耦：``EvalRunner`` 接收一个 ``agent_fn(prompt)->result``，
因此既能跑真实 OpenClawd，也能用 fake agent 做单测（无需模型/key）。

result 约定（与 agent_factory 的输出兼容）::

    {"output": str, "success": bool,
     "tool_calls": [{"tool"/"tool_name": str, ...}], ...}
"""

from core.eval.cases import EvalCase, builtin_cases, load_cases
from core.eval.memory_eval import MemoryEvalCase, MemoryEvalReport, run_memory_eval
from core.eval.runner import EvalReport, EvalRunner, run_eval
from core.eval.scorer import CaseScore, score_case

__all__ = [
    "EvalCase",
    "builtin_cases",
    "load_cases",
    "CaseScore",
    "score_case",
    "EvalReport",
    "EvalRunner",
    "run_eval",
    "MemoryEvalCase",
    "MemoryEvalReport",
    "run_memory_eval",
]
