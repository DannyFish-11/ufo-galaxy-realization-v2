"""整面是**一块**,不是几块拼起来的。

## 所有者的原话

"你的这个渐变的色彩，还有这个白色，它们分布不匀" / "左边白色的那个，不需要
非得有一个块块把卡片包起来" / "从卡片本身到最下面的卡片，颜色往下逐渐和面板
融为一体，最后逐渐消失" / "跟这整个面板就是一体的，浑然一体，而不是这种突兀
的插入"。

## 病根在哪儿

``tokens.css`` 开头写着一句规矩：

    白只是**透过来的光**，不是物体本身的颜色。

但真正画出来的面用的是 ``--s-hi / --o-hi`` 那几个**不透明**的浅紫 —— 它们是
在 liminal 那一档底色上调出来的常量。于是：

* 三态色温一换，底色走了、面不走，面就浮在上面像一块贴上去的板；
* 左栏那个"把卡片包起来的白块块"把左栏从整面里切了出来；
* 每块面各带一种紫，谁也不挨着谁，整面就是"分布不匀"。

改法只有一条：**面没有自己的颜色，它只是那块地方的光亮了一点。** 要么是叠在
底色上的一层白纱（veil），要么是拿底色兑白调出来的（color-mix）。

## 这道门钉住四件事

1. 面不许再自带不透明底色（开关把手那一颗除外，理由写在名单里）。
2. 左栏不许再长出包卡片的盒子。
3. 卡片必须**挡得住**后面那张 —— 这是实测栽过的：整张卡半透明时，下面那张的
   日期和柱状图直接透上来，四张卡的字叠在一条 40px 的唇口上。融进底色要靠
   调颜色，不是调透明度。
4. 字号只能从那把尺子上取。散着十一个半像素一档的数字，是"看着就是不齐"最
   便宜的来源。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"
_HUD = _SRC / "styles/hud.css"
_TOKENS = _SRC / "styles/tokens.css"
_MAIN = _SRC / "main.ts"


def _hud() -> str:
    if not _HUD.exists():
        pytest.fail(f"{_HUD} 不在了")
    return _HUD.read_text(encoding="utf-8")


# 允许留实色的地方。**要加一条，先在这儿说清它为什么不能透。**
_OPAQUE_IS_ALLOWED_BECAUSE = {
    ".knob::after": "开关上那颗把手要读成能拨动的一个物件，半透明会变成一片光斑",
    ".card": "只在 @supports 的回落分支里 —— 没有 color-mix 的旧壳宁可难看也要挡得住",
}


def _selectors_painting_opaque_surfaces() -> dict[str, str]:
    """扫出「哪个选择器还在用不透明的面色」。

    往回找最近的选择器行，跟 test_panel_has_no_decorative_boxes 同一个做法：
    这份 CSS 是手写的、一条规则一个选择器块。真变复杂了这道门会先误报，
    而误报比漏报安全。
    """
    lines = _hud().split("\n")
    opaque = re.compile(r"var\(--[so]-(?:hi|lo)\)|var\(--o\)\b|var\(--s\)\b")
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        if "background" not in line and not line.strip().startswith("linear-gradient"):
            continue
        if not opaque.search(line):
            continue
        for j in range(i, -1, -1):
            stripped = lines[j].strip()
            if stripped.endswith("{") and not stripped.startswith(("@", "/*", "*")):
                out[stripped[:-1].strip().rstrip(",")] = f"hud.css:{i + 1}"
                break
    return out


class TestEveryFaceIsLightComingThrough:
    def test_no_new_face_paints_its_own_opaque_colour(self) -> None:
        found = _selectors_painting_opaque_surfaces()
        unexpected = {k: v for k, v in found.items() if k not in _OPAQUE_IS_ALLOWED_BECAUSE}
        assert not unexpected, (
            f"这些面又自带了不透明底色：{unexpected}。\n"
            "tokens.css 的规矩是「白只是透过来的光，不是物体本身的颜色」——"
            "自带一种紫的面在三态色温里不会跟着变，看上去就是贴在上面的一块。\n"
            "改用 var(--veil-*) 叠在底色上，或者 color-mix(in srgb, #fdfbff X%, var(--wash-*))；"
            "确实不能透的，写进本文件的 _OPAQUE_IS_ALLOWED_BECAUSE 并说明为什么。"
        )

    def test_the_veils_are_defined_and_translucent(self) -> None:
        css = _TOKENS.read_text(encoding="utf-8")
        for n in (1, 2, 3, 4):
            m = re.search(rf"--veil-{n}:\s*rgba\([^)]*,\s*([\d.]+)\)", css)
            assert m, f"--veil-{n} 没了 —— 面就没有「一层纱」可用了"
            assert 0 < float(m.group(1)) < 1, f"--veil-{n} 不是半透明的，那它就不是纱"


class TestTheLeftRailHasNoBoxAroundTheCards:
    def test_the_frame_paints_nothing(self) -> None:
        css = _hud()
        m = re.search(r"\n\.frame \{(.*?)\n\}", css, re.S)
        assert m, ".frame 没了"
        body = m.group(1)
        assert "background:" not in body, (
            "左栏又长出了一个包卡片的盒子。卡片本来就是浮在面上的东西，"
            "再套一个盒子等于把同一件事说了两遍，而且把左栏从整面里切了出来"
        )
        assert "box-shadow:" not in body, "同上 —— 投影也会把它描成一块"


class TestACardMustHideTheOneBehindIt:
    def test_the_card_face_has_an_opaque_base(self) -> None:
        """整张卡半透明 = 下面那张的字透上来。实测栽过，钉住。"""
        css = _hud()
        m = re.search(r"\n\.card \{(.*?)\n\}", css, re.S)
        assert m, ".card 没了"
        body = m.group(1)
        assert "color-mix(" in body, (
            "卡面不再是从底色兑出来的实色。只用 rgba 叠纱的话，下面那张卡的日期和"
            "柱状图会直接透上来 —— 四张卡的字叠在一条 40px 的唇口上，谁也读不清。"
            "要融进底色就调它的颜色，不是调它的透明度。"
        )

    def test_the_card_colour_is_mixed_from_the_wash(self) -> None:
        css = _hud()
        m = re.search(r"\n\.card \{(.*?)\n\}", css, re.S)
        body = m.group(1) if m else ""
        assert "var(--wash-" in body, "卡色不是从三态底色里调的 —— 相位一换，卡不跟着换，又变回一块贴上去的板"

    def test_the_stack_fades_downward(self) -> None:
        """越靠下那张越接近底色 —— 所有者要的那句「最后逐渐消失」。"""
        css = _hud()
        assert "--depth" in css, "卡片没有按位置分层，一叠卡会是五块等亮的板子"
        m = re.search(r"--lift:\s*calc\(([\d.]+)%\s*-\s*var\(--depth[^)]*\)\s*\*\s*([\d.]+)%\)", css)
        assert m, "--lift 不再按 --depth 递减 —— 那就没有「往下化开」这件事了"
        top, step = float(m.group(1)), float(m.group(2))
        assert step > 0, "每深一张不变淡，等于没分层"
        # 第 0 张不能亮到把底色压没了:实测 76% 时三态卡面几乎同色,相位推不动它。
        assert top <= 64, (
            f"最上面那张兑了 {top}% 白 —— 白兑得太满，底色只剩一点点，"
            "三态色温推不动它，卡又变回一块白板了（实测 76% 时三态卡面同色）"
        )

    def test_the_drawn_card_is_not_masked_away(self) -> None:
        """抽出来那张的下半截是柱状图，化掉就读不出来了。"""
        css = _hud()
        m = re.search(r"\.card\[data-drawn='true'\] \{([^}]*)", css)
        assert m and "mask-image: none" in m.group(1), "抽出来那张还带着下沿的遮罩 —— 它的柱状图就在下半截，会被化掉"


class TestOneRulerForTypeSizes:
    def test_no_hand_picked_pixel_sizes(self) -> None:
        left = re.findall(r"font-size:\s*[\d.]+px", _hud())
        assert not left, (
            f"又出现了写死的字号：{sorted(set(left))}。\n"
            "从前这份样式里散着十一个（10 / 10.5 / 11 / 11.5 / 12 / 12.5 / 13 / 13.5 /"
            " 14 / 14.5 / 15）—— 半像素一档，谁也说不清哪一档表示什么，同一种东西在"
            "两个地方是两个大小。先想「它跟哪一档是同一种东西」，再从 --t-* 里取。"
        )

    def test_the_ruler_has_six_rungs(self) -> None:
        css = _TOKENS.read_text(encoding="utf-8")
        rungs = re.findall(r"--t-(micro|mini|small|ui|body|lead):\s*([\d.]+)px", css)
        assert len(rungs) == 6, f"尺子上不是六档，是 {len(rungs)} 档：{rungs}"
        vals = [float(v) for _, v in rungs]
        assert vals == sorted(vals), f"六档没有从小到大排：{rungs}"

    def test_body_weight_matches_on_both_scripts(self) -> None:
        """300 的正文在中文那边只能回落到 400 —— 一行里两种粗细。"""
        css = _hud()
        m = re.search(r"\nbody \{(.*?)\n\}", css, re.S)
        assert m, "body 规则没了"
        w = re.search(r"font-weight:\s*(\d+)", m.group(1))
        assert w and int(w.group(1)) >= 400, (
            "正文字重小于 400。中文系统字体基本只有 400/700，写 300 的结果是"
            "Latin 真的细了一档、中文却回落到 400 —— 同一行里两种粗细。"
            "要弱就用颜色弱（--ink-2 / --ink-3）。"
        )

    def test_the_cjk_side_is_size_matched_to_the_latin_side(self) -> None:
        css = _TOKENS.read_text(encoding="utf-8")
        # 找**声明**，不是找注释里那个词。
        #
        # 上一版写的是 ``"size-adjust" in css`` —— 自证的时候把那一行删掉，判据
        # 居然还是绿的：它读到的是上面那段说明里提到的 "size-adjust" 四个字。
        # 一条只要文档里提过就会通过的判据，等于没有判据。
        m = re.search(r"^\s*size-adjust:\s*([\d.]+)%", css, re.M)
        assert m, (
            "中文那半边没有做尺寸对齐。Onest 只覆盖 latin，中文直接掉进系统栈，"
            "同一个 font-size 下中文明显更大更重 —— 一行里两套字各按自己的尺寸画。"
        )
        pct = float(m.group(1))
        assert 85 <= pct <= 100, f"size-adjust 是 {pct}% —— 超出配得上的范围，等于换了一种不协调"


class TestTheLineSitsAtTheBottom:
    def test_the_wired_list_comes_before_the_line(self) -> None:
        """线夹在中间会把左栏从视觉上切成两半 —— 而那两半本来是一件事。"""
        src = _MAIN.read_text(encoding="utf-8")
        m = re.search(r"deck\.root\.append\(([^)]*)\)", src)
        assert m, "左栏底下那两块没挂上去"
        order = m.group(1)
        assert order.index("wired.root") < order.index(
            "line.root"
        ), f"线又跑到清单上面去了（{order.strip()}）—— 它是这一栏的地平线，不是栏里的一道分隔"
