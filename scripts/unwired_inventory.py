#!/usr/bin/env python3
"""scripts/unwired_inventory.py — 「未接线 / 不可达」的代码到底是些什么东西。

``check_wiring.py`` 回答「有没有**新增**的未接线能力」，``check_reachability.py`` 回答「哪些模块
从真实入口走不到」。两者都只给名单。所有者要的是**先弄清楚是什么，再决定删还是接**
（2026-09-28），所以这里把同一批名单按事实分类：

- 形态：类方法 / 模块函数；
- 旁证：只有测试在引用（写了、测了、没接）/ 全仓连测试都没引用；
- 名字表明的角色：动作/变更、事件回调、计算/构造、只读查询、判定谓词、序列化、测试复位钩子；
- 所在子系统；
- 所在模块本身是否可达。

**分类只是按名字与引用关系做的初筛，不是处置结论。** 每一条是删是接，仍要逐条看。

用法
----
  python scripts/unwired_inventory.py                 # 打印摘要
  python scripts/unwired_inventory.py --write         # 刷新 docs/UNWIRED_CODE_INVENTORY.md 的生成段
  python scripts/unwired_inventory.py --json          # 机器可读
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_reachability  # noqa: E402
import check_wiring  # noqa: E402

DOC_PATH = REPO_ROOT / "docs" / "UNWIRED_CODE_INVENTORY.md"
BEGIN = "<!-- BEGIN GENERATED: scripts/unwired_inventory.py --write -->"
END = "<!-- END GENERATED -->"

# 顺序即优先级：先命中的类别生效。
ROLES = (
    ("测试复位钩子", r"^(reset|clear)(_|$)|_for_tests?$|_for_testing$"),
    ("序列化/转换", r"^(to|from|as)_\w+$|_to_(dict|json|payload|record|node_update|platform|contract)$"),
    ("事件回调", r"^on_\w+$|_received$"),
    (
        "判定谓词",
        r"^(is|has|can|should|was|needs|requires|allows|affects|blocks|visits)_\w+$|^retriable$|"
        r"_(enabled|reachable|registered)$|^spoke_anything$",
    ),
    (
        "只读查询",
        r"^(get|list|find|lookup|query|read|retrieve|iter|all|count|snapshot|summary|describe|inspect|current|latest|"
        r"recent|last|"
        r"next|top|nodes|devices|entries|edges|sources|gaps)_|_(snapshot|summary|count|stats|label|description|terms|"
        r"catalog|entries|sources|subsystems|ms|minute|model|artifacts|of|name|handle|timeline_replay|signals|"
        r"assignment|workers|counters)$|^counters$",
    ),
    (
        "计算/构造",
        r"^(build|make|create|compose|derive|compute|classify|evaluate|assess|resolve|select|choose|rank|score|plan|"
        r"map|decide|govern|normalize|decompose|interpret|project|infer|explain|order|filter|suggest|determine|"
        r"estimate|fallback|trust|guard|block|require|think|comprehend|aggregate|handoff|redact|render|print|"
        r"extract|equivalent|generate|device|result|envelope|chat|finalise|finalize)(_|$)",
    ),
    (
        "动作/变更",
        r"^(record|register|unregister|deregister|set|update|apply|mark|attach|detach|bind|ingest|absorb|emit|"
        r"publish|notify|dispatch|execute|run|start|stop|submit|enqueue|dequeue|advance|transition|close|open|"
        r"promote|revoke|grant|enforce|validate|verify|check|assert|ensure|sync|flush|persist|save|load|restore|"
        r"replay|migrate|merge|install|remove|delete|add|push|pop|handle|process|invoke|trigger|cancel|retry|"
        r"coordinate|route|audit|assimilate|seed|download|receive|send|export|import|reload|hot|enable|disable|"
        r"connect|discover|cache|inject|couple|decouple|begin|complete|suppress|recover|resume|reconnect|relay|"
        r"write|expire|evict|sweep|force|release|subscribe|unsubscribe|track|probe|proxy|allocate|autoscale|"
        r"activate|trip|drop|increment|warn|forget|udm|store|unload|parallel|switch|initialize|reinitialize|"
        r"index|generalize|mine|take|wait|associate|auto|negotiate|detect|simulate|refresh|guarded|safe|test|"
        r"child|error)(_|$)",
    ),
)


def role_of(name: str) -> str:
    for label, pattern in ROLES:
        if re.search(pattern, name):
            return label
    return "其他"


def area_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "nodes" and len(parts) > 2:
        return "nodes/" + parts[1] + "/"
    if parts[0] != "core":
        return parts[0] + "/"
    if len(parts) > 2:
        return "core/" + parts[1] + "/"
    stem = parts[1]
    for prefix in (
        "android_",
        "canonical_",
        "attached_runtime_",
        "delegated_",
        "capability_",
        "device_",
        "node_",
        "task_",
        "desktop_",
        "cross_",
        "truth_",
        "runtime_",
        "session_",
        "orchestration",
        "operator_",
        "execution_",
        "ugcp_",
        "v2_",
        "hybrid_",
        "continuation_",
        "flow_",
    ):
        if stem.startswith(prefix):
            return f"core/{prefix}*"
    return "core/（其余单文件）"


def _kind_index(path: str, cache: Dict[str, Dict[int, str]]) -> Dict[int, str]:
    if path not in cache:
        idx: Dict[int, str] = {}
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for b in node.body:
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        idx[b.lineno] = node.name
        cache[path] = idx
    return cache[path]


def _test_referenced(names: List[str]) -> set:
    found: set = set()
    wanted = set(names)
    word = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    for f in (REPO_ROOT / "tests").rglob("*.py"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found.update(wanted.intersection(word.findall(text)))
    return found


def collect() -> Dict[str, object]:
    definitions, def_count = check_wiring.collect_definitions(check_wiring._iter_definition_files())
    referenced = check_wiring.collect_references(check_wiring._iter_reference_files())
    unwired = check_wiring.find_unwired(definitions, referenced, def_count)
    unreachable = check_reachability.compute_unreachable()
    unreachable_paths = {m.replace(".", "/") + ".py" for m in unreachable}

    tested = _test_referenced([n for n, _ in unwired])
    cache: Dict[str, Dict[int, str]] = {}
    rows = []
    for name, where in unwired:
        path, line = where.rsplit(":", 1)
        owner = _kind_index(path, cache).get(int(line), "")
        rows.append(
            {
                "name": name,
                "at": where,
                "path": path,
                "kind": "method" if owner else "function",
                "owner": owner,
                "tested": name in tested,
                "role": role_of(name),
                "area": area_of(path),
                "module_unreachable": path in unreachable_paths,
            }
        )
    modules = []
    for mod in unreachable:
        p = REPO_ROOT / (mod.replace(".", "/") + ".py")
        modules.append({"module": mod, "lines": len(p.read_text(encoding="utf-8").splitlines())})
    return {"rows": rows, "unreachable_modules": modules}


def render(data: Dict[str, object]) -> str:
    rows: List[dict] = data["rows"]  # type: ignore[assignment]
    mods: List[dict] = data["unreachable_modules"]  # type: ignore[assignment]
    out: List[str] = []
    n = len(rows)
    tested = sum(r["tested"] for r in rows)
    methods = sum(r["kind"] == "method" for r in rows)
    out.append(f"未接线公开能力 **{n}** 条，分布在 **{len({r['path'] for r in rows})}** 个文件。")
    out.append("")
    out.append("| 维度 | 数 |")
    out.append("|---|---|")
    out.append(f"| 类方法 / 模块函数 | {methods} / {n - methods} |")
    out.append(f"| 只有测试在引用（写了、测了、没接） | {tested} |")
    out.append(f"| 全仓连测试都没引用 | {n - tested} |")
    out.append(f"| 所在模块本身从入口不可达 | {sum(r['module_unreachable'] for r in rows)} |")
    out.append("")
    out.append("### 按名字表明的角色")
    out.append("")
    out.append("| 角色 | 合计 | 其中只有测试引用 | 其中连测试都没有 |")
    out.append("|---|---|---|---|")
    by_role: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)
    order = [label for label, _ in ROLES] + ["其他"]
    for label in order:
        lst = by_role.get(label, [])
        if lst:
            t = sum(x["tested"] for x in lst)
            out.append(f"| {label} | {len(lst)} | {t} | {len(lst) - t} |")
    out.append("")
    out.append("### 按子系统")
    out.append("")
    out.append("| 子系统 | 条数 | 文件数 |")
    out.append("|---|---|---|")
    by_area: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_area[r["area"]].append(r)
    for area, lst in sorted(by_area.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append(f"| `{area}` | {len(lst)} | {len({x['path'] for x in lst})} |")
    out.append("")
    out.append("### 从真实入口不可达的模块")
    out.append("")
    out.append("| 模块 | 行数 |")
    out.append("|---|---|")
    for m in mods:
        out.append(f"| `{m['module']}` | {m['lines']} |")
    out.append("")
    out.append("### 逐文件清单")
    out.append("")
    out.append("标记：`M` 类方法（后跟所属类）、`F` 模块函数；`T` 只有测试在引用；`—` 连测试都没有。")
    out.append("")
    by_file: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_file[r["path"]].append(r)
    for area, lst in sorted(by_area.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        files = sorted({x["path"] for x in lst})
        out.append(f"<details><summary><code>{area}</code> — {len(lst)} 条</summary>")
        out.append("")
        for path in files:
            items = sorted(by_file[path], key=lambda x: int(x["at"].rsplit(":", 1)[1]))
            cells = []
            for x in items:
                kind = f"M {x['owner']}." if x["kind"] == "method" else "F "
                cells.append(f"`{kind}{x['name']}` {'T' if x['tested'] else '—'} · {x['role']}")
            out.append(f"- `{path}`（{len(items)}）：" + "；".join(cells))
        out.append("")
        out.append("</details>")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help=f"刷新 {DOC_PATH.relative_to(REPO_ROOT)} 的生成段")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()
    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    body = render(data)
    if args.write:
        doc = DOC_PATH.read_text(encoding="utf-8")
        if BEGIN not in doc or END not in doc:
            print(f"{DOC_PATH} 里找不到生成段标记", file=sys.stderr)
            return 1
        head, rest = doc.split(BEGIN, 1)
        _old, tail = rest.split(END, 1)
        DOC_PATH.write_text(head + BEGIN + "\n\n" + body + "\n" + END + tail, encoding="utf-8")
        print(f"已刷新 {DOC_PATH.relative_to(REPO_ROOT)}")
        return 0
    rows = data["rows"]  # type: ignore[index]
    print(f"未接线 {len(rows)} 条；角色分布：", Counter(r["role"] for r in rows).most_common())  # type: ignore[union-attr]
    print("不可达模块：", [m["module"] for m in data["unreachable_modules"]])  # type: ignore[index]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
