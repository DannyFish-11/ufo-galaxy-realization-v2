#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/check_reachability.py — core/ 模块是否还能从真实入口到达。

为什么需要这个工具
==================
「这个模块还有人用吗」这个问题，本仓已经被反复手工回答过很多次，每次都用一个临时
脚本，每次都以不同的方式答错。仅在最近一次排查里，同一份清单就先后产生了 **五类**
误报，每修掉一类就冒出新的一类：

===================================  =========================================
误报来源                              后果（如果照单删）
===================================  =========================================
包 ``__init__`` 可达性未建模          ``core.runtime`` 等 10+ 个包入口被判死；
                                     其中 core.runtime 有 37 个文件在用
CI 按**文件路径**调用                 ``python core/release_blocking_gate.py``
                                     这类阻塞门被判死（8 个）
入口集漏了 ``nodes/*/server.py``      5 个节点服务的引擎被判死
shim 再导出                          真实模块躲在 shim 后面，按 shim 路径搜不到
workflow 跑硬编码测试路径             模块删了、测试跟着删，pytest 直接 exit 4
===================================  =========================================

结论不是「下次查仔细点」，而是：**这个判断必须固化成带基线的工具**，把已知盲区
编码进来并反向验证，而不是每次重新手搓。

判据
====
可达 = 从真实入口出发，沿真实引用边能走到。**「有人 import」不等于「活着」** ——
死代码簇会互相引用，按引用计数永远删不掉。

真实入口包括：顶层启动器、网关 app、OpenClawd、API 路由，以及 ``nodes/``、
``windows_client/``、``scripts/``、``audit/`` 等部署侧目录下的全部模块。
**测试不是入口** —— 仅测试引用正是本工具要找的东西。

引用边覆盖六种形式：``import X`` / ``from X import Y`` / 相对导入 /
``from 包 import 子模块`` / ``importlib.import_module("字符串")`` / 以及
**祖先包**（导入子模块会执行父包 ``__init__``）。

CI 侧的三类非 import 用法单独识别：workflow 里出现模块路径或点号名、workflow 跑
的测试文件所导入的模块、shim 再导出链。

用法
====
    python scripts/check_reachability.py                 # 只报**新增**的不可达（门）
    python scripts/check_reachability.py --list          # 列出当前全部不可达
    python scripts/check_reachability.py --update-baseline
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "config" / "reachability_baseline.json"

SKIP_DIRS = {".git", "__pycache__", "external", "node_modules", "chroma_db", ".venv", "venv", "build", "dist"}

# 部署侧目录：其中的模块本身就是入口（节点服务、桌面客户端、运维脚本、审计工具）。
ENTRY_ROOTS = (
    "nodes.",
    "windows_client.",
    "scripts.",
    "audit.",
    "fusion.",
    "enhancements.",
    "desktop_projection.",
    "launcher.",
    "tools.",
    "integrations.",
    "system_integration.",
    "mcp_bridge.",
    "daemon.",
    "windows_service.",
    "installer.",
    "deployment.",
)
ENTRY_MODULES = (
    "main",
    "unified_launcher",
    "system_manager",
    "launch_desktop",
    "galaxy_gateway.app",
    "core.openclawd",
    "core.api_routes",
)


def _module_name(path: Path) -> str:
    m = ".".join(path.with_suffix("").parts)
    return m[: -len(".__init__")] if m.endswith(".__init__") else m


def _iter_py() -> List[Path]:
    return [p for p in REPO_ROOT.rglob("*.py") if not any(s in p.parts for s in SKIP_DIRS)]


def _build_graph(files: List[Path]) -> Tuple[Dict[str, Path], Dict[str, Set[str]]]:
    rel = {p: p.relative_to(REPO_ROOT) for p in files}
    allmods = {_module_name(rel[p]): p for p in files}
    edges: Dict[str, Set[str]] = collections.defaultdict(set)

    def add(src: str, target: str) -> None:
        if target in allmods:
            edges[src].add(target)
        # 祖先包：导入子模块会执行父包 __init__，父包因此也是活的。
        parts = target.split(".")
        for i in range(1, len(parts)):
            anc = ".".join(parts[:i])
            if anc in allmods:
                edges[src].add(anc)

    for p in files:
        src_mod = _module_name(rel[p])
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        pkg = ".".join(rel[p].parts[:-1])
        for node in ast.walk(tree):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    q = pkg.split(".")
                    base = ".".join(q[: len(q) - node.level + 1] + ([node.module] if node.module else []))
                # `from 包 import 子模块` —— 子模块也是一条边，不能只记 base。
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names = [node.args[0].value]
            for nm in names:
                add(src_mod, nm)
    return allmods, edges


def _ci_referenced(allmods: Dict[str, Path]) -> Set[str]:
    """CI 侧以非 import 形式用到的模块。

    三类：workflow 里直接出现模块路径 / 点号名；workflow 跑的测试文件所导入的
    模块（含经 shim 转一手的）；`python core/x.py` 这类按文件路径调用。
    """
    referenced: Set[str] = set()
    wf_dir = REPO_ROOT / ".github" / "workflows"
    blobs: List[str] = []
    if wf_dir.is_dir():
        blobs = [f.read_text(encoding="utf-8", errors="replace") for f in wf_dir.rglob("*.y*ml")]
    joined = "\n".join(blobs)

    for mod, path in allmods.items():
        rel = str(path.relative_to(REPO_ROOT))
        if rel in joined or mod in joined:
            referenced.add(mod)

    # workflow 里点名要跑的测试 → 该测试导入的模块也算被 CI 用到。
    for test_rel in set(re.findall(r"tests/[\w/]+\.py", joined)):
        tp = REPO_ROOT / test_rel
        if not tp.is_file():
            continue
        try:
            tree = ast.parse(tp.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for nm in names:
                if nm in allmods:
                    referenced.add(nm)
    return referenced


def _shim_targets(allmods: Dict[str, Path], reached: Set[str], edges: Dict[str, Set[str]]) -> Set[str]:
    """shim 再导出：活着的 shim 指向的真实模块也活着（`from X import *`）。"""
    extra: Set[str] = set()
    for mod in reached:
        for tgt in edges.get(mod, ()):
            if tgt not in reached:
                extra.add(tgt)
    return extra


def compute_unreachable() -> List[str]:
    files = _iter_py()
    allmods, edges = _build_graph(files)

    entries = [m for m in ENTRY_MODULES if m in allmods]
    entries += [m for m in allmods if m.startswith(ENTRY_ROOTS)]
    entries += sorted(_ci_referenced(allmods))

    reached: Set[str] = set()
    stack = list(entries)
    while stack:
        cur = stack.pop()
        if cur in reached:
            continue
        reached.add(cur)
        stack.extend(edges.get(cur, ()))

    # shim 转一手的目标补进来，再走一轮闭包。
    for extra in _shim_targets(allmods, reached, edges):
        stack.append(extra)
    while stack:
        cur = stack.pop()
        if cur in reached:
            continue
        reached.add(cur)
        stack.extend(edges.get(cur, ()))

    return sorted(m for m in allmods if m.startswith("core.") and m not in reached)


def _load_baseline() -> List[str]:
    if not BASELINE_PATH.exists():
        return []
    try:
        return list(json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("unreachable", []))
    except json.JSONDecodeError:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="列出当前全部不可达模块")
    ap.add_argument("--update-baseline", action="store_true", help="把当前结果写入基线")
    args = ap.parse_args()

    unreachable = compute_unreachable()

    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps({"unreachable": unreachable}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"✅ 基线已写入 {BASELINE_PATH.relative_to(REPO_ROOT)}（{len(unreachable)} 个模块）")
        return 0

    if args.list:
        print(f"从真实入口不可达的 core/ 模块：{len(unreachable)} 个\n")
        for m in unreachable:
            path = REPO_ROOT / (m.replace(".", "/") + ".py")
            if not path.exists():
                path = REPO_ROOT / (m.replace(".", "/") + "/__init__.py")
            n = len(path.read_text(encoding="utf-8", errors="replace").splitlines()) if path.exists() else 0
            print(f"  {n:>5}  {m}")
        return 0

    baseline = set(_load_baseline())
    new = [m for m in unreachable if m not in baseline]
    gone = [m for m in baseline if m not in unreachable]

    if gone:
        print(f"ℹ️  基线里有 {len(gone)} 个模块已不再不可达（被接上或被删除）——可以用 --update-baseline 收紧基线。")

    if new:
        print(f"\n❌ 新增 {len(new)} 个从真实入口不可达的 core/ 模块：\n")
        for m in new:
            print(f"  {m}")
        print(
            "\n  新写的模块没有任何真实入口能走到它 —— 它不报错、不变慢、不让测试变红，"
            "\n  只是永远不生效。要么接进真实调用路径，要么先别合进主干。"
            "\n  确属有意（例如端侧沙盒、被 CI 按路径调用）时，用 --update-baseline 记账并在 PR 里说明。\n"
        )
        return 1

    print(f"✅ 没有新增的不可达模块（存量 {len(baseline)} 个已记入基线）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
