"""tests/test_aip_v3_ui_graph.py
==================================

AIP v3 TASK_ASSIGN / TASK_RESULT 携带结构化界面态(AG-UI ui_graph)。
让 DAG 任务节点带着结构化控件图流转——执行侧结构优先 grounding、闭环校验。
"""

from __future__ import annotations

from core.schemas.aip_v3 import TaskAssignMsg, TaskResultMsg
from core.schemas.ui_element import (
    UIActionKind,
    UIBounds,
    UIElementNode,
    UIGraph,
    UISource,
)


def _graph() -> UIGraph:
    return UIGraph(
        root=UIElementNode(
            role="window",
            label="微信",
            children=[
                UIElementNode(
                    role="button",
                    label="发送",
                    clickable=True,
                    actions=[UIActionKind.TAP],
                    bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                ),
            ],
        ),
        source=UISource.ANDROID_A11Y,
        app="com.tencent.mm",
    )


class TestTaskAssignUiGraph:
    def test_default_is_none(self):
        assert TaskAssignMsg(action="tap").ui_graph is None

    def test_carries_ui_graph_roundtrip(self):
        m = TaskAssignMsg(action="tap", params={"target": "发送"}, ui_graph=_graph().model_dump())
        m2 = TaskAssignMsg.model_validate(m.model_dump())
        g = UIGraph.model_validate(m2.ui_graph)
        assert g.find_by_label("发送").bounds.center() == (1240, 2060)
        assert g.source is UISource.ANDROID_A11Y

    def test_prompt_survives_transport(self):
        original = _graph()
        m = TaskAssignMsg(action="tap", ui_graph=original.model_dump())
        restored = UIGraph.model_validate(TaskAssignMsg.model_validate(m.model_dump()).ui_graph)
        assert restored.to_prompt() == original.to_prompt()


class TestTaskResultUiGraph:
    def test_result_carries_post_action_state(self):
        r = TaskResultMsg(status="completed", ui_graph=_graph().model_dump())
        g = UIGraph.model_validate(TaskResultMsg.model_validate(r.model_dump()).ui_graph)
        assert g.app == "com.tencent.mm"

    def test_before_after_comparable_for_closed_loop(self):
        before = _graph().model_dump()
        after = _graph()
        # 模拟动作后界面多了个"已发送"提示
        after.root.children.append(UIElementNode(role="text", label="已发送"))
        assign = TaskAssignMsg(action="tap", ui_graph=before)
        result = TaskResultMsg(status="completed", ui_graph=after.model_dump())
        gb = UIGraph.model_validate(assign.ui_graph)
        ga = UIGraph.model_validate(result.ui_graph)
        assert gb.find_by_label("已发送") is None
        assert ga.find_by_label("已发送") is not None  # 闭环:动作确实改变了界面
