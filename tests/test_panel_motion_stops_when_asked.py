"""面板动效的两道门：**关得掉**，而且**周期不落在那一带**。

为什么要这一层
--------------
这两件事都已经各自翻过车，而且翻车的形状一模一样：判据写在注释里、执行散在各处。

关得掉这一件：hud.css 里六条 `infinite` 循环，原先每处各写一句
`animation: none` 想把它关掉。真浏览器里量出来是 **6 条里 4 条照转**：

  · `.rest::after { animation: none }` 拦不住 `.rest:hover::after` —— 伪类
    让后者更特指，那句从落地起就没生效过；
  · 脉冲、眨眼、光标三条压根没人写。

散着写一定会漏，而且下一条新写的动画默认就是漏的。所以停的动作收进
tokens.css 的一条通配规则，这里钉的是"它还在那儿、而且没人再散着写"。

周期这一件：0.17–0.25 Hz 是余光最容易被勾住的一带。这条判据被写进注释三回，
三回都跟现实对不上 —— line.ts 的收窄态曾是 0.196 Hz、pet.ts 最慢档曾是
0.192 Hz，注释都写着"都避开"；第三回是 pet.ts 给自己写了条**更窄的**带子
(0.18–0.22)，于是 understanding 档 4.3s = 0.233 Hz 被放行，它在真正的带里。
所以判据收进 src/motion.ts 一处，周期分布在三处（tokens.css / line.ts /
pet.ts），这里把三处的值都拿那一份判据过一遍。

扫源码的门**必须先去注释**。这仓库已经有三道门被自己的注释散文绊倒过
（散文里引用了它要禁的那段代码），所以下面每次读文件都走 `_code()`，
并且有一条自测钉住这件事。
"""

from __future__ import annotations

import pathlib
import re

import pytest

_PANEL = pathlib.Path(__file__).parent.parent / "electron" / "renderer" / "panel" / "src"
_TOKENS = _PANEL / "styles" / "tokens.css"
_HUD = _PANEL / "styles" / "hud.css"
_MOTION = _PANEL / "motion.ts"


def _band() -> tuple[float, float]:
    """频段边界从 src/motion.ts 读，**不在这儿再抄一份**。

    抄一份就是第四份。写这道门的时候我在这里确实抄了 0.17 / 0.25，还配了一条
    "两边对不上就报错"的断言 —— 那仍然是两份数字加一条对账，而对账只在两边都
    被想起来改的时候才有用。同一轮里又在
    tests/test_the_island_pet_is_wired_to_real_state.py 翻出了第四份
    (硬写的 0.18 / 0.22，正是放行 4.3s 的那条窄带)。所以两边都改成读这一处。
    """
    ts = _MOTION.read_text(encoding="utf-8")
    lo = re.search(r"AVOID_LO\s*=\s*([\d.]+)", ts)
    hi = re.search(r"AVOID_HI\s*=\s*([\d.]+)", ts)
    assert lo and hi, "motion.ts 里读不到 AVOID_LO / AVOID_HI"
    return float(lo.group(1)), float(hi.group(1))


def _code(path: pathlib.Path) -> str:
    """去掉注释再看。散文不是代码 —— 这条踩过三次。"""
    raw = path.read_text(encoding="utf-8")
    # 用等量换行替换，行号不漂
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), raw, flags=re.S)


def _in_band(seconds: float) -> bool:
    lo, hi = _band()
    hz = 1 / seconds
    return lo <= hz <= hi


def _cycle_tokens() -> dict[str, float]:
    """tokens.css 里的 --c-* 周期，单位秒。"""
    out: dict[str, float] = {}
    for name, num, unit in re.findall(r"(--c-[a-z-]+)\s*:\s*(\d*\.?\d+)(m?s)\s*;", _code(_TOKENS)):
        out[name] = float(num) / (1000 if unit == "ms" else 1)
    return out


def _reduce_block() -> str:
    """tokens.css 里 prefers-reduced-motion 那一整块（去注释后）。"""
    css = _code(_TOKENS)
    start = css.index("@media (prefers-reduced-motion: reduce)")
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[start : j + 1]
    raise AssertionError("reduced-motion 块没闭合")


class TestTheScannerReadsCodeNotProse:
    """先钉住这道门自己不会被散文绊倒 —— 前面已经有三道门栽在这儿。"""

    def test_comments_are_stripped(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x.css"
        f.write_text("/* animation: spin 3s infinite; --c-fake: 4.5s; */\n.a { color: red }")
        code = _code(f)
        assert "animation" not in code
        assert "--c-fake" not in code
        assert "color: red" in code

    def test_line_numbers_do_not_drift(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "y.css"
        f.write_text("a{}\n/* 一\n二\n三 */\nb{}")
        assert _code(f).count("\n") == 4


class TestEveryLoopGoesThroughAToken:
    """周期不许散在选择器里 —— 散着写就没法一次看完，也没法一次核。"""

    def test_there_are_loops_to_check(self) -> None:
        assert _loops(), "hud.css 里一条 infinite 动画都没有 —— 这道门在空转"

    def test_each_loop_takes_its_period_from_a_c_token(self) -> None:
        bad = [d for d in _loops() if "var(--c-" not in d]
        assert not bad, (
            "这些 infinite 动画把周期写死在了 hud.css 里，没走 tokens.css 的 --c-*：\n  "
            + "\n  ".join(bad)
            + "\n周期散着写，就没有任何一处能把它们跟 0.17–0.25 Hz 那条判据对一遍。"
        )


def _loops() -> list[str]:
    """hud.css 里所有会一直转的 animation 声明。"""
    return [
        m.group(1).strip() for m in re.finditer(r"animation\s*:\s*([^;}]+)", _code(_HUD)) if "infinite" in m.group(1)
    ]


class TestNoPeriodSitsInTheBand:
    def test_the_band_is_sane(self) -> None:
        """判据只有一份，所以这里不核对数值 —— 那会变成第二份。只兜住手滑。

        单一权威的意思就是：motion.ts 说了算。但一个退化的带子(lo >= hi)或者
        一个明显不是人眼那个量级的数，是手滑不是决定，所以还是拦一下。
        """
        lo, hi = _band()
        assert lo < hi, f"频段退化了：{lo} >= {hi}，等于谁都拦不住"
        assert 0.05 <= lo and hi <= 0.5, f"频段跑到了 {lo}–{hi} Hz —— 不在余光那个量级上，多半是手滑"

    def test_nobody_hardcodes_the_band_again(self) -> None:
        """这一条钉的是**第四份**。

        tests/ 里曾经硬写着 `0.18 <= hz <= 0.22`：比真带子窄，于是 4.3s = 0.233 Hz
        在那道门下是绿的。判据的第二份从来不是"多一层保险"，而是"两份里宽的那份
        被窄的那份悄悄废掉"。所以这里禁的就是把数字直接跟 hz 比。
        """
        offenders = []
        for f in sorted(pathlib.Path(__file__).parent.glob("*.py")):
            src = f.read_text(encoding="utf-8")
            src = re.sub(r'"""(?:.|\n)*?"""', "", src)  # 散文里写数字不算
            if re.search(r"hz\s*[<>]=?\s*0\.\d+|0\.\d+\s*[<>]=?\s*hz", src):
                offenders.append(f.name)
        assert not offenders, (
            f"这些测试又把频段数字硬写进了跟 hz 的比较：{offenders}。"
            "频段只有一份，在 electron/renderer/panel/src/motion.ts —— 读它，别抄它。"
        )

    def test_only_motion_ts_defines_the_band(self) -> None:
        """第二份判据就是第三次翻车的成因 —— pet.ts 曾自带一条更窄的带子。"""
        others = [
            p for p in sorted(_PANEL.rglob("*.ts")) if p != _MOTION and re.search(r"AVOID_(LO|HI)\s*=", _code_ts(p))
        ]
        assert not others, f"这些文件又各自定义了一份频段判据：{[str(p) for p in others]}"

    def test_cycle_tokens_exist(self) -> None:
        assert _cycle_tokens(), "tokens.css 里没有 --c-* —— 这道门在空转"

    def test_no_cycle_token_is_in_the_band(self) -> None:
        bad = {k: v for k, v in _cycle_tokens().items() if _in_band(v)}
        assert not bad, "这些 --c-* 落在 0.17–0.25 Hz 带里：" + ", ".join(
            f"{k}={v}s={1 / v:.3f}Hz" for k, v in bad.items()
        )

    def test_no_pet_breath_rate_is_in_the_band(self) -> None:
        rates = _pet_breath()
        assert rates, "pet.ts 的 BREATH 表没读到 —— 这道门在空转"
        bad = {k: v for k, v in rates.items() if _in_band(v)}
        assert not bad, "pet.ts 的呼吸档落在带里：" + ", ".join(f"{k}={v}s={1 / v:.3f}Hz" for k, v in bad.items())

    def test_no_line_cadence_is_in_the_band(self) -> None:
        cad = _line_cadence()
        assert len(cad) == 6, f"line.ts 的 CADENCE 应该是三相位各两栏共 6 个，读到 {len(cad)} 个"
        bad = {k: v for k, v in cad.items() if _in_band(v)}
        assert not bad, "line.ts 的脉冲周期落在带里：" + ", ".join(f"{k}={v}s={1 / v:.3f}Hz" for k, v in bad.items())


def _code_ts(path: pathlib.Path) -> str:
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), raw, flags=re.S)
    return re.sub(r"//[^\n]*", "", raw)


def _pet_breath() -> dict[str, float]:
    code = _code_ts(_PANEL / "ui" / "pet.ts")
    body = re.search(r"const BREATH[^=]*=\s*\{(.*?)\}", code, re.S)
    if not body:
        return {}
    return {k: float(v) for k, v in re.findall(r"(\w+)\s*:\s*'(\d*\.?\d+)s'", body.group(1))}


def _line_cadence() -> dict[str, float]:
    code = _code_ts(_PANEL / "ui" / "line.ts")
    body = re.search(r"const CADENCE[^=]*=\s*\{(.*?)\n\};", code, re.S)
    if not body:
        return {}
    out: dict[str, float] = {}
    for phase, seconds, slim in re.findall(
        r"(\w+)\s*:\s*\{\s*seconds:\s*(\d*\.?\d+)\s*,\s*slimSeconds:\s*(\d*\.?\d+)",
        body.group(1),
    ):
        out[f"{phase} 常态"] = float(seconds)
        out[f"{phase} 收窄"] = float(slim)
    return out


class TestTurningMotionOffActuallyTurnsItOff:
    """**这一条钉的是特指度**：停的那一条必须赢过任何还没写出来的选择器。"""

    def test_the_stop_is_universal_and_covers_pseudo_elements(self) -> None:
        block = _reduce_block()
        sel = re.search(r"(\*\s*,\s*\*::before\s*,\s*\*::after\s*\{[^}]*\})", block, re.S)
        assert sel, (
            "prefers-reduced-motion 里没有那条通配规则。`*` 不含伪元素，"
            "所以 ::before / ::after 必须单列 —— 漏掉伪元素，"
            "`.rest::after` 那道折痕光就又停不下来了。"
        )
        assert re.search(r"animation\s*:\s*none\s*!important", sel.group(1)), (
            "通配规则里没有 `animation: none !important`。少了 !important，"
            "任何带伪类的选择器（.rest:hover::after）都比它更特指，这条就是写了等于没写 —— "
            "上一版正是这么漏掉 4 条的。"
        )

    def test_movement_is_not_on_the_transition_whitelist(self) -> None:
        block = _reduce_block()
        wl = re.search(r"transition-property\s*:\s*([^;]+?)\s*!important", block, re.S)
        assert wl, "通配规则里没有 transition-property 白名单 —— 写死秒数的位移过渡会照样滑"
        props = {p.strip() for p in wl.group(1).replace("\n", " ").split(",")}
        moving = {
            "all",
            "transform",
            "translate",
            "scale",
            "rotate",
            "width",
            "height",
            "top",
            "left",
            "right",
            "bottom",
            "margin",
            "padding",
            "inset",
            "gap",
            "x",
            "y",
            "r",
            "grid-template-columns",
            "background",
        }
        leaked = props & moving
        assert not leaked, (
            f"白名单里混进了会动的东西：{sorted(leaked)}。"
            "注意 background 也算 —— .field::before 那道高光是靠径向渐变的位置走的。"
        )
        assert "opacity" in props, "白名单里连 opacity 都没有：关了动效不等于把界面变成硬切"

    def test_nobody_stops_animations_one_by_one_any_more(self) -> None:
        """散着停就是上一版漏掉 4 条的原因。要么全在那一条里，要么就是又散了。"""
        hud = _code(_HUD)
        offenders = []
        for m in re.finditer(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{", hud):
            depth, i = 0, m.end() - 1
            for j in range(i, len(hud)):
                if hud[j] == "{":
                    depth += 1
                elif hud[j] == "}":
                    depth -= 1
                    if depth == 0:
                        body = hud[i : j + 1]
                        break
            else:
                raise AssertionError("hud.css 的 reduced-motion 块没闭合")
            if re.search(r"animation[^;}]*:\s*none", body):
                offenders.append(body.strip()[:120])
        assert not offenders, (
            "hud.css 的 prefers-reduced-motion 块里又出现了逐处 `animation: none`：\n  "
            + "\n  ".join(offenders)
            + "\n停的动作只有 tokens.css 那一条。散着写的那一版，六条里漏了四条。"
        )
