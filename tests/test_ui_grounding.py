"""tests/test_ui_grounding.py
================================

结构化 grounding 脑:意图→控件、模型回复→控件、结构优先/视觉兜底切换。
"""
from __future__ import annotations

from core.schemas.ui_element import (
    UIActionKind,
    UIBounds,
    UIElementNode,
    UIGraph,
    UISource,
)
from core.ui_grounding import (
    GroundingStrategy,
    build_grounding_prompt,
    extract_target,
    extract_text_to_type,
    infer_action,
    parse_model_action,
    resolve_target,
)


def _wechat() -> UIGraph:
    return UIGraph(root=UIElementNode(role="window", label="微信", children=[
        UIElementNode(role="edit", label="输入消息", editable=True, clickable=True,
                      bounds=UIBounds(x=60, y=2010, width=1000, height=80),
                      actions=[UIActionKind.SET_TEXT]),
        UIElementNode(role="button", label="发送", clickable=True,
                      bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                      actions=[UIActionKind.TAP]),
        UIElementNode(role="button", label="发送文件", clickable=True,
                      bounds=UIBounds(x=1000, y=2020, width=120, height=80)),
    ]), source=UISource.ANDROID_A11Y, app="com.tencent.mm")


class TestInferAction:
    def test_tap_default(self):
        assert infer_action("点发送") is UIActionKind.TAP

    def test_type(self):
        assert infer_action("在输入框输入你好") is UIActionKind.SET_TEXT

    def test_scroll_and_longpress(self):
        assert infer_action("向下滑动") is UIActionKind.SCROLL
        assert infer_action("长按消息") is UIActionKind.LONG_PRESS


class TestExtract:
    def test_extract_quoted_target(self):
        assert extract_target("点「发送」按钮") == "发送"

    def test_extract_after_verb(self):
        assert "发送" in extract_target("点发送")

    def test_extract_text_to_type_quoted(self):
        assert extract_text_to_type('输入「你好世界」') == "你好世界"

    def test_extract_text_to_type_colon(self):
        assert extract_text_to_type("输入:今天天气不错") == "今天天气不错"


class TestResolveTargetStructural:
    def test_exact_label_wins(self):
        r = resolve_target(_wechat(), "点「发送」")
        assert r.ok and r.node.label == "发送"
        assert r.strategy is GroundingStrategy.LABEL_EXACT
        assert r.action is UIActionKind.TAP
        assert r.target_center() == (1240, 2060)

    def test_set_text_carries_text(self):
        r = resolve_target(_wechat(), '在「输入消息」输入「你好」')
        assert r.ok and r.node.role == "edit"
        assert r.action is UIActionKind.SET_TEXT and r.text == "你好"

    def test_ambiguous_substring_lowers_confidence(self):
        # "发送" 是 "发送" 和 "发送文件" 的子串 → 精确匹配"发送"仍应命中精确档
        r = resolve_target(_wechat(), "点发送文件")
        assert r.ok and r.node.label == "发送文件"

    def test_vision_fallback_when_absent(self):
        r = resolve_target(_wechat(), "点「悬浮球」")
        assert not r.ok and r.strategy is GroundingStrategy.VISION_FALLBACK

    def test_no_tree_is_vision_fallback(self):
        empty = UIGraph(root=None, source=UISource.VISION)
        r = resolve_target(empty, "点发送")
        assert r.strategy is GroundingStrategy.VISION_FALLBACK


class TestParseModelAction:
    def test_index_ref_resolves_to_node(self):
        g = _wechat()
        # flatten 顺序: [0]window [1]edit [2]发送 [3]发送文件
        r = parse_model_action("点 [2]", g)
        assert r.ok and r.node.label == "发送"
        assert r.strategy is GroundingStrategy.INDEX_REF

    def test_index_ref_with_text(self):
        g = _wechat()
        r = parse_model_action('[1] 文本="你好"', g)
        assert r.ok and r.node.role == "edit" and r.action is UIActionKind.SET_TEXT
        assert r.text == "你好"

    def test_out_of_range_index_falls_back_to_name(self):
        g = _wechat()
        r = parse_model_action("[99] 发送", g)  # 越界 → 回退按名
        assert r.ok and r.node.label == "发送"

    def test_no_index_uses_name_resolution(self):
        g = _wechat()
        r = parse_model_action("点发送", g)
        assert r.ok and r.node.label == "发送"


class TestPromptComposition:
    def test_prompt_has_structure_and_instruction(self):
        p = build_grounding_prompt(_wechat(), "把消息发出去")
        assert "[2] button" in p and "把消息发出去" in p and "[n]" in p
