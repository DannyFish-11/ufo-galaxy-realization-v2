"""面板不许再长出装饰性的框，也不许再有硬切的出场。

## 这道门为什么存在

``tokens.css`` 开头就把规矩写清楚了：

    面与面之间只差一点点明度，靠顶边一道受光和底下一团柔影分层，
    **不靠给每条边刷白**。

但设置页那一片长起来的时候，每一个小东西都被顺手套了一圈
``inset 0 0 0 1px`` —— 输入框、按钮、药丸、区块、提示条、整个表单。于是不是
"几个实物摆在一个面上"，而是"一格一格的框"。那正是最容易被认出来的那种
"生成出来的界面"：一堆等宽等圆等白的矩形。

同一时期还有两处同源的毛病：
* ``.sf-row:nth-child(even)`` 的斑马纹 —— 把设置页画成了一张表格；
* ``.settings-full`` 用 ``display: none ↔ flex`` 切换 —— **硬切**，一帧之内整页
  盖上来。而岛那边早就做对了（宽高圆角连续过渡、内容交叉淡入）。同一个界面上
  两种出场方式，人会觉得这两块东西不是一个软件里的。

## 分得清"装饰"与"信息"

**不是所有 1px 都要删。** 有几处线是**带信息**的，删了就等于抹掉一个判据：

* 档位牌上那圈警示色 = "这一档你的显卡装不下"
* 那圈虚线 = "这一档**没被评估过**"（与"能跑"是两件事）
* ``.blk[data-unknown]`` 的空心 = "这三天不可知"（与"这三天是空的"是两件事）

所以这道门不数总量，而是钉住**哪些选择器有权带 1px**。要给新东西加边框，
就得先在这份名单里写清楚它带的是什么信息 —— 那一步会让人停下来想一想。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_CSS = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src/styles/hud.css"

#: 有权带 1px 线的选择器 → 它带的是什么信息（或它为什么是画的一部分）。
_RING_IS_ALLOWED_BECAUSE = {
    ".card": "一张能捏起来的实物卡：1px 只是六层里的一层，和顶边受光、内底暗、上下投影一起构成边缘",
    ".card[data-drawn='true']": "同上，抽出的那张离得更远",
    ".card-nfc": "卡面上那枚芯片图案本身就是这么画的，不是给谁镶边",
    ".blk[data-unknown='true']": "空心 = 这几天不可知。「空」与「不知道」必须分得开",
    ".blk[data-unknown='true'][data-drawn='true']": "同上，被抽出的那块",
    ".tier-stages .stage[data-fit='no_gpu']": "警示色的圈 = 这一档你的显卡装不下",
    ".tier-stages .stage[data-fit='insufficient_vram']": "同上",
    ".tier-stages .stage[data-fit='unknown']": "虚线 = 这一档没被评估过，与「能跑」是两件事",
    ".privacy-btn[data-unknown='true']": "虚线 = 问不到后端，停没停不知道。与「正在采」是两件事",
}


def _selectors_with_rings() -> dict[str, str]:
    """扫出「哪个选择器带了 1px 线」。

    做法是从每一条 ring 声明往回找最近的选择器行。够用，因为这份 CSS 是手写的、
    一条规则一个选择器块；真要变复杂了，这道门会先误报，而误报比漏报安全。
    """
    lines = _CSS.read_text(encoding="utf-8").split("\n")
    ring = re.compile(r"inset 0 0 0 1(\.\d+)?px|outline: 1px dashed")
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        if not ring.search(line):
            continue
        for j in range(i, -1, -1):
            stripped = lines[j].strip()
            if stripped.endswith("{") and not stripped.startswith(("@", "/*", "*")):
                out[stripped[:-1].strip().rstrip(",")] = f"hud.css:{i + 1}"
                break
    return out


def test_only_the_lines_that_carry_information_are_allowed_to_be_lines() -> None:
    found = _selectors_with_rings()
    unexpected = {sel: where for sel, where in found.items() if sel not in _RING_IS_ALLOWED_BECAUSE}
    assert not unexpected, (
        f"这些选择器新长出了 1px 边框：{unexpected}。\n"
        "tokens.css 的规矩是「靠顶边受光和柔影分层，不靠给每条边刷白」。"
        "如果这条线**带信息**（像「显存装不下」那圈警示色），"
        "就把它写进本文件的 _RING_IS_ALLOWED_BECAUSE 并说清它表达什么；"
        "如果只是想把一块东西框起来，改用 "
        "`box-shadow: inset 0 1px 0 var(--lite), 0 1px 2px var(--shade-1)`。"
    )


def test_the_settings_page_has_no_table_stripes() -> None:
    """斑马纹是最像表格、也最出戏的一处。"""
    css = _CSS.read_text(encoding="utf-8")
    assert "nth-child(even)" not in css, (
        "设置页又出现了隔行底色。335 行确实长，但把它画成一张表格并不会更好读 —— " "分隔靠的是间距和分组，不是条纹。"
    )


def test_the_settings_page_grows_in_instead_of_cutting_in() -> None:
    """开合必须是连续的，和岛一样。"""
    css = _CSS.read_text(encoding="utf-8")
    block = css.split(".settings-full {", 1)[1].split("}", 1)[0]
    assert "display: none" not in block, (
        ".settings-full 又变回 display:none 切换了 —— 那是硬切，一帧之内整页盖上来。"
        "岛那边是连续过渡的；同一个界面上两种出场方式，人会觉得这两块东西不是一个软件里的。"
    )
    assert "transition:" in block and "transform" in block, ".settings-full 没有过渡 —— 它应当从齿轮那一角长出来"
    assert "transform-origin" in block, "没有定原点，会从中心长出来 —— 人会去找「我刚才点的是哪儿」"


def test_widths_are_not_pinned_by_position() -> None:
    """表单里哪个框宽、哪个窄，要按标记指定，不按位置。

    按 nth-child 指的话，谁把表单重排一下，宽度就悄悄跟错了字段，而且不报错。
    """
    css = _CSS.read_text(encoding="utf-8")
    assert (
        ".up-form .up-row:nth-child(" not in css
    ), "表单的宽窄又按位置指定了 —— 重排一下就会跟错字段。用 .up-wide 这类显式标记。"
