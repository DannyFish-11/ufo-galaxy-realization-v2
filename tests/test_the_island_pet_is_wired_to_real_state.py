"""「自发注意力」那一栏右边那只小东西，必须真的接着数据。

## 这道门为什么存在

这一位原先是两行字。换成一张脸，是因为「一只在旁边待着的东西此刻什么心思」
这种事，人天生会从脸上读，不会从一行状语里读。

但脸有一种特有的坏法：**它长得可爱，所以没人会去验它说得对不对。** 一只永远
睁着眼、永远同一个姿势的桌宠，看上去跟接好了的一模一样 —— 而那正是本仓库的
头号毛病（看起来接上了，其实没有）套在一张脸上的样子。

## 这一版实际栽过的两跤，都钉在下面

1. **眼睛闭不上。** CSS 里写的是 `y: 18.4`，而无单位的长度在 CSS 里是非法的，
   整条声明被静默丢弃。截图里量出来眼高一直是 10px —— 屏幕上眼睛从没闭过，
   但代码读起来完全正确。
2. **姿势推不动。** 呼吸动画和姿势挂在同一层，动画的 `transform` 优先级压过
   普通声明。屏幕上看着"有在动"（那是呼吸），于是最难查。

两条都不是"写错了一个值"，而是**写了等于没写**。所以这道门量的是几何量本身，
不是"有没有出现这个词"。
"""

from __future__ import annotations

import re
from pathlib import Path

_PANEL = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"
_PET = _PANEL / "ui" / "pet.ts"
_ISLAND = _PANEL / "ui" / "island.ts"
_CSS = _PANEL / "styles" / "hud.css"


def _code(path: Path) -> str:
    """去掉注释再看 —— 判据钉的是代码，不是文档里提过这个词。"""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?<![:'\"])//[^\n]*", " ", text)


def _css() -> str:
    """CSS 也要去掉注释再看。

    本文件自己就栽过一次：判据查「关了动效有没有把姿势一起停掉」，而我在注释里
    解释这一跤时写下了 `.pet-body` 三个字 —— 判据读到的是那句解释，不是代码。
    跟这一轮修掉的那五条空判据同一个病，只是方向反过来：**误报**。
    """
    return re.sub(r"/\*.*?\*/", " ", _CSS.read_text(encoding="utf-8"), flags=re.S)


def _rule(selector: str) -> str:
    css = _css()
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} 这条规则没了"
    return m.group(1)


def _eye(state: str) -> dict[str, str]:
    """读出某一档眼睛的几何量。"""
    body = _rule(f".pet[data-eyes='{state}'] .pet-eye")
    return dict(re.findall(r"([a-z-]+):\s*([^;]+);", body))


def _len_px(raw: str) -> float:
    """把一个 CSS 长度读成数。**没有单位就是非法的** —— 这正是要钉的那一跤。"""
    m = re.fullmatch(r"\s*(-?[\d.]+)px\s*", raw)
    assert m, (
        f"「{raw.strip()}」不是合法的 CSS 长度。SVG 的几何属性(y / height)当作 CSS 写时"
        "必须带单位；无单位的数会让整条声明被静默丢弃 —— 代码读起来是对的，屏幕上什么都没发生。"
    )
    return float(m.group(1))


class TestTheEyesReallyClose:
    def test_shut_is_geometrically_different_from_open(self) -> None:
        """闭眼必须是**量得出来的**不同，不是换了个类名。"""
        op, sh = _eye("open"), _eye("shut")
        oh, sh_h = _len_px(op["height"]), _len_px(sh["height"])
        assert sh_h < oh / 2, (
            f"闭着({sh_h}px)并不比睁着({oh}px)矮多少 —— 屏幕上看不出它闭了眼。"
            "这一档是隐私急停在展开态最快被看见的地方，它一哑，急停就又没有样子了。"
        )
        # 压扁的同时要往下挪，否则缝会贴在上眼眶上，看着像翻白眼不像闭眼
        assert _len_px(sh["y"]) > _len_px(op["y"]), "闭眼没有往下挪 —— 缝会贴在上沿"

    def test_not_knowing_is_its_own_state(self) -> None:
        """三档，不是布尔。**还没收到过帧 ≠ 没停。**"""
        unk = _eye("unknown")
        op = _eye("open")
        assert _len_px(unk["height"]) == _len_px(op["height"]), "「不知道」被画成了闭眼 —— 那等于替后端断言已经停了"
        a, b = float(unk["opacity"]), float(op["opacity"])
        assert a < b, f"「不知道」({a})跟「在采」({b})长得一样 —— 面板此刻根本不知道，不能画成正看着"

    def test_the_eyes_are_driven_by_the_privacy_flag(self) -> None:
        code = _code(_PET)
        m = re.search(r"svg\.dataset\['eyes'\]\s*=\s*([^;]+);", code)
        assert m, "眼睛不再由数据决定了"
        expr = m.group(1)
        assert "paused" in expr and "null" in expr, f"眼睛这一位不是三态：{expr.strip()}"
        island = _code(_ISLAND)
        # 喂法是**一整份实时帧**，不是两个参数了。查的是那份帧里有没有带上「停没停」。
        m2 = re.search(r"pet\.render\(\{(.*?)\}\);", island, re.S)
        assert m2, "岛不再喂它了"
        assert "paused," in m2.group(1), "岛不再把「停没停」喂给它 —— 脸就会跟那行字讲岔"


class TestTheLiveLayerAndTheOneOffReaction:
    """底子是实时的，上面叠一次性的反应。**这两层不能混。**

    `ambient_action` 是「上一拍」—— 一个已经发生完的事实。拿它当常驻姿势，它会一直
    卡在「忍住没说」那个样子不动，而下一次决策可能是几分钟以后。看着像死了，而且把
    「刚才」说成了「一直」。
    """

    def test_breathing_and_pose_are_on_different_layers(self) -> None:
        """**这一条守的是实际栽过的那一跤。**

        动画的 transform 优先级压过普通声明。两者同挂一层时姿势永远推不动，
        而屏幕上因为还在呼吸，看着像"活的" —— 最难查的一类坏法。
        """
        body = _rule(".pet-body")
        breath = _rule(".pet-breath")
        assert "animation" not in body, (
            f".pet-body 上又挂了动画：{body.strip()}。"
            "姿势就在这一层，动画一上来就把它压住了 —— 反应会全部失效，而画面上还在动。"
        )
        assert "animation" in breath, ".pet-breath 上没有呼吸了"

    def test_blinking_is_its_own_layer_too(self) -> None:
        """眨眼是 transform，眼睛的开合是几何量 —— 同一个坑，不能再踩一次。

        挂同一层的话眨眼那条动画会把 `y` / `height` 压住，「按了急停」就闭不上了。
        """
        blink = _rule(".pet-blink")
        # 查的是**它真的在放哪一支动画**，不是「出现过 animation 这个词」——
        # `animation: none` 照样含那个词，判据会绿而屏幕上一动不动。
        m = re.search(r"animation:\s*([\w-]+)", blink)
        assert m and m.group(1) != "none", f"眨眼没了：{blink.strip()}。上面那些状态再准，看着也像一张贴纸。"
        assert f"@keyframes {m.group(1)}" in _css(), f"眨眼放的是 {m.group(1)}，而这支关键帧根本不存在"
        assert "height" not in blink and re.search(r"scaleY", _css()), "眨眼不该去改几何量"
        # 本来就闭着的时候不眨 —— 那会变成抽搐
        shut = _css()
        assert re.search(
            r"\.pet\[data-eyes='shut'\] \.pet-blink[^{]*\{[^}]*animation:\s*none", shut
        ), "眼睛已经闭上了还在眨 —— 那是抽搐，不是眨眼"

    def test_the_reaction_is_one_off_not_a_permanent_pose(self) -> None:
        """演一遍就撤。**撤不掉的反应是在说谎** —— 它把「刚才」说成了「一直」。"""
        code = _code(_PET)
        assert "data-react" in _css(), "反应那一层没了"
        # 撤必须发生在**那个定时器里**。
        # 只查「文件里有 delete」是不够的：else 分支里还有一处，把定时器里那处
        # 换掉，判据照样绿 —— 而反应就永远撤不掉了。
        m = re.search(r"setTimeout\(\(\) => \{(.*?)\}", code, re.S)
        assert m, "反应没有时限，等于常驻姿势"
        assert "delete svg.dataset['react']" in m.group(1), (
            f"定时器到点之后没有把反应撤掉：{m.group(1).strip()}。"
            "它会一直卡在上一次决策的姿势上 —— 把「刚才」说成了「一直」。"
        )

    def test_the_base_layer_moves_with_every_frame(self) -> None:
        """底子必须**每帧都在动**，不能只认那个几分钟才变一次的决策位。"""
        code = _code(_PET)
        for field, what in (("phase", "主轴此刻在哪一相"), ("activity", "阈限态里它在干嘛"), ("sensing", "在不在收")):
            assert re.search(rf"svg\.dataset\['{field}'\]", code), f"底子里没有「{what}」了"
        # 阈限内容是有序递进的，节奏也该是递进的
        rates = re.findall(r"(none|understanding|thinking|rehearsing): '([\d.]+)s'", code)
        assert len(rates) == 4, f"呼吸节奏不再按阈限内容分四档：{rates}"
        order = {k: float(v) for k, v in rates}
        assert (
            order["none"] > order["understanding"] > order["thinking"] > order["rehearsing"]
        ), f"越使劲反而喘得越慢：{order}"
        # 刻意避开 0.2 Hz 那一带（0.18~0.22 Hz，即 4.55~5.56 秒）
        for k, v in order.items():
            hz = 1 / v
            assert not (0.18 <= hz <= 0.22), (
                f"{k} 那一档周期 {v}s ≈ {hz:.3f} Hz，落在 0.2 Hz 那一带 —— "
                "那一带最容易被余光当成「有事发生」而反复把注意力拽走"
            )

    def test_the_reaction_comes_from_the_backend_decision(self) -> None:
        code = _code(_PET)
        m = re.search(r"svg\.dataset\['react'\]\s*=\s*([^;]+);", code)
        assert m, "反应不再由数据决定了"
        expr = " ".join(m.group(1).split())
        assert expr == "POSE[live.act] ?? 'rest'", (
            f"反应的来路变了：{expr}。它必须直接按 ambient_action 查表 —— "
            "中间插任何一个恒真分支，四档就全塌成一档，而屏幕上因为还在呼吸，看着像活的。"
        )
        assert re.search(r"POSE: Record<AmbientAction", code), "四档没有各自的反应"

    def test_the_four_reactions_are_actually_different(self) -> None:
        css = _css()
        r = dict(re.findall(r"\.pet\[data-react='(\w+)'\] \.pet-body\s*\{\s*transform:\s*([^;]+);", css))
        vals = [v.strip() for v in r.values()]
        assert len(vals) >= 3, f"反应只剩 {len(vals)} 种"
        assert len(set(vals)) == len(vals), f"有两档反应写的是同一个变换：{r}"


class TestTheFaceAndTheWordsCannotDisagree:
    def test_the_wording_has_one_home(self) -> None:
        """脸和话讲的是同一件事。**两处各存一份，迟早讲岔。**"""
        island = _code(_ISLAND)
        assert "POSE_WORD" in island and "from './pet'" in island, "岛不再从 pet.ts 取那几句话"
        assert not re.search(
            r"const AMBIENT_WORD", island
        ), "岛里又攒了一份自己的说法 —— 同一件事两处各写各的，改一处忘一处就开始讲岔"

    def test_reduced_motion_keeps_the_facts(self) -> None:
        """关了动效的人：呼吸可以停，**姿势和眼睛不能停** —— 那两样是事实，不是动效。"""
        css = _css()
        i = css.index(".pet-breath")
        block = css[i:]
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{([^}]*\}[^}]*)\}", block)
        assert m, "桌宠没有照顾关了动效的人"
        inner = m.group(1)
        assert ".pet-body" not in inner, "关了动效把底子那一层也停掉了 —— 相位就看不出来了"
        assert ".pet-eye" not in inner, "关了动效把眼睛也停掉了 —— 隐私急停就又看不见了"
