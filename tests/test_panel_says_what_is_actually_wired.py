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


def _oklch(hex_colour: str) -> tuple:
    """sRGB 十六进制 → OKLCH 的 (L, C)。"""
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
    return big_l, math.hypot(a, bb)


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


class TestTheThreePhasesReallyDiffer:
    def test_every_phase_declares_its_own_wash(self) -> None:
        css = _read(_TOKENS)
        for phase in ("silent", "liminal", "manifest"):
            assert f"[data-phase='{phase}']" in css, f"{phase} 没有自己的色温"

    def test_the_shell_reads_the_field_tokens(self) -> None:
        """场写死的话,上面那几支 token 就白定义了。"""
        css = _read(_HUD)
        shell = css[css.index(".shell") :][:1400]
        for pos in ("--field-tl", "--field-tr", "--field-br", "--field-bl", "--field-bg"):
            assert f"var({pos})" in shell, f".shell 没读 {pos} —— 场定义了却没接上"
        assert "transition: background" in shell, "换相位是硬切的。硬切一帧换整面的底,是这个面板最不该有的出场方式"

    def test_each_phase_puts_a_different_cast_on_the_field(self) -> None:
        """三相排出来的场不许重样,否则等于没做。"""
        css = _read(_TOKENS)
        seen = {}
        for phase in ("silent", "liminal", "manifest"):
            blk = css[css.index(f"[data-phase='{phase}']") :]
            blk = blk[: blk.index("}")]
            seen[phase] = re.findall(r"--field-\w+:\s*var\(--(\w+)-\d\)", blk)
            assert len(seen[phase]) >= 4, f"{phase} 那一块没把场排满:{seen[phase]}"
        assert len(set(map(tuple, seen.values()))) == 3, f"三相的场有重样的:{seen}"

    def test_every_phase_shows_more_than_one_hue_at_once(self) -> None:
        """**这是所有者纠正过的那一条。**

        「你知道它为什么叫色系吗？不是单一的某种色温在混合,这种才是莫兰迪色系。」

        上一版每一相只是同一根灰紫轴挪了挪色温 —— 那是一个颜色的两个样子,不是
        一个系。一相里必须同时站着**至少三支不同色相**,整面才是几支颜色在互相
        渗,而不是一支颜色在变温。
        """
        css = _read(_TOKENS)
        for phase in ("silent", "liminal", "manifest"):
            blk = css[css.index(f"[data-phase='{phase}']") :]
            blk = blk[: blk.index("}")]
            hues = set(re.findall(r"--field-\w+:\s*var\(--(\w+)-\d\)", blk))
            assert len(hues) >= 3, (
                f"{phase} 这一相场上只有 {sorted(hues)} —— 少于三支色相," "那是一个颜色在变温,不是色系在过渡"
            )

    def test_the_family_shares_one_saturation_and_lightness(self) -> None:
        """五支之所以能凑在一起,靠的是 L/C 同档,不是色相接近。

        灰玫和灰青差了 130 度色相,照样不打架;真要坏事的是拿吸管从图上吸一支
        彩度不在这一档的色进来 —— 它会从整面里跳出来,而且说不清哪儿不对。
        这里用 OKLCH 反算,钉住三排各自的 L 与 C 一致。**要验"同一档"就得真的
        算**,靠眼看是看不出 0.01 的彩度差的,而正是那 0.01 让一支色跳出来。
        """
        css = _read(_TOKENS)
        for step in (1, 2, 3):
            hexes = re.findall(rf"--(?:rose|clay|sage|blue|viol)-{step}:\s*(#[0-9a-f]{{6}})", css)
            assert len(hexes) == 5, f"第 {step} 档不是五支:{hexes}"
            pairs = [_oklch(h) for h in hexes]
            ls = [p[0] for p in pairs]
            cs = [p[1] for p in pairs]
            assert max(ls) - min(ls) < 0.02, f"第 {step} 档明度不齐({ls})—— 亮的那支会跳出来"
            assert max(cs) - min(cs) < 0.012, f"第 {step} 档彩度不齐({cs})—— 艳的那支会跳出来"
