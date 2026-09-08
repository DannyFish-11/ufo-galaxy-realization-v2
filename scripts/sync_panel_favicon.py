#!/usr/bin/env python3
"""把面板 index.html 里的图标标签**从 core/brand_icon.py 重新生成**。

为什么要有这个脚本
------------------
图标在两个地方出现:网关 ``GET /favicon.ico`` 直接返回 ``FAVICON_SVG``,面板
``index.html`` 则把它内联成 data URI(壳里以 file:// 打开时没有同源后端可问)。

如果面板那份是手写死的,``core/brand_icon.py`` 改了颜色/形状之后它不会跟着变 ——
后端给一个图标、壳里显示另一个,而且没有任何地方会报错。这个脚本让面板那份
**由定义处生成**,``core/brand_icon.py`` 就是唯一权威。

用法::

    python scripts/sync_panel_favicon.py            # 写回并报告是否有改动
    python scripts/sync_panel_favicon.py --check    # 只检查,不一致就非零退出

改完记得重建面板产物(``cd electron/renderer/panel && npm run build``),
``scripts/check_panel_dist.sh`` 会盯着 dist 与源码是否一致。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.brand_icon import favicon_data_uri  # noqa: E402 —— 必须先把仓库根放进 path

PANEL_INDEX = ROOT / "electron" / "renderer" / "panel" / "index.html"

_LINK_RE = re.compile(r'^[ \t]*<link rel="icon" href="[^"]*" />[ \t]*$', re.MULTILINE)


def expected_tag() -> str:
    return f'    <link rel="icon" href="{favicon_data_uri()}" />'


def sync(path: Path = PANEL_INDEX, *, check_only: bool = False) -> int:
    """返回退出码:0 = 已一致(或已写回);1 = 不一致且 --check;2 = 找不到那一行。"""
    html = path.read_text(encoding="utf-8")
    if not _LINK_RE.search(html):
        print(f'✗ {path} 里找不到 <link rel="icon" …> 那一行 —— 先手工加一行占位再跑本脚本。')
        return 2

    updated = _LINK_RE.sub(lambda _m: expected_tag(), html, count=1)
    if updated == html:
        print(f"✓ 面板图标与 core/brand_icon.py 一致({path.relative_to(ROOT)})")
        return 0
    if check_only:
        print(f"✗ 面板图标与 core/brand_icon.py 不一致({path.relative_to(ROOT)})。跑一次本脚本写回。")
        return 1
    path.write_text(updated, encoding="utf-8")
    print(f"✓ 已按 core/brand_icon.py 重写面板图标({path.relative_to(ROOT)})。别忘了重建 dist。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只检查,不一致就非零退出")
    args = ap.parse_args()
    return sync(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
