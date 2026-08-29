#!/usr/bin/env python3
"""判据保鲜门 —— 对仓库自身状态的结论,所依据的事实变了没有。

它守的是什么
------------
本仓已有的门都在查**代码**:接线了没有、可达吗、有没有超预算、清单漂了没有。
没有任何一道在查**结论** —— 而 2026-08-28 那次全仓评估发现,结论烂得比代码快:

* ``audit/completion_matrix.json`` 的分数停在 2026-04-29,四个月没重推过;
  它自己的证据校验一直是绿的,因为那道门查的是**文件在不在**,35 条路径一条不缺。
* ``FOLLOWUP_IMPLEMENTATION_ROADMAP.md`` 把 ``task_cancel`` 列为唯一的 P0
  correctness failure,而它早就实现了。
* ``runtime_closure_audit`` 的 in-code 缺口清单仍列 GAP-512-004 为开着,
  而 harness 明写已关闭、``device_pool_manager`` 有真调用。
* 那七个"阻塞中的设计问题"里有四个已经不成立。

**同一个缺陷四处独立复现。** 而且每一处都带着绿灯 —— 判据以判据的形式被钉住之后,
比没有它更难被质疑。

它不做什么
----------
**不重算分数。** 那做不到:完成度矩阵原本的方法是人工 code-path tracing,
"这个域 65% 还是 80%"没有机械办法能算。硬做就是臆造。

它只回答一个能机械回答的问题:**这条结论当初依据的那些事实,现在还是那样吗。**
推导仍然由人做;这道门只保证结论不会无声地烂在那儿。

用法
----
::

    python3 scripts/check_assessment_freshness.py            # 复验,过期即非零退出
    python3 scripts/check_assessment_freshness.py --json     # 机器可读
    python3 scripts/check_assessment_freshness.py --list     # 只列清单,不复验

结论清单在 ``config/assessment_claims.json``,人写人改。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.assessment_freshness import freshness_report, load_claims  # noqa: E402


def _render(report: dict) -> str:
    lines = ["config/assessment_claims.json 结论复验", ""]
    loaded = report["claims_loaded"]
    lines.append(f"  结论数 : {loaded}")
    counts = report["verdicts"]
    lines.append(f"  新鲜   : {counts['fresh']}")
    lines.append(f"  已过期 : {counts['stale']}")
    lines.append(f"  问不出 : {counts['unverifiable']}")
    lines.append("")

    if loaded == 0:
        lines.append("⚠️  一条结论都没加载上 —— 这不是「全都新鲜」,是这道门什么都没查。")
        return "\n".join(lines)

    for item in report["results"]:
        if item["verdict"] == "fresh":
            continue
        mark = "❌" if item["verdict"] == "stale" else "⚠️ "
        lines.append(f"{mark} [{item['claim_id']}] {item['statement']}")
        lines.append(f"     出处: {item['source']}  (记于 {item['recorded_on']})")
        for pred in item["predicates"]:
            if pred["verdict"] == "fresh":
                continue
            lines.append(
                f"     · {pred['kind']}({pred['target']} @ {pred['scope'] or '/'}) "
                f"记录={pred['expected']} 实际={pred['actual']} — {pred['detail']}"
            )
        lines.append("")

    if counts["stale"]:
        lines.append("过期的意思是:**这条结论所依据的事实变了,必须重新推导** —— 不是说结论一定错。")
        lines.append("推完之后:改 config/assessment_claims.json 里的 expected 与 recorded_on,")
        lines.append("**并且去改 source 指的那份文档**。只改清单不改文档,等于把过期挪了个地方。")
    elif counts["unverifiable"]:
        lines.append("「问不出」与「过期」是两回事:前者是谓词答不上来(目录没了/搜不动),")
        lines.append("不能被读成「一批结论过期了」—— 那样一次环境故障就会让人不再信这道门。")
    else:
        lines.append("✅ 每条结论所依据的事实都还成立。")

    known_stale = [c for c in load_claims() if str(c.get("supersedes", "")).strip()]
    if known_stale:
        lines.append("")
        lines.append(f"另有 {len(known_stale)} 条结论标注了「有文档仍然说反话」—— 那需要人去改文档,这道门看不住:")
        for c in known_stale:
            lines.append(f"  · {c['id']}: {c['supersedes']}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--list", action="store_true", help="只列清单,不复验")
    args = parser.parse_args()

    if args.list:
        for claim in load_claims():
            print(f"{claim.get('id','?'):44s} {claim.get('statement','')[:80]}")
        return 0

    if args.json:
        print(json.dumps(freshness_report(), ensure_ascii=False, indent=2))
        return 1 if freshness_report()["verdicts"]["stale"] else 0

    report = freshness_report()
    print(_render(report))

    if report["claims_loaded"] == 0:
        # 清单读不出来时**必须**非零 —— 一道什么都没查的门报绿,是这套东西最坏的失效方式。
        return 2
    return 1 if report["verdicts"]["stale"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
