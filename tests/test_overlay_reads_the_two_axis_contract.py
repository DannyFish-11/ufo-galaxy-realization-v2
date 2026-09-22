"""覆盖层这一层：它读的是契约，画的是编排，而且 WebGL 已经拆掉了。

## 这道门为什么存在

覆盖层的坏法全是**不报错的**：画面不对而已。着色器时代最典型的三个——

* ``u_intent`` 声明了、每帧都 ``setUniform``、着色器里一次都没读到 ——
  ``WebGLContext.setUniform`` 在 location 为 null 时**静默 return**，
  于是"接上了"和"没接上"在日志里长得一模一样。
* ``depth`` 0.30–0.42 **整段不画任何东西** —— 每次唤醒中间 0.13~0.35 秒纯黑。
* 契约 31 个字段，真正到达像素的只有 1.5 个。

换成 CSS 之后这些坏法一个都没消失，只是换了地方。所以这道门钉的是**能不能**，
不是**有没有写过**。

## 三条硬规矩（都栽过）

1. **3D 上下文那一层不能挂 grouping 属性**：``opacity`` / ``filter`` / ``mask`` /
   ``mix-blend-mode`` 任意一个都会让 ``transform-style: preserve-3d`` 失效，
   四面墙被拍扁成平面。做面板桌宠时栽过一次（opacity 压 transform），
   做这一层时又栽过两次。
2. **SVG 的几何属性必须带单位**：``y: 13.6`` 是非法长度，整条声明被静默丢弃。
   现场表现是"眼睛永远闭不上"，而代码读起来完全正确。
3. **空 ≠ 未知**：隐私急停要留下那道贴边细线，没有感知通路则什么都不留。
   两者都是"没有光"，但前者是用户按的、后者要去插摄像头。
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RENDERER = _ROOT / "electron" / "renderer"


def _html() -> str:
    return (_RENDERER / "index.html").read_text(encoding="utf-8")


def _js() -> str:
    """app.js 去掉注释 —— 判据钉的是代码，不是文档里提过这几个词。

    本仓库为"钉在注释上"栽过不止一次。
    """
    src = (_RENDERER / "app.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*(?:.|\n)*?\*/", " ", src)
    src = re.sub(r"(?<![:'\"])//[^\n]*", " ", src)
    return src


def _css() -> str:
    """index.html 的 <style> 段，同样去掉注释。"""
    html = _html()
    body = html[html.index("<style>") + 7 : html.index("</style>")]
    return re.sub(r"/\*(?:.|\n)*?\*/", " ", body)


class TestTheShaderStackIsGone:
    """WebGL 那一套是**拆掉**的，不是留着不用的。"""

    def test_no_shader_files_remain(self) -> None:
        for rel in ("shaders/lumiv.frag", "shaders/main.vert", "webgl/context.js"):
            assert not (_RENDERER / rel).exists(), (
                f"{rel} 还在。留着不用比删掉更坏：下一个人会以为它仍是渲染路径，"
                "而产品里那个把 GPU 整个关掉的开关（GALAXY_ELECTRON_GPU=0）"
                "会让它在真机上跑到 1.4fps。"
            )

    def test_the_page_does_not_load_them(self) -> None:
        html = _html()
        for token in ("webgl/context.js", "lumiv.frag", "main.vert"):
            assert token not in html, f"index.html 还在加载 {token}"

    def test_no_webgl_call_survives_in_the_renderer(self) -> None:
        js = _js()
        for token in ("getContext('webgl", 'getContext("webgl', "setUniform", "drawArrays"):
            assert token not in js, f"app.js 里还有 WebGL 调用：{token}"


class TestTheOrchestrationFollowsTheMainAxis:
    """整体编排跟主轴 ``lifecycle`` 走，不跟那个一维遗留深度走。"""

    def test_open_comes_from_lifecycle_not_depth_factor(self) -> None:
        """**这一条是这道门的判别点。**

        ``depth_factor`` 三个锚点是 static .05 / liminal .62 / manifest .92 ——
        一路单调上升；而这套编排里 manifest 恰恰是**空间收回去**的那一段。
        照着 depth 画，第三态会越张越大，跟它的语义正好相反。
        """
        js = _js()
        assert "OPEN_BY_LIFECYCLE" in js, "展开度不再由主轴给了"
        m = re.search(r"OPEN_BY_LIFECYCLE\s*=\s*\{(.*?)\}", js, re.S)
        assert m, "取不到 OPEN_BY_LIFECYCLE"
        table = m.group(1)
        assert re.search(r"liminal\s*:\s*1", table), "阈限态不是展开的，那这套编排是什么"
        assert re.search(r"manifest\s*:\s*0", table), (
            "manifest 不是 0 —— 收回就是执行的开场，第三态该把空间收干净。"
            "写成跟 depth_factor 一样单调上升，就是把语义画反了。"
        )

        # **表对不等于表被用到。** 第一版只钉了这张表的取值，于是把 _advance 里的
        # 落点整个换成 depth_factor、这张表一行不改，判据照样绿 —— 典型的
        # "钉在词上，不是钉在代码路径上"。所以下面钉的是**算落点的那几行**。
        body = js[js.index("_advance(") :]
        body = body[: body.index("\n  _loop(")]
        assert "OPEN_BY_LIFECYCLE" in body, "算落点的地方不读那张表了 —— 表还在，但没人用，画面照样会按深度走"
        assert "lifecycle" in body, "落点不再按主轴取"
        assert not re.search(r"\bdepth_factor\b", body), "落点又照 depth_factor 算了"

    def test_the_light_stays_out_while_manifesting(self) -> None:
        """表达期屏幕是干净的 —— 边光**不能**跟着空间一起回来。

        展开度在 silent 和 manifest 都是 0（一个还没展开、一个已经收回），
        单靠它分不出这两件事。第一态那条光的含义是"在场但不表达"，而 manifest
        恰恰是"对外表达" —— 收完之后它正在点你的鼠标，这时候亮着那条光等于说反了。

        实测栽过：第一版就是这样，manifest 一到边光就回来了。
        """
        js = _js()
        assert re.search(
            r"life\s*===\s*['\"]manifest['\"]\s*\)\s*\?\s*1", js
        ), "表达期没有把收回量钉死在满格 —— 边光会跟着空间一起回来"

    def test_the_two_exits_are_told_apart(self) -> None:
        """``handoff``（接着下一轮）与 ``dissolving``（做完就散）是两段不同的动作。

        契约对 ``transition_kind`` 的注释就是冲着这件事写的：**退场编排该看这一位，
        而不是看深度往哪边走** —— 深度倒着走只能把进场动画倒放。
        """
        js = _js()
        assert "transition_kind" in js, "覆盖层不读 transition_kind 了 —— 两种收场会变成同一段"
        assert re.search(r"===\s*['\"]dissolving['\"]", js), "没有单独认出 dissolving"
        # dissolving 要额外做"把光铺回去"这一步；handoff 不做。
        m = re.search(r"===\s*['\"]dissolving['\"]\s*\)\s*\{([^}]*)\}", js)
        assert m and "spreading" in m.group(1), "dissolving 没有触发铺回 —— 那它和 handoff 在画面上就是同一件事"

    def test_the_resident_bit_backs_up_the_one_tick_bit(self) -> None:
        """``transition_kind`` 是一拍性的，掉一拍消散就整段没了。

        桥每次广播完就把 ``_previous_lifecycle`` 推进到本拍（见
        ``lumiv_websocket_bridge._render_payload`` 结尾那一行），所以
        ``dissolving`` 只在**那一拍**出现，下一拍同档位就算成 ``none``。
        两种场合会把这一拍整个错过：覆盖层在返回弧中途才连上（重载／重连），
        或那一拍广播恰好掉了。结果是「做完就散」被演成「什么都没发生」。

        副轴的 ``is_returning`` 是驻留位（``continuum_phase == "receding"``，
        整段返回弧里都为真），契约把它单列出来的理由正是这个。所以这里钉：
        覆盖层必须**同时**读这两位，而且驻留位要真的能启动铺回。

        只读一位的两种写法都被这一条挡下：只读 ``transition_kind`` 会丢掉
        上面那两种场合；只读 ``is_returning`` 则分不出 handoff 与 dissolving
        （handoff 时副轴根本不进 receding，那一位一直是假）。
        """
        js = _js()
        assert "is_returning" in js, "覆盖层不读 is_returning —— 掉一拍 dissolving 就等于没消散过"
        # 驻留位必须真的通向铺回，而不是读出来放着。
        m = re.search(r"is_returning[^;]*;(?:.|\n){0,400}?\bspreading\s*=\s*true", js)
        assert m, "is_returning 读了但没接上铺回 —— 那它只是个没人用的变量"
        # 边沿触发：驻留位每拍都为真，照拍启动会把同一段消散反复重演。
        assert re.search(r"returning\s*!==\s*this\._lastReturning", js), (
            "is_returning 没有边沿判定 —— 返回弧里每一拍都会重演一遍铺回。"
            "（构造函数里存了一位不算：要的是拿它跟本拍比。这一条最初就只钉了变量名，"
            "把去掉比较、照拍触发的改法放过去了。）"
        )

    def test_the_segments_overlap_so_nothing_goes_blank(self) -> None:
        """两段首尾相接的话，边光退干净了、墙还没长出来，屏幕会空一段。

        这正是旧着色器 ``depth`` 0.30–0.42 全黑的同一个洞（每次唤醒 0.13~0.35 秒
        纯黑）。**重做一遍又踩过一次**，所以钉住。
        """
        js = _js()
        m = re.search(r"pull:\s*\[([\d.]+),\s*([\d.]+)\].*?grow:\s*\[([\d.]+),\s*([\d.]+)\]", js, re.S)
        assert m, "取不到 SEG 分段"
        pull_a, pull_b, grow_a, grow_b = (float(m.group(i)) for i in (1, 2, 3, 4))
        assert grow_a < pull_b, (
            f"延伸从 {grow_a} 才起步，而收回要到 {pull_b} 才走完 —— 中间空了一段。" "两段必须叠着走，不能首尾相接。"
        )


class TestThePreserve3dLayerStaysClean:
    """3D 那一层不能挂会分组的属性 —— 挂了四面墙就被拍扁。"""

    def test_the_box_has_no_grouping_property(self) -> None:
        css = _css()
        m = re.search(r"\.box\s*\{([^}]*)\}", css)
        assert m, ".box 没了"
        body = m.group(1)
        assert "preserve-3d" in body, ".box 不再是 3D 上下文"
        for prop in ("opacity", "filter", "mask", "mix-blend-mode", "backdrop-filter"):
            assert prop not in body, (
                f".box 上挂了 {prop} —— 它会让 preserve-3d 失效，四面墙被拍成平面。"
                "浓度写到每面墙自己身上（叶子节点，不影响 3D 上下文）。"
                "opacity 和 mix-blend-mode 各栽过一次，不再栽第三次。"
            )

    def test_the_stage_is_the_one_that_holds_perspective(self) -> None:
        css = _css()
        m = re.search(r"\.stage\s*\{([^}]*)\}", css)
        assert m and "perspective" in m.group(1), "透视不在 .stage 上了，箱体会塌成平面"


class TestTheCornersLeaveNoTrace:
    def test_all_four_walls_share_one_density(self) -> None:
        """角线的**唯一来源**是四面亮度不等。

        先前四面取 26/36/31/28，想靠调子差把折边读出来 —— 那恰恰就是四个角上那道痕。
        齐平之后相邻两面共用那条棱，棱上深度相同、取的是渐变同一处，接缝无从产生。
        """
        css = _css()
        per_wall = re.findall(r"\.wall-[tblr][^{]*\{([^}]*)\}", css)
        assert per_wall, "四面墙的规则没了"
        offenders = [b.strip() for b in per_wall if re.search(r"--n\s*:", b)]
        assert not offenders, (
            f"某一面单独设了近端浓度 --n：{offenders}。四面必须同值，" "不等就会在四个角上留下折边那道痕。"
        )


def _avoid_band() -> tuple[float, float]:
    """要躲开的频段 —— **从权威那一份读**，不在本文件里重写一遍数字。

    权威是 ``electron/renderer/panel/src/motion.ts`` 的 ``AVOID_LO`` /
    ``AVOID_HI``。那个文件开头记着这条判据栽过的两次，两次都是同一种栽法：
    判据写在注释里。而这一条判据**自己就是第三次**：它原先写死 0.18–0.22，
    比真带子（0.17–0.25）窄，于是覆盖层桌宠的 understanding 档
    4.3s = 0.233 Hz 从它底下走过去了 —— 那个值正是 motion.ts 点名记过的
    同一个值。所以现在不留第二份数字。
    """
    ts = (_RENDERER / "panel" / "src" / "motion.ts").read_text(encoding="utf-8")
    lo = re.search(r"AVOID_LO\s*=\s*([\d.]+)", ts)
    hi = re.search(r"AVOID_HI\s*=\s*([\d.]+)", ts)
    assert lo and hi, "panel/src/motion.ts 里读不到 AVOID_LO / AVOID_HI —— 权威那一份被改名或搬走了"
    return float(lo.group(1)), float(hi.group(1))


def _panel_breath() -> dict[str, str]:
    """面板那只桌宠的四档呼吸周期（panel/src/ui/pet.ts 的 BREATH）。"""
    ts = (_RENDERER / "panel" / "src" / "ui" / "pet.ts").read_text(encoding="utf-8")
    block = re.search(r"const BREATH:[^=]*=\s*\{(.*?)\}", ts, re.S)
    assert block, "panel/src/ui/pet.ts 里找不到 BREATH 表"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))


def _panel_pose() -> dict[str, str]:
    """面板那只桌宠的反应表（panel/src/ui/pet.ts 的 POSE）。"""
    ts = (_RENDERER / "panel" / "src" / "ui" / "pet.ts").read_text(encoding="utf-8")
    block = re.search(r"const POSE:[^=]*=\s*\{(.*?)\}", ts, re.S)
    assert block, "panel/src/ui/pet.ts 里找不到 POSE 表"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))


def _js_table(name: str) -> dict[str, str]:
    """app.js 里某张 ``{ k: 'v' }`` 常量表。"""
    m = re.search(r"const\s+" + name + r"\s*=\s*\{(.*?)\};", _js(), re.S)
    assert m, f"app.js 里找不到 {name}"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", m.group(1)))


class TestTheRhythmAvoidsTheBand:
    def test_no_period_lands_in_the_avoided_band(self) -> None:
        """那一带是刻意避开的 —— 与面板同一条纪律，也是同一份数字。

        判据把周期换算成频率去比，不看注释怎么写：面板那边就是靠这条算出来，
        抓到我在注释里写了一句假话（"5.2 秒 ≈ 0.19 Hz，刻意不落在带内"）。
        """
        lo, hi = _avoid_band()
        blob = _css() + _js()
        # ``.5s`` 这种省掉整数位的写法要认全：原先的 ``\d+\.?\d*`` 会把它读成
        # 5s = 0.2 Hz，凭空造出一个带内的假阳性。
        periods = {float(x) for x in re.findall(r"(?<![\w.])(\d*\.?\d+)s\b", blob)}
        periods = {p for p in periods if 0.3 <= p <= 30}
        assert periods, "一个周期都没找到，判据大概是失效了"
        bad = {p: round(1 / p, 3) for p in periods if lo <= 1 / p <= hi}
        assert not bad, f"这些周期落在 {lo}–{hi} Hz 带内：{bad}"


class TestTheTwoPetsAreTheSameCreature:
    """岛上那只和面板那只是**同一只东西**，不是两只长得像的。

    它们读的是同一位数据（``render.perception`` 与 ``render.liminal_activity``），
    所以同一份数据必须演出同一个样子。一只喘 6 秒另一只喘 9 秒、一只会对上一拍的
    决策有反应另一只没有 —— 那不是两种风格，那是其中一只在说假话。

    权威放在面板那边（``panel/src/ui/pet.ts``）：那只先有、四档周期在那儿被
    量过两回、要躲的频段也在它隔壁。覆盖层是纯 JS，import 不进 TS，所以表得抄
    一份；抄一份就会漂，于是这里逐条核对两边没漂。同一套做法在
    ``tests/test_tauri_frontend_staging.py::test_denylist_matches_build_rs``。
    """

    def test_the_breath_table_matches_the_panel(self) -> None:
        ours, theirs = _js_table("PET_RATE"), _panel_breath()
        assert ours == theirs, (
            f"两只桌宠的呼吸表漂了：只在一边的是 {set(ours.items()) ^ set(theirs.items())}。"
            "同一个 liminal_activity 必须喘成同一个样子。"
        )

    def test_the_reaction_table_matches_the_panel(self) -> None:
        ours, theirs = _js_table("POSE"), _panel_pose()
        assert ours == theirs, f"两只桌宠的反应表漂了：只在一边的是 {set(ours.items()) ^ set(theirs.items())}"

    def test_every_pose_has_somewhere_to_land(self) -> None:
        """表里每一档都得有对应的样式 —— 少一条那一档就是"演了但看不见"。"""
        css = _css()
        missing = [v for v in _js_table("POSE").values() if v != "rest" and f"data-react='{v}'" not in css]
        assert not missing, f"这几档反应没有对应的 CSS：{missing} —— 它们会被演一遍然后什么也没发生"

    def test_the_reaction_is_one_shot_and_edge_triggered(self) -> None:
        """``ambient_action`` 是**驻留位**：同一个决策会跟着之后每一帧一遍遍回来。

        照帧演的话它每一帧抽一下 —— 既刺眼，又把"刚才"说成了"一直"。
        而不撤回的话它会一直卡在"忍住没说"那个姿势，下一次决策可能几分钟以后，
        看着像死了。所以两件事都要：只认变化、演完撤回。
        """
        js = _js()
        assert "ambient_action" in js, "覆盖层的桌宠不读 ambient_action —— 面板那只读了，两只就不是同一只了"
        assert re.search(
            r"if\s*\(\s*key\s*===\s*this\._lastAct\s*\)\s*return", js
        ), "反应没有边沿判定 —— ambient_action 每一帧都会回来，照帧演它就一直在抽"
        assert re.search(r"delete\s+this\.pet\.dataset\.react", js), "反应演完不撤 —— 一个过去的决策会变成永久姿势"
        assert re.search(r"setTimeout\((?:.|\n)*?REACT_MS\)", js), "撤回不是定时的 —— 那就没有「演一遍」这回事"

    def test_the_reaction_outranks_the_resting_pose(self) -> None:
        """``data-react`` 与 ``data-phase`` 两边特指度相同，谁在后面谁赢。

        调个个儿的话，"忍住没说"那一下会被静息的 ``scale(.94)`` 吃掉 —— 属性
        照样设上了、DOM 里看着对，屏幕上什么都没发生。这类坏法最难查，所以钉住。
        """
        css = _css()
        phase = [m.start() for m in re.finditer(r"#pet\[data-phase='[^']+'\]\s*\.pet-body", css)]
        react = [m.start() for m in re.finditer(r"#pet\[data-react='[^']+'\]\s*\.pet-body", css)]
        assert phase and react, "data-phase / data-react 落在 .pet-body 上的规则没找齐"
        assert min(react) > max(phase), "反应那几条排在静息姿势前面 —— 同特指度下它会被盖掉，演了等于没演"


class TestThePetKeepsItsLayers:
    def test_pose_breath_blink_are_three_layers(self) -> None:
        """同挂一层的话动画那条 transform 压过普通声明，姿势永远推不动 ——
        而屏幕上因为还在呼吸看着"活的"，是最难查的一类坏法。"""
        css = _css()
        breath = re.search(r"\.pet-breath\s*\{([^}]*)\}", css)
        blink = re.search(r"\.pet-blink\s*\{([^}]*)\}", css)
        body = re.search(r"\.pet-body\s*\{([^}]*)\}", css)
        assert body and breath and blink, "桌宠那三层不全了"
        assert "animation" in breath.group(1), "呼吸不在 .pet-breath 上"
        assert "animation" in blink.group(1), "眨眼不在 .pet-blink 上"
        assert "animation" not in body.group(1), ".pet-body 上挂了动画 —— 姿势那一层必须干净，否则数据推不动它"

    def test_eye_geometry_carries_units(self) -> None:
        """``y: 13.6`` 是非法长度，整条声明会被静默丢弃。

        现场表现是"眼睛永远闭不上"，而代码读起来完全正确。栽过一次。
        """
        css = _css()
        for m in re.finditer(r"\.pet-eye[^{]*\{([^}]*)\}", css):
            for decl in re.finditer(r"\b(y|height)\s*:\s*([^;]+)", m.group(1)):
                val = decl.group(2).strip()
                assert re.search(r"(px|em|rem|%)$", val), (
                    f"pet-eye 的 {decl.group(1)} 写成了 {val!r} —— 无单位长度非法，"
                    "整条声明会被静默丢弃，眼睛就永远闭不上了"
                )


class TestEmptyIsNotUnknown:
    def test_privacy_pause_leaves_a_line_and_no_pathway_leaves_nothing(self) -> None:
        """两者都是"没有光"，但一个是用户按的、一个要去插摄像头。

        契约把 ``privacy_paused`` 单独给一位，正是因为"用户按停了"是一个**整体**
        姿态，而不是"恰好四条都闭着"。渲染上必须分得开：
        有那道贴边细线 = 我在但我闭着；没有 = 这台机器根本没有感知可用。
        """
        js = _js()
        assert "privacy_paused" in js, "覆盖层不读隐私急停了"
        # 急停时岛收成细线并且仍然可见；没有通路时连线都没有。
        assert re.search(r"paused\s*\?\s*2\s*:", js), "急停没有把岛收成那道细线"
        assert re.search(
            r"paused\s*\?\s*['\"]0\.85['\"]", js
        ), "急停时那道线不可见 —— 那它和「这台机器没有感知」就长得一样了"
        assert "unwired" in js, "没有区分「这条通路从没来过东西」"


class TestThePerceptionVocabularyComesFromTheContract:
    def test_all_five_modality_states_are_handled(self) -> None:
        """五档各有明确且不同的渲染含义，**刻意不是布尔** ——
        布尔会把三件不同的事压成一件。取值域见 core.phase_contract.MODALITY_STATES。
        """
        from core.phase_contract import MODALITY_STATES

        js = _js()
        m = re.search(r"SENSE_GLOW\s*=\s*\{([^}]*)\}", js)
        assert m, "取不到 SENSE_GLOW"
        table = m.group(1)
        for state in MODALITY_STATES:
            assert state in table, f"模态状态 {state} 没有对应的画法 —— 那一档会被画成别的档"

    def test_the_island_words_cover_every_activity(self) -> None:
        from core.phase_contract import LIMINAL_ACTIVITIES

        js = _js()
        m = re.search(r"ACTIVITY_WORD\s*=\s*\{([^}]*)\}", js)
        assert m, "取不到 ACTIVITY_WORD"
        for act in LIMINAL_ACTIVITIES:
            assert act in m.group(1), f"阈限内容 {act} 在岛上没有说法 —— 加档时漏改过一次（understanding）"
