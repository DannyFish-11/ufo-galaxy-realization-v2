#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/check_agent_supply_declaration.py — 守卫 G13：Agent 声明的是需求，不是供应商。

``AgentConfig`` 的三格供给声明（``model_preference`` / ``modality_required`` /
``locus_constraint``）取值域都是枚举（见 :mod:`core.agent_supply`）。一旦某处写成
``model_preference="deepseek"`` 或 ``locus_constraint="qwen2.5:7b"``，Agent 就在点名供应商 ——
``core/model_role_policy.py`` 的「OpenClawd 是模型选择的唯一权威」当场作废。

扫两处：

* Python 源码（core/ · galaxy_gateway/ · launcher/ · nodes/）里任何以这三格为关键字的调用：
  取值必须是字面量且在枚举内。非字面量只允许出现在 ``core/agent_supply.py``（清洗入口本身）。
* config/ 下 JSON 里以这三格为键的取值。

纯 AST / JSON 静态分析，不导入任何业务模块。

用法::

    python scripts/check_agent_supply_declaration.py          # 有违例退出 1
    python scripts/check_agent_supply_declaration.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Iterator, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.agent_supply import LOCUS_CONSTRAINTS, MODALITIES, MODEL_PREFERENCES  # noqa: E402

SCAN_DIRS = ("core", "galaxy_gateway", "launcher", "nodes")
FIELDS = ("model_preference", "modality_required", "locus_constraint")
SANITIZER = "core/agent_supply.py"


def _allowed(field: str, value: Any) -> bool:
    if field == "model_preference":
        return value in MODEL_PREFERENCES
    if field == "locus_constraint":
        return value in LOCUS_CONSTRAINTS
    return isinstance(value, (list, tuple)) and all(m in MODALITIES for m in value)


def _python_files() -> Iterator[Path]:
    for top in SCAN_DIRS:
        root = REPO_ROOT / top
        if root.is_dir():
            yield from (p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def scan_python() -> List[Tuple[str, str]]:
    violations: List[Tuple[str, str]] = []
    for path in _python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        if not any(f in source for f in FIELDS):
            continue
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg not in FIELDS:
                    continue
                try:
                    value = ast.literal_eval(kw.value)
                except ValueError:
                    if rel != SANITIZER:
                        violations.append((f"{rel}:{node.lineno}", f"{kw.arg} 必须是字面量枚举值（否则守卫核不了）"))
                    continue
                if not _allowed(kw.arg, value):
                    violations.append(
                        (f"{rel}:{node.lineno}", f"{kw.arg}={value!r} 不在枚举内 —— 声明需求，不点名供应商")
                    )
    return violations


def _walk_json(node: Any, trail: str) -> Iterator[Tuple[str, str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FIELDS:
                yield trail + "." + key, key, value
            yield from _walk_json(value, f"{trail}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_json(value, f"{trail}[{i}]")


def scan_config() -> List[Tuple[str, str]]:
    violations: List[Tuple[str, str]] = []
    for path in sorted((REPO_ROOT / "config").rglob("*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for where, field, value in _walk_json(data, rel):
            if not _allowed(field, value):
                violations.append((where, f"{field}={value!r} 不在枚举内 —— 声明需求，不点名供应商"))
    return violations


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G13：Agent 供给声明只能是需求枚举")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    violations = scan_python() + scan_config()
    if args.json:
        print(json.dumps([{"where": w, "detail": d} for w, d in violations], ensure_ascii=False, indent=2))
    elif violations:
        print(f"❌ G13：{len(violations)} 处 Agent 供给声明越出枚举：\n")
        for where, detail in violations:
            print(f"  {where}  {detail}")
    else:
        print("✅ G13：所有 Agent 供给声明都是需求枚举，没有点名供应商。")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
