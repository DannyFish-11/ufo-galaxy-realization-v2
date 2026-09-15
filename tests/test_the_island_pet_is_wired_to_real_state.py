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
        m = re.search(r"svg\.dataset\['eyes'\] = ([^;]+);", code)
        assert m, "眼睛不再由数据决定了"
        expr = m.group(1)
        assert "paused" in expr and "null" in expr, f"眼睛这一位不是三态：{expr.strip()}"
        island = _code(_ISLAND)
        assert re.search(r"pet\.render\(act, paused\)", island), "岛不再把「停没停」喂给它 —— 脸就会跟那行字讲岔"


class TestThePoseIsNotJustBreathing:
    def test_breathing_and_pose_are_on_different_layers(self) -> None:
        """**这一条守的是实际栽过的那一跤。**

        动画的 transform 优先级压过普通声明。两者同挂一层时姿势永远推不动，
        而屏幕上因为还在呼吸，看着像"活的" —— 最难查的一类坏法。
        """
        body = _rule(".pet-body")
        breath = _rule(".pet-breath")
        assert "animation" not in body, (
            f".pet-body 上又挂了动画：{body.strip()}。"
            "姿势就在这一层，动画一上来就把它压住了 —— 四种姿势会全部失效，而画面上还在动。"
        )
        assert "animation" in breath, ".pet-breath 上没有呼吸了"
        # 姿势确实写在 .pet-body 上
        css = _css()
        poses = re.findall(r"\.pet\[data-pose='(\w+)'\] \.pet-body\s*\{([^}]*)\}", css)
        assert len(poses) >= 4, f"姿势只剩 {len(poses)} 种 —— 四档各一种，少一种那一档就没画"

    def test_the_four_poses_are_actually_different(self) -> None:
        """四种姿势不能有两种长得一样 —— 那等于把两档并成一档。"""
        css = _css()
        poses = dict(re.findall(r"\.pet\[data-pose='(\w+)'\] \.pet-body\s*\{\s*transform:\s*([^;]+);", css))
        vals = [v.strip() for v in poses.values()]
        assert len(set(vals)) == len(vals), f"有两档姿势写的是同一个变换：{poses}"

    def test_the_pose_comes_from_the_backend_decision(self) -> None:
        code = _code(_PET)
        m = re.search(r"svg\.dataset\['pose'\] = ([^;]+);", code)
        assert m, "姿势不再由数据决定了"
        # 钉**形状**，不是钉「出现过 act 这三个字母」。
        # 只查「含 act」是不够的：`true ? 'rest' : …act…` 照样含 act，而它是写死的。
        expr = " ".join(m.group(1).split())
        assert expr == "act === null ? 'unknown' : POSE[act] ?? 'rest'", (
            f"姿势的来路变了：{expr}。"
            "它必须先分出「还没收到过帧」，再直接按 ambient_action 查表 —— "
            "中间插任何一个恒真分支，四档就全塌成一档，而屏幕上因为还在呼吸，看着像活的。"
        )
        assert re.search(r"POSE: Record<AmbientAction", code), "四档没有各自的姿势表"


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
        assert ".pet-body" not in inner, "关了动效把姿势也停掉了 —— 那一档事实就没了"
        assert ".pet-eye" not in inner, "关了动效把眼睛也停掉了 —— 隐私急停就又看不见了"
