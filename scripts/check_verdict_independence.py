#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/check_verdict_independence.py — 裁决不得由被裁决者自己报。

判据与四个签名的定义见 :mod:`core.verdict_independence`。本脚本只是它的命令行门：

* 出现存量清单之外的命中 → 退出码 1（新缺陷）
* 存量清单里有条目已经扫不到 → 退出码 1（修掉了却没从清单里删，清单会因此失去意义）

用法
====
    python scripts/check_verdict_independence.py           # 门
    python scripts/check_verdict_independence.py --list    # 打印全部命中与豁免
    python scripts/check_verdict_independence.py --json    # 机器可读报告
    python scripts/check_verdict_independence.py --file some_patch.py   # 扫任意文件（S1–S3）

``--file`` 用于代码落进 core/ 之前：审查一个补丁、一段生成出来的工具定义，
不必先把它放进仓库再跑全仓扫描。

纯 AST 静态分析，不 import 任何业务模块，无需装依赖。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.verdict_independence import (  # noqa: E402 — path bootstrap must precede import
    KNOWN_UNRESOLVED,
    PROPOSER_MUST_NOT_SELF_CERTIFY_POLICY,
    VERDICT_FLOWS_THROUGH_ENFORCEMENT_POLICY,
    VERDICT_WRITER_EXEMPTIONS,
    build_verdict_independence_report,
    scan_repository,
    scan_source_for_self_certification,
    stale_known_entries,
    unresolved_findings,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="打印判据、全部命中与豁免")
    parser.add_argument("--json", action="store_true", help="输出机器可读报告")
    parser.add_argument("--file", action="append", default=[], help="只扫这些文件（可重复），跑 S1–S3")
    args = parser.parse_args(argv)

    if args.file:
        hits = []
        for raw in args.file:
            path = Path(raw)
            hits.extend(scan_source_for_self_certification(path.read_text(encoding="utf-8"), str(path)))
        for f in hits:
            print(f"  [{f.signature}] {f.path}:{f.line}  {f.detail}")
        print(f"{'❌' if hits else '✅'} {len(args.file)} 个文件，{len(hits)} 处提案者自报成绩。")
        return 1 if hits else 0

    if args.json:
        print(json.dumps(build_verdict_independence_report(), ensure_ascii=False, indent=2))
        return 0

    findings = scan_repository()
    new = unresolved_findings(findings)
    stale = stale_known_entries(findings)

    if args.list:
        print("判据")
        print("=" * 72)
        print(PROPOSER_MUST_NOT_SELF_CERTIFY_POLICY)
        print(VERDICT_FLOWS_THROUGH_ENFORCEMENT_POLICY)
        print()
        print(f"全部命中（{len(findings)}）")
        for f in findings:
            print(f"  [{f.signature}] {f.path}:{f.line}  {f.detail}")
        print()
        print(f"S4 豁免（{len(VERDICT_WRITER_EXEMPTIONS)}）")
        for path, reason in VERDICT_WRITER_EXEMPTIONS.items():
            print(f"  {path}: {reason}")
        print()

    failed = False
    if new:
        failed = True
        print(f"❌ 发现 {len(new)} 处新的「提案者自报成绩」：")
        for f in new:
            print(f"  [{f.signature}] {f.path}:{f.line}  {f.detail}")
        print("  模型可以提议跑哪条验证，不可以报告验证结果；结果由 harness 实跑读退出码，")
        print("  经 classify_execution_evidence() 定级。")
    if stale:
        failed = True
        print(f"❌ 存量清单里有 {len(stale)} 条已经扫不到 —— 请从 KNOWN_UNRESOLVED 里删掉：")
        for key in stale:
            print(f"  {key}")
    if failed:
        return 1

    remaining = len(KNOWN_UNRESOLVED)
    suffix = f"（存量 {remaining} 处已记入清单，待修）" if remaining else ""
    print(f"✅ 没有新增的提案者自报成绩{suffix}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
