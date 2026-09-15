"""收起态那枚药丸里的微缩星系，必须真的是一座星系，而且真的在讲设备。

## 这道门为什么存在

那枚药丸原先装的是八格小方块（四条感知通路 + 几台设备）。方块得**数**，而数东西
要用中央视觉；这块面板要在余光里回答的却是「还有多少东西连着」。所以它换成了一座
微缩星系：整座有多亮 = 连接浓度，星海里几颗明显更亮的星 = 几台连着的设备。

这种画法有三种塌法，塌了都不报错、屏幕上还挺好看：

1. **塌成一堆星。** 撒一把随机点也是一片白，但它不是星系 —— 星系认得出来靠的是
   核球、棒、旋臂、晕这几件，少一件就只剩噪点。
2. **塌成一张静图。** 星表要是每帧重算，整片星海会跟着帧闪；要是干脆写死不跟设备
   走，那它就是一张壁纸，画得再好也没在说话。
3. **塌成看不出差别。** 这一种最隐蔽：浓度那条映射确实接上了，但星海自己先到了
   满白 —— 白之上没有更白，于是「有一台连着」那颗星再也亮不上去。**这道门里的
   余量那一条就是为它写的**，那正是这一版实际犯过、拿截图量出来才发现的毛病。
"""

from __future__ import annotations

import re
from pathlib import Path

_PANEL = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"
_GALAXY = _PANEL / "ui" / "galaxy.ts"
_ISLAND = _PANEL / "ui" / "island.ts"
_CSS = _PANEL / "styles" / "hud.css"


def _code(path: Path) -> str:
    """去掉注释再看。判据钉的是代码，不是文档里提过这个词。

    这一步不是讲究：本仓库栽过一次 —— 判据写成「css 里有 size-adjust 就算过」，
    而那三个字正巧出现在一段说明里，于是删掉被测的声明，门照样绿。
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?<![:'\"])//[^\n]*", " ", text)


def _body(code: str, opener: str) -> str:
    """把某个函数的花括号里那一段取出来。

    判据得钉在**那一段代码里**，不是钉在「整份文件里出现过这个词」。这份文件里
    栽过一次：`Math.exp(PITCH` 在旋臂和尘埃带里各有一处，于是把旋臂那一处拆掉，
    门照样绿 —— 因为尘埃带那一处还在。
    """
    i = code.index(opener)
    # 函数体那个 `{` 是**行末最后一个非空字符**。直接取 opener 之后第一个 `{` 是不行的：
    # `function project(...): { x: number; y: number } {` 的返回类型自己就带一对花括号，
    # 取到的会是类型注解，不是函数体 —— 于是判据量的是一句根本不含被测代码的话。
    j = next(k for k in range(i, len(code)) if code[k] == "{" and code[k + 1 :].split("\n", 1)[0].strip() == "")
    depth = 0
    for k in range(j, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return code[j : k + 1]
    raise AssertionError(f"{opener} 的花括号没配上")


def _rule(selector: str) -> str:
    """把某条 CSS 规则的花括号里那一段取出来。"""
    css = _CSS.read_text(encoding="utf-8")
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} 这条规则没了"
    return m.group(1)


def _lum_ramp(selector: str) -> tuple[float, float]:
    """读出 `calc(底 + 增益 * var(--gx-lum))` 里的那两个数。"""
    body = _rule(selector)
    m = re.search(
        r"opacity:\s*calc\(\s*([\d.]+)\s*\+\s*([\d.]+)\s*\*\s*var\(--gx-lum",
        body,
    )
    assert m, f"{selector} 的 opacity 不再是跟着 --gx-lum 走的 calc()：{body.strip()}"
    return float(m.group(1)), float(m.group(2))


# 会跟着连接浓度一起明暗的每一层。**一层都不能漏** —— 漏掉的那层不跟着变，
# 浓度低的时候它照旧亮着，整座星系就暗不下去。
_LAYERS = (".gx-field", ".gx-disc", ".gx-core", ".gx-dust polyline")


class TestItIsAGalaxyAndNotAPileOfDots:
    def test_it_has_a_bulge_a_bar_arms_and_a_halo(self) -> None:
        """四件缺一不可。撒一把点也是一片白，但那不是星系。"""
        code = _code(_GALAXY)
        assert re.search(r"\bfunction buildStars\b", code), "星表生成函数没了"

        # 旋臂得真的是对数螺线，而且这一条要钉在**旋臂那一段里** ——
        # 尘埃带那边也有一处同样的写法，钉在整份文件上等于没钉。
        arm = _body(code, "function armStars")
        assert (
            "Math.exp(PITCH" in arm
        ), "旋臂不再按对数螺线 r = r0·e^(bθ) 缠绕 —— 缠不起来的话那不是旋臂，是几道散开的射线"

        # 盘得真的按倾角投一遍，而不是随手压扁。
        proj = _body(code, "function project")
        assert "COS_I" in proj and "SIN_I" in proj, (
            f"投影里不再用倾角了：{proj.strip()}。" "少了它，盘就是一张被拉扁的圆图，旋臂不会近大远小。"
        )

        # 旋臂四条（两主两次）。数的是**调用**，不是定义 ——
        # 只按 `armStars(out` 数的话，函数定义自己也算一条，删掉一条调用还是够数。
        calls = re.findall(r"armStars\(out, r,", code)
        assert len(calls) >= 4, f"旋臂只剩 {len(calls)} 条 —— 银河系是四条主次旋臂，一条主臂看着像个逗号"

        # 核球、棒、晕
        for marker, what in ((r"核球|bulge", "核球"), (r"棒|\bbar\b", "棒"), (r"晕|halo", "晕")):
            assert re.search(marker, _GALAXY.read_text(encoding="utf-8")), f"星系里没有{what}了"

    def test_the_star_table_is_seeded_and_built_once(self) -> None:
        """星位必须定死。每帧重算的话整片星海跟着帧闪 —— 那是噪点，不是星系。"""
        code = _code(_GALAXY)
        assert "Math.random(" not in code, (
            "galaxy.ts 用上了 Math.random() —— 星位就不再定死了。"
            "每次重算星海都换一副样子，一台设备也就不再永远是同一颗星。"
        )
        assert re.search(r"const STARS = buildStars\(\);", code), "星表不再是模块加载时算一次的"

    def test_the_lit_stars_are_picked_apart_not_in_a_clump(self) -> None:
        """点亮的那几颗要摊得开。挤成一簇看着像星系那头坏了，不像「有几台连着」。"""
        code = _code(_GALAXY)
        assert "pickLit" in code, "挑星那一步没了"
        # 最远点遍历：任取前 n 颗都是铺开的。
        # **这一条不能写成「或」** —— 写成 `A or B` 的判据只和它最松的那一支一样紧：
        # 把真正算距离那一行换掉、只留下旁边的 `far = -1`，门照样会绿。
        pick = _body(code, "function pickLit")
        assert "order.map" in pick and "Math.min(" in pick, (
            "挑出来的星不再按「离已选的最远」排 —— 只连着三台时，点亮的会是挨在一起的三颗，"
            "看着像星系那头坏了，而不是「有三台连着」。"
        )


class TestBrightnessReallyFollowsHowManyAreConnected:
    def test_the_density_comes_from_the_roster_not_from_nothing(self) -> None:
        code = _code(_ISLAND)
        assert "galaxy.render(devices)" in code, "星系不再喂设备名册 —— 那它就是一张壁纸"
        gal = _code(_GALAXY)
        assert re.search(
            r"devices\.filter\(\(d\) => d\.state !== 'offline'\)", gal
        ), "浓度不再按「还有几台没离线」算 —— 它就不在讲连接浓度了"
        assert "--gx-lum" in gal, "算出来的浓度没有交给样式"

    def test_every_layer_gets_brighter_when_more_are_connected(self) -> None:
        """每一层都得跟着。有一层不跟，浓度低的时候整座星系就暗不下去。"""
        for sel in _LAYERS:
            floor, gain = _lum_ramp(sel)
            assert gain > 0, f"{sel} 的增益是 {gain} —— 连得越多反而不更亮，这条映射是反的"
            assert floor > 0, (
                f"{sel} 的底是 {floor} —— 一台都不在线时这一层整个没了。"
                "「暗」和「没有」是两件事：星系该暗下去，不该消失。"
            )

    def test_the_star_field_leaves_headroom_for_the_lit_ones(self) -> None:
        """**这一条是这道门的核心。**

        星是白的，底子是浅色的莫兰迪。星海要是自己先到了满白，那几颗「接着的设备」
        就再也亮不上去 —— 白之上没有更白。这一版实际栽过一次：星海顶到 0.97，
        一台设备连上之后，那颗星在截图里量出来只比周围高一点点。
        """
        floor, gain = _lum_ramp(".gx-field")
        ceiling = floor + gain
        assert ceiling <= 0.7, (
            f"星海最亮能到 {ceiling:.2f} —— 太靠近满白了。"
            "被点亮的那几颗就是靠比星海更白才显眼的，这一截余量一没，"
            "「有设备连着」在屏幕上就说不出来了。"
        )
        on = _rule(".gx-star[data-lit='on'] .gx-core-c")
        m = re.search(r"opacity:\s*([\d.]+)", on)
        assert m and float(m.group(1)) == 1, f"点亮的那颗不是满白：{on.strip()}"

    def test_connected_is_three_steps_not_a_boolean(self) -> None:
        """在线 / 降级 / 离线是三档。降级顶着在线那一档的亮度，等于把降级说成在线。"""
        on = float(re.search(r"opacity:\s*([\d.]+)", _rule(".gx-star[data-lit='on'] .gx-halo-c")).group(1))
        half = float(re.search(r"opacity:\s*([\d.]+)", _rule(".gx-star[data-lit='half'] .gx-halo-c")).group(1))
        assert 0 < half < on, f"降级那一档({half})没有落在离线(0)和在线({on})之间 —— 三档塌成了两档"
        gal = _code(_GALAXY)
        assert "'half'" in gal and "d.state === 'degraded'" in gal, "降级那一档不再由设备状态决定"


class TestAnEmptyRosterIsNotAQuietOne:
    """**空 ≠ 未知。** 名册没接上，跟「接上了、一台都没在线」是两件事。"""

    def test_wired_is_decided_by_whether_the_roster_arrived(self) -> None:
        gal = _code(_GALAXY)
        m = re.search(r"const wired = ([^;]+);", gal)
        assert m, "不再区分「名册接没接上」了"
        expr = m.group(1)
        assert "devices.length" in expr, (
            f"「接没接上」是按 {expr.strip()} 判的 —— 它得按名册**到没到**判，"
            "不是按有几台在线。按在线数判的话，五台全离线会被画成「后端没接上」。"
        )
        assert "state" not in expr, f"「接没接上」掺进了设备状态：{expr.strip()}"

    def test_nothing_is_lit_when_the_roster_never_arrived(self) -> None:
        """一颗都不许点亮 —— 点亮等于替后端断言「有这些设备连着」。"""
        gal = _code(_GALAXY)
        assert re.search(r"const lum = wired \?", gal), "名册没到时浓度不再强制归零"
        off = _rule(".galaxy[data-wired='false']")
        on = _rule(".galaxy[data-wired='true']")
        a = float(re.search(r"opacity:\s*([\d.]+)", off).group(1))
        b = float(re.search(r"opacity:\s*([\d.]+)", on).group(1))
        assert a < b, f"没接上({a})并不比接上了({b})淡 —— 这两件事在屏幕上分不开"


class TestTheCollapsedPillHoldsTheGalaxyAndNothingElse:
    def test_the_mini_view_only_gets_the_galaxy(self) -> None:
        code = _code(_ISLAND)
        m = re.search(r"mini\.append\(([^)]*)\)", code)
        assert m, "收起态那一层不再往里放东西了"
        assert m.group(1).strip() == "galaxy.root", f"收起态那枚药丸里除了星系还放了别的：{m.group(1).strip()}"

    def test_devices_that_do_not_fit_leave_a_trace(self) -> None:
        """星图只挑得出这么些颗互不粘连的星。**多出来的必须说出来。**

        画面上看着「就这么些台」，而实际上还有几台没画 —— 那正是这块面板最不许
        犯的那种错：看起来接上了，其实没有。
        """
        code = _code(_ISLAND)
        assert "LIT_CAPACITY" in code, "岛不再看星图放得下几台"
        # 留痕得在**读屏那句话里**。只要求文件里出现过 `unplaced ?` 是不够的：
        # 旁边 title 那一行也长这样，于是把 aria-label 里那一截删掉，门照样绿。
        i = code.index("'aria-label',", code.index("const unplaced"))
        label = code[i : code.index(");", i)]
        assert "unplaced" in label, (
            f"星图放不下的那几台没有写进无障碍标签：{label.strip()[:160]}。"
            "画面上看着「就这么些台」而实际还有几台没画 —— 那正是这块面板最不许犯的那种错。"
        )


class TestTheThingsTheTilesUsedToSayAreStillSaid:
    """星系讲的是**设备**，讲不了感知。撤掉那四格小方块之后，感知那几件事在收起态
    就没有画面可依附了 —— 而其中一件是**隐私急停停没停**。

    人按下「别看了」，是因为此刻不想被看／被听。这一位要是悄悄消失，收起态的药丸
    在急停生效时和平常长得一模一样 —— 这正是本仓库的头号毛病：看起来接上了，
    其实没有；或者反过来，看起来在采，其实已经停了。

    药丸上不再加东西是所有者定的，所以这道门守的是**说得出口的那一层**：读屏读得到，
    指针停上去看得到。眼睛那一侧仍然是空的，那是一个已知的、还没补的洞。
    """

    def test_the_privacy_stop_is_still_spoken_in_the_collapsed_state(self) -> None:
        code = _code(_ISLAND)
        i = code.index("const senseWord")
        block = code[i : code.index("island.setAttribute", i)]
        assert "privacy_paused" in block or "paused === true" in block, (
            f"收起态不再说「感知已暂停」了：{block.strip()[:200]}。"
            "撤掉那四格小方块之后，这一位在收起态**只剩这一条路**；它一断，"
            "急停生效时药丸和平常一模一样。"
        )
        # 三态，不是两态：停了 / 没停 / 还没收到过帧。压成布尔就等于替后端说话。
        assert "perception === null" in block, "「还没收到过感知帧」被压进了「没停」—— 面板此刻根本不知道，不能说成没停"
        # 说出来的话得真的进到给人看的那两处
        label_i = code.index("'aria-label'", i)
        label = code[label_i : code.index(");", label_i)]
        assert "senseWord" in label, "感知那句话没有进无障碍标签"
        title_i = code.index("island.title", i)
        title = code[title_i : code.index(";", code.index("join(", title_i))]
        assert "senseWord" in title, "感知那句话没有进 title —— 指针停上去看不到"

    def test_the_perception_link_being_down_is_also_spoken(self) -> None:
        """「四条都没在收」和「这条链路压根没建起来」是两件事，后者也得说得出口。"""
        code = _code(_ISLAND)
        i = code.index("const senseWord")
        block = code[i : code.index("island.setAttribute", i)]
        assert "wired" in block, "感知链路没建起来这一档在收起态没了 —— 它会被读成「此刻恰好安静」"


class TestItStaysInWhiteLight:
    def test_the_galaxy_introduces_no_second_hue(self) -> None:
        """白光之外不引第二种颜色。这块面板上稍微加一点别的色相都很明显。"""
        css = _CSS.read_text(encoding="utf-8")
        block = css[css.index(".galaxy {") : css.index(".tile {")]
        for hue in re.findall(r"#[0-9a-fA-F]{3,8}", block):
            assert hue.lower() in ("#fff", "#ffffff"), f"星系里出现了白之外的颜色：{hue}"
        for rgba in re.findall(r"rgba?\(([^)]*)\)", block):
            nums = [float(x) for x in rgba.split(",")[:3]]
            # 允许面板本来那一种灰紫阴影色（尘埃带用它），不允许别的色相
            assert nums == [255, 255, 255] or nums == [74, 66, 82], f"星系里出现了新的颜色：rgba({rgba})"
