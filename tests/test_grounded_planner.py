"""tests/test_grounded_planner.py
===================================

一步规划器:结构确定命中→直接动作;点不准→needs_model+提示;落成 TASK_ASSIGN。
"""

from __future__ import annotations

from core.grounded_planner import PlannedAction, plan, to_task_assign
from core.schemas.aip_v3 import TaskAssignMsg
from core.schemas.ui_element import (
    UIActionKind,
    UIBounds,
    UIElementNode,
    UIGraph,
    UISource,
)
from core.ui_grounding import GroundingStrategy


def _wechat() -> UIGraph:
    return UIGraph(
        root=UIElementNode(
            role="window",
            label="微信",
            children=[
                UIElementNode(
                    role="edit",
                    label="输入消息",
                    editable=True,
                    clickable=True,
                    node_id="0.0",
                    bounds=UIBounds(x=60, y=2010, width=1000, height=80),
                    actions=[UIActionKind.SET_TEXT],
                ),
                UIElementNode(
                    role="button",
                    label="发送",
                    clickable=True,
                    node_id="0.1",
                    bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                    actions=[UIActionKind.TAP],
                ),
            ],
        ),
        source=UISource.ANDROID_A11Y,
        app="com.tencent.mm",
    )


class TestPlanStructuralHit:
    def test_direct_action_when_structure_hits(self):
        p = plan(_wechat(), "点「发送」")
        assert not p.needs_model and p.executable
        assert p.action is UIActionKind.TAP
        assert p.node_id == "0.1" and p.label == "发送"
        assert p.coordinates == [1240, 2060]
        assert p.strategy is GroundingStrategy.LABEL_EXACT

    def test_set_text_carries_text_and_target(self):
        p = plan(_wechat(), "在「输入消息」输入「你好」")
        assert p.action is UIActionKind.SET_TEXT and p.text == "你好"
        assert p.node_id == "0.0" and not p.needs_model


class TestPlanDeferToModel:
    def test_absent_target_needs_model_with_prompt(self):
        p = plan(_wechat(), "点「悬浮球」")
        assert p.needs_model and not p.executable
        assert p.strategy is GroundingStrategy.DEFER_TO_MODEL
        # 附上与截图一同发给模型的结构化辅助提示
        assert "[2] button" in p.grounding_prompt and "悬浮球" in p.grounding_prompt

    def test_model_reply_resolves_after_defer(self):
        g = _wechat()
        p1 = plan(g, "点那个发送东西的按钮")  # 结构可能点不准
        # 模型看着截图+结构回了序号
        p2 = plan(g, "", model_reply="[2]")
        assert not p2.needs_model and p2.node_id == "0.1" and p2.coordinates == [1240, 2060]


class TestToTaskAssign:
    def test_emits_task_assign_with_ui_graph(self):
        g = _wechat()
        p = plan(g, "点「发送」")
        msg = to_task_assign(p, g, goal="发消息")
        assert isinstance(msg, TaskAssignMsg)
        assert msg.action == "tap"
        assert msg.params["node_id"] == "0.1"
        assert msg.params["coordinates"] == [1240, 2060]
        assert msg.goal == "发消息"
        # 携带结构化界面态,可往返
        g2 = UIGraph.model_validate(msg.ui_graph)
        assert g2.find_by_label("发送") is not None

    def test_set_text_params(self):
        g = _wechat()
        p = plan(g, "在「输入消息」输入「你好」")
        msg = to_task_assign(p, g)
        assert msg.action == "set_text" and msg.params["text"] == "你好"
