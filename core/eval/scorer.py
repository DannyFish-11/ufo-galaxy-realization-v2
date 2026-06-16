"""core/eval/scorer.py — 基于规则的轨迹打分（确定性、无需 LLM/key）。

把一个 agent result 与 EvalCase 的判定标准比对，给出 0~1 的分 + 通过与否 + 明细。
每个被设置的判据是一个等权检查项；分 = 通过项 / 总项。无判据的用例只看 success。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.eval.cases import EvalCase


@dataclass
class CaseScore:
    case_id: str
    score: float                       # 0.0~1.0
    passed: bool                       # score == 1.0(全部判据通过)
    checks: Dict[str, bool] = field(default_factory=dict)
    detail: str = ""


def _tool_names(result: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for tc in (result.get("tool_calls") or []):
        if isinstance(tc, dict):
            n = tc.get("tool") or tc.get("tool_name") or ""
            if n:
                names.append(str(n).lower())
    return names


def score_case(case: EvalCase, result: Dict[str, Any]) -> CaseScore:
    output = str(result.get("output") or result.get("reply") or "").lower()
    tools = _tool_names(result)
    checks: Dict[str, bool] = {}

    for kw in case.must_contain:
        checks[f"contains:{kw}"] = kw.lower() in output
    for kw in case.must_not_contain:
        checks[f"absent:{kw}"] = kw.lower() not in output
    if case.expect_tools:
        # 命中任一期望工具(名称子串匹配)即算通过该项
        checks["tool_used"] = any(
            any(exp.lower() in t for t in tools) for exp in case.expect_tools
        )
    if case.expect_success is not None:
        checks["success"] = bool(result.get("success", True)) == case.expect_success

    if not checks:
        # 无显式判据 → 退化为 success 检查
        ok = bool(result.get("success", True))
        return CaseScore(case.id, 1.0 if ok else 0.0, ok, {"success": ok})

    passed_n = sum(1 for v in checks.values() if v)
    score = passed_n / len(checks)
    detail = ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in checks.items())
    return CaseScore(case.id, round(score, 4), score >= 1.0, checks, detail)
