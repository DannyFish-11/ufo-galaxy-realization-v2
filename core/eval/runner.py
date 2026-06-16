"""core/eval/runner.py — 评估执行器 + 报告 + 基线回归对比。"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from core.eval.cases import EvalCase, builtin_cases
from core.eval.scorer import CaseScore, score_case

# agent_fn: 接收 prompt(str)，返回 result dict（可同步或异步）。
AgentFn = Callable[[str], Union[Dict[str, Any], Awaitable[Dict[str, Any]]]]


@dataclass
class EvalReport:
    total: int
    passed: int
    avg_score: float
    pass_rate: float
    scores: List[CaseScore] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 4),
            "avg_score": round(self.avg_score, 4),
            "duration_ms": round(self.duration_ms, 1),
            "cases": [
                {"id": s.case_id, "score": s.score, "passed": s.passed, "detail": s.detail}
                for s in self.scores
            ],
        }

    def regressions_vs(self, baseline: "EvalReport") -> List[str]:
        """返回相对基线分数下降的用例 id 列表（回归项）。"""
        base = {s.case_id: s.score for s in baseline.scores}
        return [s.case_id for s in self.scores if s.case_id in base and s.score < base[s.case_id]]


class EvalRunner:
    def __init__(self, cases: Optional[List[EvalCase]] = None) -> None:
        self.cases = cases or builtin_cases()

    async def _invoke(self, agent_fn: AgentFn, prompt: str) -> Dict[str, Any]:
        try:
            out = agent_fn(prompt)
            if inspect.isawaitable(out):
                out = await out
            return out if isinstance(out, dict) else {"output": str(out), "success": True}
        except Exception as exc:  # noqa: BLE001 — agent 异常记为失败用例，不中断整轮
            return {"output": "", "success": False, "error": str(exc)}

    async def run(self, agent_fn: AgentFn) -> EvalReport:
        t0 = time.monotonic()
        scores: List[CaseScore] = []
        for case in self.cases:
            result = await self._invoke(agent_fn, case.prompt)
            scores.append(score_case(case, result))
        dur = (time.monotonic() - t0) * 1000
        n = len(scores) or 1
        passed = sum(1 for s in scores if s.passed)
        avg = sum(s.score for s in scores) / n
        return EvalReport(
            total=len(scores), passed=passed,
            avg_score=avg, pass_rate=passed / n,
            scores=scores, duration_ms=dur,
        )


def run_eval(agent_fn: AgentFn, cases: Optional[List[EvalCase]] = None) -> EvalReport:
    """同步便捷入口。"""
    return asyncio.run(EvalRunner(cases).run(agent_fn))
