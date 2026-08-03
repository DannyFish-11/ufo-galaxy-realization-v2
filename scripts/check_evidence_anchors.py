#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/check_evidence_anchors.py — 生产代码里的「证据锚点」必须指向真实存在的东西。

为什么需要这道门
================
仓里有大量模块把「某个文件 / 某个模块」当作论据写进字符串常量：

    v2_anchors=["core/unified_result_ingress.py", ...]      # 完成度评审的证据
    code_evidence=("core.routing_observability", ...)        # 边界轴的代码证据
    KNOWN_SHIM_FILES = {"core/architecture_invariants.py"}   # 债务冻结豁免名单

**这些字符串没有任何机制保证它们指向的东西还在。** 文件被删掉、模块被改名，
字符串照样躺在那里，评审报告照样"通过"。已经踩到的具体后果：

* 删掉一个死模块后，``tools/architecture/architecture_invariants.py`` 里那个
  只负责转发给它的检查变成恒定报错，三条单测转红 —— 但没有任何一道门在删除时
  提前告诉我们有这个消费者。
* ``config/file_complexity_baseline.json`` 里留着已删文件的复杂度基线。基线条目
  是**放宽**用的：哪天有人新建同名文件，会白拿一份祖传高预算。
* ``core/complete_joint_system_review.py`` 一边声明"只用当前真实代码作证据"，
  一边把一个已删文件列为"本次已补强"的成果锚点。

这与 ``scripts/check_completion_matrix.py`` 是同一个思路（那道门只管
audit/completion_matrix.json 一个文件），这里把它推广到全部生产代码。

判据边界
========
只校验**能被机器判定**的那一件事：路径存在 / 模块可导入。锚点选得对不对、
论据够不够强，是人的判断，硬做只会制造噪音。

**不扫 tests/。** 测试里大量出现 ``core/foo.py``、``tests/t.py`` 这类合成路径，
它们是构造用例的素材而非证据锚点，扫了全是误报。

用法
====
    python scripts/check_evidence_anchors.py            # 报告并在有问题时退出 1
    python scripts/check_evidence_anchors.py --list     # 只列出扫到的锚点总数
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# 扫描范围：生产代码。tests/ 见模块文档串里的说明，故意排除。
SCAN_DIRS = ("core", "galaxy_gateway", "contracts", "scripts", "tools", "audit", "fusion")

# 「看起来像仓内相对路径」的字符串。必须带已知顶层目录前缀 + 已知扩展名，
# 否则会把 URL 片段、日志格式串之类的东西也卷进来。
PATH_LITERAL_RE = re.compile(
    r"^(?:core|tests|galaxy_gateway|contracts|scripts|tools|nodes|audit|config|docs|fusion)"
    r"/[\w/\-.]+\.(?:py|json|md|ya?ml)$"
)

# 已知的、不指向真实文件的占位路径。加进来必须写明理由。
PATH_ALLOWLIST = {
    # github_installer 生成的文档站点入口，产物路径而非仓内文件。
    "docs/index.md",
}

# 复杂度基线是**放宽**用的：条目指向已删文件时，同名文件重新出现会白拿高预算。
COMPLEXITY_BASELINE = REPO_ROOT / "config" / "file_complexity_baseline.json"


def _iter_python_files() -> List[Path]:
    files: List[Path] = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def check_path_literals() -> List[Tuple[str, str]]:
    """返回 [(锚点, "文件:行号"), ...] —— 指向不存在文件的路径字面量。"""
    problems: List[Tuple[str, str]] = []
    for f in _iter_python_files():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            # 语法错误由别的门负责报，这里不重复。
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            value = node.value.strip()
            if not PATH_LITERAL_RE.match(value) or value in PATH_ALLOWLIST:
                continue
            if not (REPO_ROOT / value).exists():
                rel = f.relative_to(REPO_ROOT)
                problems.append((value, f"{rel}:{node.lineno}"))
    return problems


def check_complexity_baseline() -> List[str]:
    """复杂度基线里指向已删文件的条目。"""
    if not COMPLEXITY_BASELINE.exists():
        return []
    try:
        data = json.loads(COMPLEXITY_BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries: Dict[str, object] = data.get("files", data) if isinstance(data, dict) else {}
    return sorted(k for k in entries if isinstance(k, str) and k.endswith(".py") and not (REPO_ROOT / k).exists())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="只统计扫到的锚点数量，不判定")
    args = parser.parse_args()

    dangling_paths = check_path_literals()
    stale_baseline = check_complexity_baseline()

    if args.list:
        print(f"扫描目录：{', '.join(SCAN_DIRS)}")
        print(f"悬空路径字面量：{len(dangling_paths)}")
        print(f"陈旧复杂度基线条目：{len(stale_baseline)}")
        return 0

    failed = False

    if dangling_paths:
        failed = True
        print("❌ 以下路径字面量指向不存在的文件：\n")
        for anchor, where in sorted(dangling_paths):
            print(f"  {anchor}")
            print(f"      ← {where}")
        print(
            "\n  这些字符串被当作证据/名单在用，指向的文件已经没了。"
            "\n  要么改成真实存在的路径，要么把这条记录一起删掉。"
            "\n  确属占位符（不打算指向真实文件）时，加进本脚本的 PATH_ALLOWLIST 并写明理由。\n"
        )

    if stale_baseline:
        failed = True
        print("❌ config/file_complexity_baseline.json 里有指向已删文件的基线条目：\n")
        for k in stale_baseline:
            print(f"  {k}")
        print(
            "\n  基线条目是**放宽**用的。文件已删还留着条目，"
            "\n  哪天新建同名文件会直接白拿一份祖传高预算，绕过复杂度门。删掉即可。\n"
        )

    if failed:
        return 1

    print("✅ 证据锚点检查通过 —— 所有路径字面量与复杂度基线条目都指向真实存在的文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
