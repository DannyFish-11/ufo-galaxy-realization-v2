"""tests/test_vision_ui_projection_stage_b.py
=================================================
视觉理解结果 → 统一控件契约（Stage B）。

要解决的问题
------------
``vision_pipeline`` 已经能从截图解出 OCR 文本框与 GUI 元素树（四级降级），
但它产出的是自己的 ``VisionResult``；而 grounding 那条链吃的是 ``UIGraph``。
于是契约里 ``UISource.VISION`` 与 ``UISource.OCR`` 两个来源**声明了却零生产者**，
真正能产出它们的模块只挂在两个 HTTP 端点上，主链路走不到。

本阶段补的是中间这一步投影——不是新的识别器，是把已经识别出来的东西
接进同一份契约。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. POLICY_1 纯投影，回滚等于删文件。
  A02. POLICY_2 视觉节点永不冒充 1.0 置信度。

Group B — Vocabulary mapping
  B01. ElementType 表覆盖 vision_pipeline 实际会产出的全部类型。
  B02. 交互类型映射不包含 none —— 那是"不可交互"，映射成动作即谎报。
  B03. 容器类落到 group，不冒充可交互控件。

Group C — 投影本体
  C01. 可交互按钮 → clickable。
  C02. 输入框 → editable 且不 clickable。
  C03. 子树递归投影。
  C04. 坐标原样落到 UIBounds。
  C05. 置信度带过来且被限制在 1.0 以下（POLICY_2）。
  C06. 边界框坏了不抛，节点仍在但没有坐标锚点。

Group D — OCR 去重
  D01. 与已识别控件高度重叠的 OCR 文本不再单独建节点。
  D02. 独立文本保留。
  D03. 空文本丢弃。
  D04. include_ocr=False 时完全不产出 OCR 节点。

Group E — 失败必须可区分
  E01. 空结果。
  E02. 识别失败（带原因）。
  E03. 识别失败但没给原因 —— 也要说出"没给原因"。
  E04. 识别成功但无控件。
  E05. 以上四种都返回空图 + 非空说明，且说明彼此不同。

Group F — 融合
  F01. 无结构图时原样返回视觉图。
  F02. 有结构图时产出混合图，merged_from 记录两个来源。
  F03. 结构缺 label 由视觉补上。
  F04. 融合抛异常时退回结构图，不丢掉两边。

Group G — 活路径
  G01. ui_act 接受 screenshot_b64。
  G02. 视觉链路不可用时说明原因，不是静默失败。
  G03. 结构图与截图都给时两条腿一起走（融合），不是二选一。
  G04. 融合失败退回结构图，不丢掉本来就好的那份。
"""

from __future__ import annotations

import pytest

from core.schemas.ui_element import UIBounds, UIElementNode, UIGraph, UISource
from core.vision_pipeline import (
    BoundingBox,
    ElementType,
    GUIElement,
    InteractionType,
    OCRWord,
    SceneContext,
    VisionResult,
)
from core.vision_ui_projection import (
    ELEMENT_ROLE_MAP,
    INTERACTION_ACTION_MAP,
    project_and_merge,
    project_vision_result,
)


def _btn(text="发送", x=1180, y=2020, w=120, h=80, conf=0.91):
    return GUIElement(
        element_id="e-btn",
        element_type=ElementType.BUTTON,
        text=text,
        bbox=BoundingBox(x, y, w, h),
        confidence=conf,
        interactable=True,
        interaction_types=[InteractionType.CLICK],
    )


def _input(text="输入消息"):
    return GUIElement(
        element_id="e-input",
        element_type=ElementType.INPUT,
        text=text,
        bbox=BoundingBox(60, 2010, 1000, 80),
        confidence=0.88,
        interactable=True,
        interaction_types=[InteractionType.TYPE],
    )


def _ok(elements=None, words=None, app="微信", engine="deepseek-ocr2"):
    return VisionResult(
        success=True,
        gui_elements=list(elements or []),
        ocr_words=list(words or []),
        scene=SceneContext(app_name=app, platform="android"),
        engine_used=engine,
    )


class TestGroupAPolicies:
    def test_a01_projection_is_additive(self):
        from core.vision_ui_projection import VISION_PROJECTION_IS_ADDITIVE_POLICY

        text = VISION_PROJECTION_IS_ADDITIVE_POLICY
        assert "POLICY_1" in text
        assert "never becomes a second recogniser" in text

    def test_a02_vision_nodes_are_never_certain(self):
        from core.vision_ui_projection import VISION_NODES_ARE_NEVER_CERTAIN_POLICY

        text = VISION_NODES_ARE_NEVER_CERTAIN_POLICY
        assert "POLICY_2" in text
        assert "never 1.0" in text


class TestGroupBVocabulary:
    def test_b01_role_map_covers_every_element_type(self):
        """漏一个类型,那类控件就会被静默投影成 text —— 可点的东西变成不可点。"""
        for member in ElementType:
            assert member.value in ELEMENT_ROLE_MAP, f"{member.value} 没有 role 映射"

    def test_b02_none_interaction_is_not_mapped(self):
        assert InteractionType.NONE.value not in INTERACTION_ACTION_MAP

    def test_b03_containers_are_not_controls(self):
        assert ELEMENT_ROLE_MAP["container"] == "group"
        assert ELEMENT_ROLE_MAP["card"] == "group"


class TestGroupCProjection:
    def test_c01_button_is_clickable(self):
        graph, _ = project_vision_result(_ok([_btn()]))
        node = graph.find_by_label("发送")
        assert node is not None and node.clickable is True
        assert node.source is UISource.VISION

    def test_c02_input_is_editable_not_clickable(self):
        graph, _ = project_vision_result(_ok([_input()]))
        node = graph.find_by_label("输入消息")
        assert node.editable is True
        assert node.clickable is False, "输入框被判成可点,模型会去点它而不是往里写"

    def test_c03_children_recurse(self):
        parent = _btn(text="卡片")
        parent.element_type = ElementType.CARD
        parent.children = [_btn(text="里面的按钮")]
        graph, _ = project_vision_result(_ok([parent]))
        assert graph.find_by_label("里面的按钮") is not None

    def test_c04_bounds_carry_over(self):
        graph, _ = project_vision_result(_ok([_btn()]))
        node = graph.find_by_label("发送")
        assert node.bounds is not None
        assert (node.bounds.x, node.bounds.y, node.bounds.width, node.bounds.height) == (1180, 2020, 120, 80)
        assert node.bounds.center() == (1240, 2060)

    def test_c05_confidence_stays_below_one(self):
        graph, _ = project_vision_result(_ok([_btn(conf=1.0)]))
        node = graph.find_by_label("发送")
        assert node.confidence < 1.0, "视觉推断冒充了结构事实的确定性(POLICY_2)"

    def test_c06_broken_bounds_do_not_raise(self):
        bad = _btn()
        bad.bbox = object()  # 没有 x/y/width/height
        graph, _ = project_vision_result(_ok([bad]))
        node = graph.find_by_label("发送")
        assert node is not None, "一个坏坐标不该让整屏都消失"
        assert node.bounds is None


class TestGroupDOcrDedup:
    def test_d01_overlapping_text_is_absorbed(self):
        """同一个按钮不该既是按钮又是文字 —— 模型引用 [n] 时会看到两个都对的候选。"""
        word = OCRWord(text="发送", bbox=BoundingBox(1185, 2030, 110, 60), confidence=0.95)
        graph, note = project_vision_result(_ok([_btn()], [word]))
        labels = [n.label for n in graph.flatten() if n.label == "发送"]
        assert len(labels) == 1
        assert "独立文本" not in note

    def test_d02_independent_text_is_kept(self):
        word = OCRWord(text="今天天气不错", bbox=BoundingBox(60, 400, 600, 50), confidence=0.9)
        graph, _ = project_vision_result(_ok([_btn()], [word]))
        node = graph.find_by_label("今天天气不错")
        assert node is not None and node.source is UISource.OCR

    def test_d03_empty_text_is_dropped(self):
        word = OCRWord(text="   ", bbox=BoundingBox(10, 10, 10, 10), confidence=0.9)
        graph, _ = project_vision_result(_ok([_btn()], [word]))
        assert all(n.source is not UISource.OCR for n in graph.flatten())

    def test_d04_ocr_can_be_switched_off(self):
        word = OCRWord(text="今天天气不错", bbox=BoundingBox(60, 400, 600, 50), confidence=0.9)
        graph, _ = project_vision_result(_ok([_btn()], [word]), include_ocr=False)
        assert graph.find_by_label("今天天气不错") is None


class TestGroupEFailuresAreDistinguishable:
    """四种"没有图"必须说得出是哪一种 —— 处置完全不同。"""

    def test_e01_none_result(self):
        graph, note = project_vision_result(None)
        assert graph.root is None and "为空" in note

    def test_e02_failed_with_reason(self):
        graph, note = project_vision_result(VisionResult(success=False, error="配额耗尽"))
        assert graph.root is None and "配额耗尽" in note

    def test_e03_failed_without_reason_still_says_so(self):
        graph, note = project_vision_result(VisionResult(success=False))
        assert graph.root is None
        assert "未给出原因" in note, "失败且不说原因,是最难排查的那一种,必须点名"

    def test_e04_succeeded_but_nothing_found(self):
        graph, note = project_vision_result(_ok([], [], engine="tesseract"))
        assert graph.root is None and "tesseract" in note

    def test_e05_all_four_notes_differ(self):
        notes = {
            project_vision_result(None)[1],
            project_vision_result(VisionResult(success=False, error="配额耗尽"))[1],
            project_vision_result(VisionResult(success=False))[1],
            project_vision_result(_ok([], []))[1],
        }
        assert len(notes) == 4, "两种不同的失败给了同一句说明,等于没说"


class TestGroupFMerge:
    @staticmethod
    def _structural(label=""):
        root = UIElementNode(
            role="root",
            children=[
                UIElementNode(
                    role="button",
                    label=label,
                    clickable=True,
                    bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                )
            ],
        )
        return UIGraph(root=root, source=UISource.UIA)

    def test_f01_without_structure_returns_vision_graph(self):
        graph, _ = project_and_merge(_ok([_btn()]), None)
        assert graph.source is UISource.VISION

    def test_f02_merged_graph_records_both_sources(self):
        graph, note = project_and_merge(_ok([_btn(), _input()]), self._structural(label="发送"))
        assert graph.source is UISource.HYBRID
        assert set(graph.merged_from) == {UISource.UIA, UISource.VISION}
        assert "融合" in note

    def test_f03_vision_fills_a_missing_structural_label(self):
        """结构常缺文案,视觉常有 —— 这正是两条腿一起走的收益。"""
        graph, _ = project_and_merge(_ok([_btn()]), self._structural(label=""))
        button = next(n for n in graph.flatten() if n.role == "button" and n.source is not UISource.VISION)
        assert button.label == "发送"

    def test_f04_merge_failure_falls_back_to_structure(self, monkeypatch):
        structural = self._structural(label="发送")

        def boom(*_a, **_k):
            raise RuntimeError("merge exploded")

        monkeypatch.setattr(type(structural), "merge", boom, raising=True)
        graph, note = project_and_merge(_ok([_btn()]), structural)
        assert graph is structural, "融合失败把两边都丢了 —— 结构本来是好的"
        assert "RuntimeError" in note


class TestGroupGLivePath:
    @pytest.mark.asyncio
    async def test_g01_ui_act_accepts_a_screenshot(self, monkeypatch):
        """没有结构树的平台可以只给截图 —— 这是本阶段接线的落点。"""
        import core.vision_ui_projection as proj
        from core.routes import ui_act as mod

        async def _fake_graph(req):
            graph, note = proj.project_vision_result(_ok([_btn()]), device_id=req.device_id)
            return graph.model_dump(mode="json"), note

        monkeypatch.setattr(mod, "_graph_from_screenshot", _fake_graph)
        out = await mod.ui_act(
            mod.UIActRequest(instruction="点发送", screenshot_b64="zzz", platform="windows", execute=False)
        )
        assert out["success"] is True
        assert out["planned"]["label"] == "发送"
        assert "视觉投影" in out["vision_note"]

    @pytest.mark.asyncio
    async def test_g02_unavailable_vision_says_why(self, monkeypatch):
        from core.routes import ui_act as mod

        async def _fake_graph(req):
            return None, "视觉链路不可用(ModuleNotFoundError)"

        monkeypatch.setattr(mod, "_graph_from_screenshot", _fake_graph)
        out = await mod.ui_act(mod.UIActRequest(instruction="点发送", screenshot_b64="zzz"))
        assert out["success"] is False
        assert "不可用" in out["vision_note"], "给不出图却不说为什么,排查无从下手"

    @pytest.mark.asyncio
    async def test_g03_both_inputs_walk_on_two_legs(self, monkeypatch):
        """契约本身的立场:结构与视觉恒并存,不是谁 fallback 谁。"""
        from core.routes import ui_act as mod
        from core.schemas.ui_element import UISource

        structural = UIGraph(
            root=UIElementNode(
                role="root",
                children=[
                    UIElementNode(
                        role="button",
                        label="",  # 结构常缺文案
                        clickable=True,
                        bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                    )
                ],
            ),
            source=UISource.UIA,
        ).model_dump(mode="json")

        async def _fake_merge(req, base):
            from core.vision_ui_projection import project_and_merge

            merged, note = project_and_merge(_ok([_btn(), _input()]), UIGraph.model_validate(base))
            return merged.model_dump(mode="json"), note

        monkeypatch.setattr(mod, "_merge_screenshot_into", _fake_merge)
        out = await mod.ui_act(
            mod.UIActRequest(
                instruction="点发送", ui_graph=structural, screenshot_b64="zzz", platform="windows", execute=False
            )
        )
        assert out["success"] is True
        assert "融合" in out["vision_note"]
        assert out["planned"]["label"] == "发送", "视觉给结构补上了缺失的文案"

    @pytest.mark.asyncio
    async def test_g04_merge_failure_keeps_the_structural_graph(self, monkeypatch):
        from core.routes import ui_act as mod

        structural = UIGraph(
            root=UIElementNode(
                role="root",
                children=[
                    UIElementNode(
                        role="button", label="发送", clickable=True, bounds=UIBounds(x=1, y=1, width=10, height=10)
                    )
                ],
            ),
            source=UISource.UIA,
        ).model_dump(mode="json")

        class _Boom:
            async def understand(self, **_kw):
                raise RuntimeError("vision down")

        monkeypatch.setattr("core.vision_pipeline.VisionPipeline", _Boom)
        out = await mod.ui_act(
            mod.UIActRequest(
                instruction="点发送", ui_graph=structural, screenshot_b64="zzz", platform="windows", execute=False
            )
        )
        assert out["success"] is True
        assert out["planned"]["label"] == "发送", "融合失败把本来好的结构图也丢了"
        assert "融合跳过" in out["vision_note"]
