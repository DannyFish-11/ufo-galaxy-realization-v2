"""core/eval/cases.py — 评估用例 schema + 内置用例集 + JSONL 加载。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvalCase:
    """一个评估用例：给 agent 的 prompt + 对其结果的判定标准。"""

    id: str
    prompt: str
    must_contain: List[str] = field(default_factory=list)  # 输出须含全部(大小写不敏感)
    must_not_contain: List[str] = field(default_factory=list)  # 输出不得含任一
    expect_tools: List[str] = field(default_factory=list)  # 轨迹中应出现的工具名
    expect_success: Optional[bool] = None  # 期望 result.success
    weight: float = 1.0
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalCase":
        return cls(
            id=str(d["id"]),
            prompt=str(d.get("prompt", "")),
            must_contain=list(d.get("must_contain", [])),
            must_not_contain=list(d.get("must_not_contain", [])),
            expect_tools=list(d.get("expect_tools", [])),
            expect_success=d.get("expect_success"),
            weight=float(d.get("weight", 1.0)),
            tags=list(d.get("tags", [])),
        )


def builtin_cases() -> List[EvalCase]:
    """一组最小的内置用例（冒烟级；真实评估请用更大的 JSONL 数据集）。"""
    return [
        EvalCase(
            id="smoke_chat_greeting",
            prompt="用一句话礼貌地打个招呼。",
            must_contain=[],
            expect_success=True,
            tags=["chat", "smoke"],
        ),
        EvalCase(
            id="tool_list_files",
            prompt="列出当前目录下的文件。",
            expect_tools=["filesystem", "shell", "list"],  # 任一类文件/列目录工具
            expect_success=True,
            tags=["tool", "smoke"],
        ),
        EvalCase(
            id="reasoning_capital",
            prompt="法国的首都是哪座城市？只回答城市名。",
            must_contain=["巴黎"],
            must_not_contain=["伦敦", "柏林"],
            expect_success=True,
            tags=["reasoning"],
        ),
    ]


def load_cases(path: str) -> List[EvalCase]:
    """从 JSONL(每行一个用例 dict) 加载用例集；文件不存在/为空则返回内置用例。"""
    if not path or not os.path.exists(path):
        return builtin_cases()
    cases: List[EvalCase] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(EvalCase.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return cases or builtin_cases()
