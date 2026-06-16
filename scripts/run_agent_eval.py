#!/usr/bin/env python3
"""scripts/run_agent_eval.py — 跑一轮 agent 轨迹评估并打印/保存报告。

用法:
    python -m scripts.run_agent_eval                      # 内置用例 + 真实 agent
    python -m scripts.run_agent_eval --cases cases.jsonl  # 自定义用例集
    python -m scripts.run_agent_eval --baseline base.json # 与基线对比, 报告回归
    python -m scripts.run_agent_eval --out report.json    # 保存报告

真实 agent 需要配置好 LLM key / 本地模型；未就绪时每个用例记为失败(报告仍可产出)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict


async def galaxy_agent_fn(prompt: str) -> Dict[str, Any]:
    """把一条 prompt 跑过真实 OpenClawd，归一化成评估 result。"""
    from core.openclawd import get_openclawd

    clawd = get_openclawd()
    res = await clawd.process(message=prompt, device_id="eval", session_id="eval_session")
    if not isinstance(res, dict):
        return {"output": str(res), "success": True, "tool_calls": []}
    # 归一化：OpenClawd/agent_factory 的输出 → 评估约定字段
    tool_calls = res.get("tool_calls") or (res.get("task_result") or {}).get("tool_calls") or []
    return {
        "output": res.get("response") or res.get("reply") or res.get("output") or "",
        "success": bool(res.get("success", True)),
        "tool_calls": tool_calls,
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="run_agent_eval")
    ap.add_argument("--cases", default="", help="JSONL 用例集路径(默认内置)")
    ap.add_argument("--baseline", default="", help="基线报告 JSON 路径(用于回归对比)")
    ap.add_argument("--out", default="", help="保存报告 JSON 路径")
    args = ap.parse_args()

    sys.path.insert(0, os.getcwd())
    from core.eval import EvalRunner, load_cases
    from core.eval.runner import EvalReport

    cases = load_cases(args.cases)
    report = asyncio.run(EvalRunner(cases).run(galaxy_agent_fn))
    d = report.to_dict()

    print(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"\n通过率 {report.pass_rate:.0%} | 平均分 {report.avg_score:.3f} | "
          f"{report.passed}/{report.total} 通过")

    if args.baseline and os.path.exists(args.baseline):
        try:
            base_d = json.load(open(args.baseline, encoding="utf-8"))
            base = EvalReport(
                total=base_d["total"], passed=base_d["passed"],
                avg_score=base_d["avg_score"], pass_rate=base_d["pass_rate"],
            )
            from core.eval.scorer import CaseScore
            base.scores = [CaseScore(c["id"], c["score"], c["passed"]) for c in base_d.get("cases", [])]
            regs = report.regressions_vs(base)
            print(f"回归项({len(regs)}): {regs}" if regs else "无回归 ✅")
        except Exception as exc:  # noqa: BLE001
            print(f"基线对比跳过: {exc}")

    if args.out:
        json.dump(d, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"报告已保存: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
