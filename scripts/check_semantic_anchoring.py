#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/check_semantic_anchoring.py — 决策路径不得从检索到的散文里反解结构。

这道闸守的是什么
================
被 Stage 0 修掉的那个缺陷有一个非常具体的形状：

    在同一个函数里，先 ``recall(...)`` 拿回按相似度排序的文本，
    再用 ``re.search(...)`` 把结构抠出来，然后拿它做决策。

它当时的后果是：``ExecutionPlanner`` 用一个"成功率"决定执行策略，而那个成功率的
分母是"按语义相似度召回的至多 8 条"，不是该策略的实际执行总数——样本由 embedding
决定，措辞一变数字就变。而同一份事实本来就有类型化版本（``TaskSummary.strategy``
是 str、``success`` 是 bool）躺在旁边没人读。

判据
====
读取的结果**若会改变控制流**（选策略 / 选设备 / 判权限 / 决定是否执行），必须走
对象层做确定性查询；**若只是进 prompt 供 LLM 参考**，走检索是对的、也应该继续走。

**该换的是决策路径，不是检索能力。** ``Node_105``、``academic_retrieval`` 面对的
本来就是非结构化文本，向量检索是对的工具，不在本闸的射程内。

为什么是脚本而不只是哨兵
========================
策略哨兵是文档，会被绕过；这个脚本是能在 CI 上失败的东西。它的有效性用最硬的方式
验证过——把扫描器指向 Stage 0 之前的真实代码，它精确抓到了
``_experience_strategy_adjust``（见 ``tests/test_semantic_anchoring_stage2.py`` C01）。
一道抓不到已知缺陷的守卫等于没有守卫。

扫描范围是一份**短的显式清单**（``core.semantic_anchoring.DECISION_PATH_MODULES``）
而不是全仓：全仓扫描会被无关的正则用法淹没成噪音，然后被关掉——那比一道窄而常开
的闸更糟。

用法
====
    python scripts/check_semantic_anchoring.py            # 有违规则非零退出
    python scripts/check_semantic_anchoring.py --list     # 打印判据与已审调用点
    python scripts/check_semantic_anchoring.py --json     # 机器可读报告
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.semantic_anchoring import (  # noqa: E402 — path bootstrap must precede import
    AUDITED_RETRIEVAL_CALL_SITES,
    DECISION_PATH_MODULES,
    DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY,
    RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY,
    RETRIEVAL_IS_ADVISORY_ONLY_POLICY,
    build_audit_report,
    scan_decision_paths,
)


def _print_doctrine() -> None:
    print("判据")
    print("=" * 72)
    for policy in (
        DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY,
        RETRIEVAL_IS_ADVISORY_ONLY_POLICY,
        RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY,
    ):
        print(f"\n  {policy}")
    print("\n\n扫描范围（决策路径模块）")
    print("=" * 72)
    for name in DECISION_PATH_MODULES:
        print(f"  {name}")
    print("\n已审计的检索调用点")
    print("=" * 72)
    for site in AUDITED_RETRIEVAL_CALL_SITES:
        print(f"  [{site['use']:<16}] {site['site']}")
        print(f"  {'':<18} → {site['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="打印判据、扫描范围与已审调用点")
    parser.add_argument("--json", action="store_true", help="输出机器可读报告")
    args = parser.parse_args(argv)

    if args.json:
        print(json.dumps(build_audit_report(), ensure_ascii=False, indent=2))
        return 0 if not scan_decision_paths() else 1

    if args.list:
        _print_doctrine()
        print()

    violations = scan_decision_paths()
    if not violations:
        print(f"\n✅ 决策路径干净：{len(DECISION_PATH_MODULES)} 个模块，未发现从检索文本反解结构的用法。")
        return 0

    print(f"\n❌ 发现 {len(violations)} 处决策路径从检索到的散文里反解结构：\n")
    for violation in violations:
        print(f"  {violation.describe()}\n")
    print("  这类值带的是检索的采样偏差，不是底层事实的权威。")
    print("  改为读对象层的类型化字段（参考 core/cognitive/experience_guidance.py 的做法）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
