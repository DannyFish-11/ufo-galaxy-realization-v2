"""面板上那张「接上了什么」清单,必须说得出「不知道」。

## 这道门为什么存在

这一整轮真机排查里反复出现的缺陷只有一个形状:**看起来接上了,其实没有。**
托盘说「右下角常驻」而图标根本没出现;探测超时被画成「未安装」;档位说 C 档
而目录压根没拉到。每一次的修法都一样 —— 把「到底接没接上」摆到明面上。

左栏底下那张清单是这件事的常驻形态。它要能成立,靠的不是"列了几行",而是
下面这几条:任何一条塌掉,这张清单就从"说真话的地方"变成"又一个看起来没问题
的地方",而且没人看得见它塌了。

## 钉住的是什么

1. **四态,不是布尔。** 通 / 降级 / 不通 / **不知道**。后端没拉到(`null`)与
   后端说"一个都没有"(空数组)是两件事;画成同一个样子,就是把"不知道"说成
   了"没有"。
2. **不知道要长得不一样。** 空心,不是"暗一点的实心" —— 暗一点只会被当成
   "不通",而"不通"是一个**问过了**的结论。
3. **缺的那条也得列出来。** 容器运行时现在没有面板能问的接口。省掉它,这张
   清单看起来就是完整的,而它不是。
4. **开机就得去问。** 端点列表只在打开设置时才拉的话,这一行会一直写着
   「端点列表没拉到」,而后端好好的 —— 那正好是这张清单要治的毛病本身。
5. **喂入口那块没接上的格子不许能点。** 写着"点了不会有反应"却还能点,
   等于把这句话又变成一句空话。
6. **一相里不止一支色相。** 所有者纠正过:"不是单一的某种色温在混合,这种才是
   莫兰迪色系"。一根轴变冷暖不成系 —— 见本文件最后那三条。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"
_WIRED = _ROOT / "ui/wired.ts"
_DOCK = _ROOT / "ui/dock.ts"
_MAIN = _ROOT / "main.ts"
_HUD = _ROOT / "styles/hud.css"
_TOKENS = _ROOT / "styles/tokens.css"


def _reduced_motion_block(css: str) -> str:
    """取出 prefers-reduced-motion 那一整块（按花括号配对，不靠第一个 `}`）。"""
    start = css.index("@media (prefers-reduced-motion: reduce)")
    depth = 0
    for j in range(css.index("{", start), len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[start : j + 1]
    raise AssertionError("prefers-reduced-motion 块没闭合")


def _oklch(hex_colour: str) -> tuple:
    """sRGB 十六进制 → OKLCH 的 (L, C, H)。

    **要验"邻近"就得真的算色相**,靠眼看分不出 76 度和 280 度里哪一段是哪一段,
    而正是那个跨度决定了整面是一条带还是几块颜色。
    """
    r, g, b = (int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    big_l = 0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc
    a = 1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc
    bb = 0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc
    return big_l, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _read(p: Path) -> str:
    if not p.exists():
        pytest.fail(f"{p} 不在了 —— 这张清单没了,判据也就没有对象")
    return p.read_text(encoding="utf-8")


class TestTheListCanSayItDoesNotKnow:
    def test_the_state_is_four_valued_not_a_boolean(self) -> None:
        src = _read(_WIRED)
        m = re.search(r"export type WiredState\s*=\s*([^;]+);", src)
        assert m, "WiredState 不见了 —— 这张清单的状态空间是这道门的对象"
        states = set(re.findall(r"'([a-z]+)'", m.group(1)))
        assert states == {"on", "part", "off", "unknown"}, (
            f"状态空间变成了 {sorted(states)}。少了 unknown,「没问到」就会被画成"
            f"「问过了,没有」—— 这正是要治的那类缺陷"
        )

    def test_a_missing_catalog_is_unknown_not_off(self) -> None:
        """后端没给目录 → 不知道。不许直接说"还没选定档位"。"""
        src = _read(_WIRED)
        block = src[src.index("input.tiers === null") :][:400]
        assert "'unknown'" in block, "档位目录没拉到时没有报 unknown —— 「拉不到」被说成了一个结论"

    def test_unverified_endpoints_do_not_count_as_wired(self) -> None:
        """没验过的端点不算通。`live` 才算。"""
        src = _read(_WIRED)
        assert "p.state === 'live'" in src, "端点这一行不是按 live 筛的 —— 填了地址没验过也会被算成「通」"

    def test_the_gap_we_cannot_ask_about_is_still_listed(self) -> None:
        """容器运行时:面板问不到,但必须出现在清单里,且标成 unknown。"""
        src = _read(_WIRED)
        assert "容器运行时" in src, "容器运行时被从清单里省掉了 —— 省掉之后这张清单看起来是完整的,而它不是"
        # 头注释里也提了这四个字 —— 要找的是**代码里**那一处 rows.push。
        m = re.search(r"rows\.push\(\{[^}]*name:\s*'容器运行时'[^}]*\}\)", src, re.S)
        assert m, "容器运行时只在注释里说了,代码没真的往清单里推这一行"
        assert "'unknown'" in m.group(0), "容器运行时被标成了一个结论,可面板根本没问到过它"


class TestUnknownLooksDifferentFromNo:
    def test_the_unknown_dot_is_hollow_not_a_dim_solid(self) -> None:
        css = _read(_HUD)
        m = re.search(r"\.wired-row\[data-state='unknown'\]\s+\.wired-dot\s*\{([^}]*)\}", css)
        assert m, "unknown 那颗点没有自己的样子 —— 它会跟别的态混成一样"
        body = m.group(1)
        assert "inset" in body, "unknown 用的不是空心。暗一点的实心会被读成「不通」," "而「不通」是一个问过了的结论"

    def test_each_state_is_visually_distinct(self) -> None:
        """四态四种画法,不许两态共用一条规则。"""
        css = _read(_HUD)
        for state in ("on", "part", "off", "unknown"):
            assert (
                f".wired-row[data-state='{state}'] .wired-dot" in css
            ), f"{state} 这一态没有自己的画法 —— 它会跟别的态长得一样"


class TestItAsksBeforeItClaimsItDoesNotKnow:
    def test_endpoints_are_fetched_at_boot(self) -> None:
        """不在开机拉,「模型服务」那一行就会永远写着「没拉到」。"""
        src = _read(_MAIN)
        # 找模块级那一次调用(不带 await、不在别的函数体里的那种写法)
        assert re.search(r"^\s{2}void loadEndpoints\(\);", src, re.M), (
            "loadEndpoints 只在打开设置时才调 —— 那么后端明明通着," "清单上却一直写「端点列表没拉到」,说的和现实相反"
        )

    def test_the_list_is_fed_from_the_store_not_its_own_copy(self) -> None:
        """一处权威:每一行都从 store 推出来,不许自己存一份。"""
        src = _read(_MAIN)
        assert "deriveWired(" in src, "清单没有接上 deriveWired"
        block = src[src.index("deriveWired(") :][:500]
        for field in ("providers:", "devices:", "perception:", "connected:"):
            assert field in block, f"{field} 没喂进去 —— 那一行会凭空说话"


class TestDeadEntriesCannotBeClicked:
    def test_unwired_feed_cards_are_disabled_and_say_so(self) -> None:
        src = _read(_DOCK)
        assert "还没接上" in src, "没接上的喂入口没有如实说出来"
        assert "item.disabled = true" in src, "写着「点了不会有反应」却还能点 —— 那句话就又成了一句空话"


class TestTheRampIsOneHueFadingIntoWhite:
    """整面的颜色怎么分配 —— **量自所有者给的那张壁纸**，不是我定的。

    这一段的判据换过两轮，两轮换的都是"我以为的规矩"：

    * 第一轮钉的是「三态色温不许相同」—— 那时我以为色系是一根轴挪冷暖。
    * 第二轮钉的是「一相里至少三支色相 + 五支同 L 同 C」—— 那时我以为色系是
      多支颜色摆在一起。所有者看了实物：「为什么莫兰迪色系会出现其他奇奇怪怪
      的各种颜色」。

    **那两条判据本身就是错的。** 它们把我当时的误解钉住了，于是每次都"全绿"，
    而屏幕上难看。判据能把错误也钉牢，这是它最危险的地方。

    这一轮不再钉我的想法，钉**壁纸自己的数**（`51aa951c-image.png` 取样）：

        色相    只有一支      314° ± 3°
        明度    0.598 → 0.939  跨 0.34
        彩度    0.043 → 0.004  越亮越淡

    对照我上一版：五支色相、明度只跨 0.08、彩度基本不动 —— 所以整面是平的。

    根子不在色相上，在**分配**上：白不是铺上去的一层，是颜色变亮之后自己去的
    地方。彩度跟着明度降，亮到头就化进白。
    """

    def test_the_ramp_is_one_hue(self) -> None:
        """多一支都会被看出来 —— 所有者：「哪怕稍微加一点，其实都很明显」。"""
        css = _read(_TOKENS)
        hexes = re.findall(r"--m-\d:\s*(#[0-9a-f]{6})", css)
        assert len(hexes) >= 5, f"坡上不到五档：{hexes}"
        # 近白那几档彩度趋零，色相没有意义，会算出任意角度 —— 只看有彩度的。
        hues = [_oklch(h)[2] for h in hexes if _oklch(h)[1] > 0.004]
        span = max(hues) - min(hues)
        assert span <= 8, (
            f"坡上有 {len(hues)} 档带彩度的，色相跨了 {span:.1f} 度 —— "
            f"这一面只许一支色相。第二支哪怕很淡也会被看出来。"
        )

    def test_chroma_falls_as_lightness_rises(self) -> None:
        """**白是颜色变亮之后自己去的地方**，不是盖上去的一层。

        壁纸就是这么走的：L 0.598 时 C=0.043，L 0.939 时 C=0.004。
        彩度不跟着降的话，最亮那头会是一块"亮但仍然有色"的面 —— 它和白之间
        就有一道看得见的界，而不是化进去。
        """
        css = _read(_TOKENS)
        hexes = re.findall(r"--m-\d:\s*(#[0-9a-f]{6})", css)
        pairs = [(_oklch(h)[0], _oklch(h)[1]) for h in hexes]
        pairs.sort()
        for (l0, c0), (l1, c1) in zip(pairs, pairs[1:]):
            assert c1 <= c0 + 0.002, (
                f"L={l1:.3f} 比 L={l0:.3f} 亮，彩度却没降（{c0:.4f} → {c1:.4f}）—— " f"越亮越该越淡，才化得进白"
            )

    def test_the_ramp_actually_has_range(self) -> None:
        """明度跨度太小 = 整面是平的、闷的。这是上一版真正的毛病。"""
        css = _read(_TOKENS)
        ls = sorted(_oklch(h)[0] for h in re.findall(r"--m-\d:\s*(#[0-9a-f]{6})", css))
        span = ls[-1] - ls[0]
        assert span >= 0.18, f"明度只跨了 {span:.3f} —— 太平。壁纸跨 0.34，上一版跨 0.08 就是" f"「看着闷」的数值原因。"

    def test_the_shell_reads_the_ramp(self) -> None:
        css = _read(_HUD)
        shell = css[css.index(".shell") :][:1600]
        for pos in ("--field-top", "--field-mid", "--field-bot"):
            assert f"var({pos})" in shell, f".shell 没读 {pos} —— 坡定义了却没接上"
        assert "transition: background" in shell, "换相位是硬切的"

    def test_each_phase_sits_at_a_different_depth(self) -> None:
        """只有一支色相，换不了颜色 —— 相位换的是这道坡沉多深。"""
        css = _read(_TOKENS)
        seen = {}
        for phase in ("silent", "liminal", "manifest"):
            blk = css[css.index(f"[data-phase='{phase}']") :]
            blk = blk[: blk.index("}")]
            seen[phase] = re.findall(r"--field-\w+:\s*var\(--(m-\d)\)", blk)
            assert len(seen[phase]) >= 3, f"{phase} 没把坡排满：{seen[phase]}"
        assert len(set(map(tuple, seen.values()))) == 3, f"三相坐的深浅有重样的：{seen}"

    def test_no_colour_is_dragged_in_from_outside_the_ramp(self) -> None:
        """场只许站在这道坡上。

        所有者：「我让你在莫兰迪色系下手，没让你把其他颜色扯进来」。
        """
        css = _read(_TOKENS)
        for phase in ("silent", "liminal", "manifest"):
            blk = css[css.index(f"[data-phase='{phase}']") :]
            blk = blk[: blk.index("}")]
            refs = re.findall(r"--(?:field|wash)-\w+:\s*var\(--([\w-]+)\)", blk)
            outsiders = [r for r in refs if not re.fullmatch(r"m-\d", r)]
            assert not outsiders, f"{phase} 引了坡外的色：{outsiders}"


class TestStateIsToldByLightNotColour:
    """那几个点用**光**说状态，不用红黄绿。

    所有者：「那个点儿就是红绿绿黄，是有点不太好看……可以通过白光加动效的方式，
    让人体会，而不是这种奇怪的颜色」。

    这一面上只有一支色相，四个彩色小点是整面唯一跳出来的东西。而且它们坐在坡
    最浅那一头（近白），白点在白底上看不见 —— 所以光要靠**深度**表达：
    有光 = 浮起来，没光 = 沉下去。这本来就是这个面板的语言（岛上那几个小方块
    同理）。
    """

    def test_the_dots_use_no_semantic_colour(self) -> None:
        css = _read(_HUD)
        block = css[css.index(".wired-dot {") : css.index(".wired-name")]
        leaked = [t for t in ("--ok", "--warn", "--bad") if f"var({t})" in block]
        assert not leaked, f"那几个点又用回了语义色 {leaked} —— 整面只有一支色相，" f"这几个彩点会是唯一跳出来的东西"

    def test_on_carries_light_that_moves(self) -> None:
        """通 = 有光在走。静止的亮点说不出"它还活着"。"""
        css = _read(_HUD)
        m = re.search(r"\.wired-row\[data-state='on'\] \.wired-dot \{([^}]*)\}", css)
        assert m, "通那一态没有自己的画法"
        assert "animation" in m.group(1), "通没有动效 —— 光不走，就只是个亮点"
        assert "dot-breathe" in css and "@keyframes dot-breathe" in css

    def test_motion_stops_when_the_user_asked_for_less(self) -> None:
        """减少动效时呼吸要停 —— 那是人明确要求过的。

        停的动作**不在这个文件里**了：它收进了 tokens.css 的一条通配规则。
        原先 hud.css 里是逐处写 `.wired-dot { animation: none }`，那种写法被实测
        证明六条循环里会漏四条（`.rest::after` 那句拦不住 `.rest:hover::after`，
        伪类更特指），所以整批删掉、收成一条。

        这一条原先还带个兜底分支 `"animation: none" in css.split(...)[-1]`。
        逐处那句删掉之后它**照样绿** —— 匹上的是隔了一截的、毫不相干的
        `.pet[data-eyes='unknown'] .pet-blink { animation: none }`。
        兜底分支一并删掉：一条能靠别处的规则变绿的断言，等于没有断言。
        """
        # 先确认真有东西要停，否则这一条是在为一个不存在的动效把关
        hud = _read(_HUD)
        m = re.search(r"\.wired-row\[data-state='on'\] \.wired-dot \{([^}]*)\}", hud)
        assert m and "animation" in m.group(1), "通那一态本来就没有动效 —— 无事可停"

        block = _reduced_motion_block(_read(_TOKENS))
        assert re.search(
            r"\*\s*,\s*\*::before\s*,\s*\*::after\s*\{[^}]*animation\s*:\s*none\s*!important",
            block,
            re.S,
        ), (
            "tokens.css 的 prefers-reduced-motion 里没有那条通配的 `animation: none !important`。"
            "接线点的呼吸靠它停；少了它，`.wired-row[data-state='on'] .wired-dot` 的动效就没人拦。"
        )

    def test_all_four_states_still_look_different(self) -> None:
        """去掉颜色之后，四态仍然必须一眼分得开。"""
        css = _read(_HUD)
        for state in ("on", "part", "off", "unknown"):
            assert f".wired-row[data-state='{state}'] .wired-dot" in css, f"{state} 没有自己的画法"
