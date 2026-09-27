#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/check_meta_layer.py — 元层的静态守卫门：G5 / G6 / G10。

* G6  可写面表与验证器表不相交（算子不得改判卷标准）；Model-RSI 阶段一可写面为空
* G5  算子作用域与可写面表一一对应
* G10 热路径模块不 import core.meta，模块级导入闭包里也没有

判据见 :mod:`core.meta.guards`。纯 AST 静态分析，不 import 任何业务模块，无需装依赖。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.meta.guards import HOT_PATH_MODULES, check_meta_layer  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    violations = check_meta_layer()
    if args.json:
        print(json.dumps([v.to_dict() for v in violations], ensure_ascii=False, indent=2))
    elif violations:
        print(f"❌ 元层守卫：{len(violations)} 处违规")
        for v in violations:
            print(f"  [{v.guard}] {v.path}  {v.detail}")
    else:
        print(f"✅ 元层守卫通过：可写面与验证器不相交；{len(HOT_PATH_MODULES)} 个热路径模块都不加载元层。")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
