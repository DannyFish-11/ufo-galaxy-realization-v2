"""灵动岛是又薄又长的一条（Windows 灵动岛那种），不是一块墩子。

所有者两次要的都是「瘦长」。第一次我把它改成「更窄更高」（248×33 → 216×40，比例从 7.5:1
掉到 5.4:1）—— 方向反了。这里把比例钉住：展开后的整体高度（含顶上那 2px）不超过 32，
长宽比不低于 8:1。尺寸常量在 ``electron/renderer/app.js`` 的 ``ISLE_*``，一处可调；要改比例就改
这里的数，并在 ``docs/SYSTEM_STATUS.md`` 里说明为什么。
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = (Path(__file__).resolve().parent.parent / "electron" / "renderer" / "app.js").read_text(encoding="utf-8")


def _const(name: str) -> int:
    m = re.search(rf"^const {name} = (\d+);", APP_JS, re.MULTILINE)
    assert m, f"app.js 里找不到 {name}"
    return int(m.group(1))


def test_the_island_is_a_thin_pill_not_a_block():
    width, height = _const("ISLE_MIN_W"), 2 + _const("ISLE_H")
    assert height <= 32, f"岛展开后高 {height}px —— 太厚了，不是瘦长"
    assert width / height >= 8, f"岛 {width}×{height}（{width / height:.1f}:1）—— 不够长，要 ≥ 8:1"


def test_the_lower_corners_round_the_end_into_a_pill():
    """下沿圆角至少是高度的一半 —— 小于它，两头就是方的，成了一条带而不是药丸。"""
    height, radius = 2 + _const("ISLE_H"), 2 + _const("ISLE_R")
    assert radius >= height / 2, f"圆角 {radius}px 小于高度一半 {height / 2}px，两头不圆"
