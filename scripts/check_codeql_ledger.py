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

行号漂移怎么处理(这一段是被真实情况改过一次的)
----------------------------------------------
第一版把位置严格比到 ``文件:行号``,理由是"只比文件名会让同一个文件里新增一处
完全隐形"。这个理由本身没错,但代价被低估了:**在这套守卫落地的同一个 PR 里,
两条记录的行号就漂了** —— 只因为我在 bind 上面加了两行注释。一份每次改动都要
手工对行号的台账,很快就没人维护,而那正是它要防的结局。

现在按 ``(规则, 文件)`` 分组比**条数**:

  * 同组内行号能对上的 → 匹配;
  * 对不上、但该组在 SARIF 里的条数**没有超过**台账里记的条数 → 判为**位置漂移**,
    提示更新行号,不算新增;
  * 条数**超了** → 超出的部分是**新增**,照报不误。

所以"同一个文件里多出一处"仍然抓得到(条数变了),而"整体位移"不再制造噪声。
按条数而不是按行号判定,是这两个需求唯一能同时满足的方式。
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


def _group(pairs) -> Dict[Tuple[str, str], List[str]]:
    """按 ``(规则, 文件)`` 归组,值是该组下的行号列表。"""
    out: Dict[Tuple[str, str], List[str]] = {}
    for rule, loc in pairs:
        uri, line = loc.rsplit(":", 1)
        out.setdefault((rule, uri), []).append(line)
    return out


def reconcile(recorded: Set[Tuple[str, str]], found: Set[Tuple[str, str]]):
    """对账,返回 ``(新增, 位置漂移, 已消失)`` 三份清单。

    判定按 ``(规则, 文件)`` 分组比**条数**,而不是逐条比行号 —— 理由见模块 docstring:
    行号会随无关改动漂移,而"同一个文件里多出一处"必须仍然抓得到。条数是唯一能
    同时满足这两点的判据。
    """
    rec_groups = _group(recorded)
    found_groups = _group(found)

    new: List[Tuple[str, str]] = []
    drifted: List[Tuple[str, str, str]] = []  # (rule, file, "旧行 → 新行")
    gone: List[Tuple[str, str]] = []

    for key, found_lines in found_groups.items():
        rule, uri = key
        rec_lines = rec_groups.get(key, [])
        matched = set(found_lines) & set(rec_lines)
        unmatched_found = sorted(set(found_lines) - matched, key=int)
        unmatched_rec = sorted(set(rec_lines) - matched, key=int)

        # 能一一对上的当作漂移;多出来的才是新增。
        for i, line in enumerate(unmatched_found):
            if i < len(unmatched_rec):
                drifted.append((rule, uri, f"{unmatched_rec[i]} → {line}"))
            else:
                new.append((rule, f"{uri}:{line}"))

    for key, rec_lines in rec_groups.items():
        rule, uri = key
        found_lines = found_groups.get(key, [])
        # 这一组在 SARIF 里少了几条,少的那几条算"已消失"(漂移已经在上面配对掉了)。
        missing = len(set(rec_lines)) - len(set(found_lines))
        if missing > 0:
            for line in sorted(set(rec_lines) - set(found_lines), key=int)[:missing]:
                gone.append((rule, f"{uri}:{line}"))

    return sorted(new), sorted(drifted), sorted(gone)


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

    unrecorded, drifted, stale = reconcile(recorded, found)

    print(f"SARIF {len(paths)} 份 · 告警 {len(found)} 条 · 台账 {len(recorded)} 条")
    by_status: Dict[str, int] = {}
    for key in found & recorded:
        by_status[status.get(key, "?")] = by_status.get(status.get(key, "?"), 0) + 1
    if by_status:
        print("  已判定:" + " · ".join(f"{k} {v}" for k, v in sorted(by_status.items())))

    if drifted:
        print(f"\n📍 {len(drifted)} 条位置漂移(同一规则、同一文件,条数没变,只是行号动了):")
        for rule, uri, move in drifted:
            print(f"    {rule}  {uri}  {move}")
        print("    改一下 config/codeql_findings_ledger.json 里的行号即可,不是新问题。")

    if stale:
        print(f"\n📉 台账里有 {len(stale)} 条在本轮 SARIF 里已经不见了(修掉了、或规则变了):")
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
