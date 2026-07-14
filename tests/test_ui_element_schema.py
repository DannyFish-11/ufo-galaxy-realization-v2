"""tests/test_ui_element_schema.py
===================================

结构化 UI 节点契约(AG-UI)。核心不变量:
  - 结构树渲染成紧凑可引用的提示词(取代自由提示词)。
  - 可交互控件过滤、按名查找(交互优先)。
  - 结构 + 视觉融合成混合图:重叠→补语义不新增;缺失→视觉兜底新增。
  - JSON 往返无损(供协议/DAG 携带)。
"""

from __future__ import annotations

from core.schemas.ui_element import (
    UIActionKind,
    UIBounds,
    UIElementNode,
    UIGraph,
    UISource,
)


def _wechat_tree() -> UIElementNode:
    return UIElementNode(
        role="window",
        label="微信",
        package="com.tencent.mm",
        children=[
            UIElementNode(
                role="edit",
                label="输入消息",
                editable=True,
                clickable=True,
                bounds=UIBounds(x=60, y=2010, width=1000, height=80),
                actions=[UIActionKind.SET_TEXT],
            ),
            UIElementNode(
                role="button",
                label="发送",
                clickable=True,
                bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                actions=[UIActionKind.TAP],
            ),
            UIElementNode(role="text", label="装饰文本"),  # 非交互
        ],
    )


class TestTraversalQuery:
    def test_flatten_covers_all(self):
        assert len(_wechat_tree().flatten()) == 4

    def test_interactive_filters_decoration(self):
        labels = [n.label for n in _wechat_tree().interactive()]
        assert labels == ["输入消息", "发送"]

    def test_find_by_label_prefers_interactive(self):
        n = _wechat_tree().find_by_label("发送")
        assert n is not None and n.clickable and n.bounds.center() == (1240, 2060)

    def test_find_by_label_substring_and_exact(self):
        t = _wechat_tree()
        assert t.find_by_label("输入") is not None
        assert t.find_by_label("输入", exact=True) is None  # 全名是"输入消息"

    def test_disabled_hidden_not_interactive(self):
        n = UIElementNode(role="button", label="x", clickable=True, enabled=False)
        assert not n.is_interactive()


class TestToPrompt:
    def test_renders_indexed_structured_lines(self):
        out = _wechat_tree().to_prompt()
        lines = out.splitlines()
        assert lines[0].startswith("[0] window")
        assert '[2] button "发送"' in out
        assert "{clickable}" in out
        # 每个控件有稳定序号锚
        assert all(f"[{i}]" in out for i in range(4))

    def test_states_are_explicit(self):
        n = UIElementNode(role="checkbox", label="记住我", checked=False, clickable=True)
        assert "unchecked" in n.to_prompt()
        n2 = n.model_copy(update={"checked": True})
        assert "checked" in n2.to_prompt() and "unchecked" not in n2.to_prompt()

    def test_vision_confidence_flagged(self):
        n = UIElementNode(role="button", label="悬浮球", source=UISource.VISION, confidence=0.82, clickable=True)
        assert "vision:0.82" in n.to_prompt()


class TestGraphMergeStructureAndVision:
    def test_vision_adds_missing_control(self):
        g = UIGraph(root=_wechat_tree(), source=UISource.ANDROID_A11Y)
        vg = UIGraph(
            root=UIElementNode(
                role="button",
                label="悬浮球",
                source=UISource.VISION,
                confidence=0.82,
                clickable=True,
                bounds=UIBounds(x=1150, y=1000, width=100, height=100),
            ),
            source=UISource.VISION,
        )
        merged = g.merge(vg)
        assert merged.source is UISource.HYBRID
        assert merged.vision_added == 1
        assert merged.find_by_label("悬浮球") is not None

    def test_overlapping_vision_dedupes_and_supplies_label(self):
        # 结构里有个没文案的按钮,视觉框与它高度重叠 → 补 label,不新增
        struct = UIElementNode(
            role="window",
            children=[
                UIElementNode(
                    role="button", label="", clickable=True, bounds=UIBounds(x=1180, y=2020, width=120, height=80)
                ),
            ],
        )
        g = UIGraph(root=struct, source=UISource.UIA)
        vg = UIGraph(
            root=UIElementNode(
                role="button",
                label="发送",
                source=UISource.VISION,
                confidence=0.9,
                bounds=UIBounds(x=1182, y=2022, width=118, height=78),
            ),
            source=UISource.VISION,
        )
        merged = g.merge(vg)
        assert merged.vision_added == 0
        btn = merged.root.find(lambda n: n.role == "button")
        assert btn.label == "发送" and btn.source is UISource.HYBRID

    def test_merge_does_not_mutate_original(self):
        g = UIGraph(root=_wechat_tree(), source=UISource.ANDROID_A11Y)
        before = len(g.flatten())
        g.merge(
            UIGraph(
                root=UIElementNode(
                    role="button", label="x", clickable=True, bounds=UIBounds(x=1, y=1, width=9, height=9)
                ),
                source=UISource.VISION,
            )
        )
        assert len(g.flatten()) == before  # 原图不变


class TestBoundsIoU:
    def test_identical_iou_one(self):
        b = UIBounds(x=0, y=0, width=10, height=10)
        assert b.iou(UIBounds(x=0, y=0, width=10, height=10)) == 1.0

    def test_disjoint_iou_zero(self):
        assert UIBounds(x=0, y=0, width=10, height=10).iou(UIBounds(x=100, y=100, width=10, height=10)) == 0.0


class TestJsonRoundtrip:
    def test_graph_roundtrip_lossless(self):
        g = UIGraph(
            root=_wechat_tree(),
            source=UISource.ANDROID_A11Y,
            app="com.tencent.mm",
            screen_width=1280,
            screen_height=2200,
        )
        g2 = UIGraph.model_validate(g.model_dump())
        assert g2.find_by_label("发送").bounds.center() == (1240, 2060)
        assert g2.to_prompt() == g.to_prompt()
