#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/select_affected_tests.py — 分级验证阶梯的命令行入口。

改了哪些文件 → L0 该跑哪些测试、L0 可不可信、每一档该跑什么命令。判据见
:mod:`core.verification_ladder`。

用法
====
    python scripts/select_affected_tests.py core/x.py core/y.py      # 打印 L0 测试文件
    python scripts/select_affected_tests.py --git-diff origin/main   # 改动取自 git diff
    python scripts/select_affected_tests.py --level L1 core/x.py     # 打印这一档的命令
    python scripts/select_affected_tests.py --json core/x.py         # 完整计划

L0 不可信（``escalate_reason`` 非空）时退出码为 2，打印原因 —— 调用方据此上更高一档。
纯 AST 静态分析，不 import 任何业务模块，无需装依赖。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.verification_ladder import LEVELS, recommended_level, select_affected_tests  # noqa: E402


def _git_changed(base: str) -> List[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git diff 失败：{proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="改动的文件（仓库相对路径）")
    parser.add_argument("--git-diff", metavar="BASE", help="改动取自 git diff BASE...HEAD")
    parser.add_argument("--level", choices=LEVELS, help="打印这一档要跑的命令")
    parser.add_argument("--json", action="store_true", help="打印完整计划")
    args = parser.parse_args(argv)

    changed = list(args.paths) + (_git_changed(args.git_diff) if args.git_diff else [])
    if not changed:
        parser.error("没有给出任何改动的文件")
    plan = select_affected_tests(changed)

    if args.json:
        payload = plan.to_dict()
        payload["recommended_level"] = recommended_level(plan)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.level:
        commands = plan.commands(args.level)
        print("\n".join(commands) if commands else f"# {args.level} 本地没有可跑的命令")
    else:
        print("\n".join(plan.tests))

    if plan.escalate_reason:
        print(f"⚠️  L0 不可信：{plan.escalate_reason}；建议 {recommended_level(plan)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
