"""Agent 调了工具,任务照样有回答 —— 不是一段 pydantic 报错。

第 8 轮真跑:对着一个按剧本回话的本机模型说「帮我调一下那个参数」,走的是任务路径(Agent 工厂建一个 Agent 去做),
Agent 调了 ``tuning__set``(参数不存在,工具如实失败),回到面板上的却是::

    任务执行失败:1 validation error for ToolCallRecord
    result
      Input should be a valid dictionary [type=dict_type, input_value='GALAXY_NOT_A_REAL_KNOB ...']

执行规划器把 Agent 回执里的工具调用收成自己的 ``ToolCallRecord`` 时,按自己的字段名去读那边的记录:
那边(``core.schemas.tool_call.ToolCallRecord``)叫 ``tool_name`` / ``status``、``result`` 是截断后的文字,
这边读 ``tool`` / ``success``、``result`` 要字典 —— 工具名一律空串、失败一律读成成功,只要有一次工具调用就校验失败。
"""

from __future__ import annotations

from core.agent.execution_planner import ToolCallRecord as PlannerRecord
from core.schemas.tool_call import ToolCallRecord as AgentRecord
from core.schemas.tool_call import ToolCallStatus


def _agent_record(**kw):
    base = dict(tool_name="tuning__set", layer=AgentRecord.classify_layer("tuning__set"), arguments={"key": "X"})
    base.update(kw)
    return AgentRecord(**base).model_dump()


def test_a_failed_tool_call_is_read_as_failed_with_its_name():
    rec = PlannerRecord.from_agent(
        _agent_record(result="X 不在可调的参数里", status=ToolCallStatus.ERROR, error="X 不在可调的参数里")
    )
    assert rec.tool == "tuning__set" and rec.success is False and "不在可调" in rec.error
    assert rec.result == "X 不在可调的参数里"


def test_a_successful_tool_call_with_a_text_result_does_not_blow_up():
    rec = PlannerRecord.from_agent(_agent_record(result="已调好", status=ToolCallStatus.SUCCESS))
    assert rec.success is True and rec.result == "已调好" and rec.arguments == {"key": "X"}


def test_records_already_in_the_planner_shape_still_read_the_same():
    rec = PlannerRecord.from_agent({"tool": "t", "arguments": {}, "result": {"a": 1}, "success": False, "error": "e"})
    assert rec.tool == "t" and rec.success is False and rec.result == {"a": 1}
