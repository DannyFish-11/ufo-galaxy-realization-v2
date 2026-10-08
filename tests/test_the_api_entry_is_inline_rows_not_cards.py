"""面板上填 API 的那些（模型服务商、我的模型服务）是内嵌的行，不是一摞凸起的卡片。

所有者要的是「与面板一致的样式，内嵌的那种，融为一整体」。原先每家厂商 / 每条端点一块小卡
（渐变底 + 内高光 + 投影），叠在「全部设置」那一页上像从别处贴过来的 —— 那一页上别的项全是
平铺的行（``.sf-row``：左边一句话、右边一个控件）。

这里钉三件事，免得有人又把卡片画回来：

1. ``.up-card`` 没有底、没有影（只在悬停 / 正在填的那一行淡淡亮一下）；
2. 厂商那一行是两栏：``.vd-text``（是谁、通没通、能做什么）+ ``.vd-ctl``（填的地方），
   窄栏按**容器宽度**塌成一列（设置页是个浮层，窗口宽不代表这一栏宽）；
3. ``vendors.ts`` 真的按这两栏建 DOM（样式写了、结构没跟上，等于没改）。
"""

from __future__ import annotations

import re
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "electron" / "renderer" / "panel"
CSS = (PANEL / "src" / "styles" / "hud.css").read_text(encoding="utf-8")
VENDORS = (PANEL / "src" / "ui" / "vendors.ts").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """取 ``selector { … }`` 这一条的花括号里的内容（只认顶层、选择器独占一条的那种）。"""
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"hud.css 里找不到 {selector} 这一条"
    return m.group(1)


def test_a_card_has_no_raised_box_any_more():
    body = _rule(".up-card")
    assert re.search(r"background:\s*transparent", body), ".up-card 又有底色了 —— 那是卡片，不是内嵌的行"
    assert re.search(r"box-shadow:\s*none", body), ".up-card 又有投影了 —— 那是卡片，不是内嵌的行"
    assert "gradient" not in body, ".up-card 又画渐变底了"


def test_a_vendor_is_one_row_with_two_columns():
    body = _rule(".vd-card")
    assert "display: grid" in body
    assert re.search(
        r"grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto", body
    ), "厂商这一行不是「左边说明、右边控件」两栏"
    assert ".vd-text" in CSS and ".vd-ctl" in CSS


def test_a_narrow_column_collapses_by_container_width_not_window_width():
    m = re.search(r"@container \(max-width:\s*\d+px\)\s*\{([^@]*?)\n\}", CSS)
    assert m, "没有按容器宽度塌成一列的规则"
    assert ".vd-card" in m.group(1) and "grid-template-columns: minmax(0, 1fr)" in m.group(1)


def test_the_markup_is_built_as_the_two_columns_the_css_expects():
    assert "vd-text" in VENDORS and "vd-ctl" in VENDORS
    assert "el.append(text, ctl, detail)" in VENDORS, "厂商卡片没按 左栏 / 右栏 / 详情 三块组装"
