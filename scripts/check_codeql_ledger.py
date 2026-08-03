#!/usr/bin/env python3
"""scripts/check_codeql_ledger.py — 把 CodeQL 的结果和处置台账对账。

要解决什么
----------
CodeQL 的分析结果只进 Security 页。排查的时候只知道"还有 N 条告警",既读不到
是哪 N 条,也分不清"这条判过了"和"这条是今天新冒出来的"。结果就是:**存量把新增
淹掉**。本仓在别处已经踩过同一种病 —— 一道长期红着的闸,和没有闸没有区别。

这个脚本做的事很小:拿当轮 SARIF 里的每一条,去
``config/codeql_findings_ledger.json`` 里找它的处置结论。

  * 台账里有 → 已经有人回答过"为什么它不该被改",放过;
  * 台账里没有 → **新增**,报出来;
  * 台账里有、SARIF 里没有了 → 已经修掉或规则变了,提示可以从台账里删。

和本仓其它守卫一样,判据是"增量",不是"总数"。

刻意的取舍
----------
* 位置比到 ``文件:行号``。行号会随无关改动漂移 —— 那时这里会报一条"新增"和一条
  "已消失",看起来吵,但**那正是需要有人看一眼的时刻**:告警还在不在、是不是同一条。
  只比文件名会让"同一个文件里新增了一处"完全隐形,而那才是真正要抓的东西。
* 不做严重性过滤。CodeQL 在本仓的输出里 ``problem.severity`` 大量缺失(显示为 ?),
  按它过滤等于按一个不存在的字段过滤。
* 找不到 SARIF 时**判失败**而不是跳过。一个"找不到就当通过"的守卫,在产物路径
  变化的那天会静默失效,而那正是这类守卫要防的病本身。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "config" / "codeql_findings_ledger.json"


def load_ledger(path: Path = LEDGER_PATH) -> Tuple[Set[Tuple[str, str]], Dict[Tuple[str, str], str]]:
    """读台账,返回 ``{(rule, location)}`` 与它们各自的处置状态。"""
    if not path.is_file():
        raise SystemExit(f"❌ 找不到台账 {path} —— 没有台账就无法区分存量与新增,判失败而不是放过。")
    data = json.loads(path.read_text(encoding="utf-8"))
    recorded: Set[Tuple[str, str]] = set()
    status: Dict[Tuple[str, str], str] = {}
    for entry in data.get("findings", []):
        rule = entry["rule"]
        for loc in entry.get("locations", []):
            key = (rule, loc)
            recorded.add(key)
            status[key] = entry.get("status", "?")
    return recorded, status


def load_sarif(paths: List[Path]) -> Set[Tuple[str, str]]:
    """从一个或多个 SARIF 里取 ``{(ruleId, 文件:行号)}``。"""
    found: Set[Tuple[str, str]] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for run in payload.get("runs", []):
            for result in run.get("results", []):
                rule = result.get("ruleId") or "?"
                for loc in result.get("locations", []):
                    phys = loc.get("physicalLocation") or {}
                    uri = ((phys.get("artifactLocation") or {}).get("uri")) or "?"
                    line = (phys.get("region") or {}).get("startLine", "?")
                    found.add((rule, f"{uri}:{line}"))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="CodeQL 结果 ↔ 处置台账对账")
    parser.add_argument("sarif", nargs="*", help="SARIF 文件路径(可多个)")
    parser.add_argument("--sarif-dir", help="改为扫描这个目录下的 *.sarif")
    parser.add_argument("--strict", action="store_true", help="有新增时以退出码 1 结束")
    args = parser.parse_args()

    paths = [Path(p) for p in args.sarif]
    if args.sarif_dir:
        paths.extend(sorted(Path(args.sarif_dir).rglob("*.sarif")))
    paths = [p for p in paths if p.is_file()]

    if not paths:
        print("❌ 没有找到任何 SARIF 文件。", file=sys.stderr)
        print("   这里刻意判失败:'找不到就当通过' 的守卫会在产物路径变动那天静默失效。", file=sys.stderr)
        return 2

    recorded, status = load_ledger()
    found = load_sarif(paths)

    unrecorded = sorted(found - recorded)
    stale = sorted(recorded - found)

    print(f"SARIF {len(paths)} 份 · 告警 {len(found)} 条 · 台账 {len(recorded)} 条")
    by_status: Dict[str, int] = {}
    for key in found & recorded:
        by_status[status.get(key, "?")] = by_status.get(status.get(key, "?"), 0) + 1
    if by_status:
        print("  已判定:" + " · ".join(f"{k} {v}" for k, v in sorted(by_status.items())))

    if stale:
        print(f"\n📉 台账里有 {len(stale)} 条在本轮 SARIF 里已经不见了(修掉了、或规则/位置变了):")
        for rule, loc in stale:
            print(f"    [{status.get((rule, loc), '?')}] {rule}  {loc}")
        print(
            "    确认已修掉的,请从 config/codeql_findings_ledger.json 里删除 —— "
            "留着会让台账慢慢变成一份没人信的清单。"
        )

    if unrecorded:
        print(f"\n⚠️  {len(unrecorded)} 条告警不在台账里:")
        for rule, loc in unrecorded:
            print(f"    {rule}  {loc}")
        print(
            "\n  每一条都要回答一句:**为什么它不该被改**?"
            "\n  答得上来 → 连同理由记进 config/codeql_findings_ledger.json;"
            "\n  答不上来 → 那就是该去改代码,而不是记账。"
        )
        return 1 if args.strict else 0

    print("\n✅ 没有台账之外的 CodeQL 告警。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
