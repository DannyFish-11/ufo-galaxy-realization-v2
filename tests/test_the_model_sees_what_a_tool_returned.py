"""工具返回了什么,模型就看到什么 —— 摊在顶层的返回体不再变成一段空白。

推理循环原来只把 ``result``(失败时 ``error``)回喂给模型。可 ``devices__list`` 的设备卡在 ``members``、
``devices__invite`` 的配对码在 ``code`` / ``tell_user``、调参的结果在 ``tell_user`` —— 都在顶层。于是模型
看有哪些设备看到的是空的,邀请一块手表拿不到配对码,只能编或者说「没成功」。三个推理循环
(``OpenClawd._react_loop``、``core/agent/react_loop``、``agent_factory`` 的记录)共用一个 ``tool_result_text``。
"""

from __future__ import annotations

import json

from core.react_progress import tool_result_text


def test_the_result_field_is_still_what_the_model_reads():
    assert tool_result_text({"success": True, "result": {"bpm": 72}}) == "{'bpm': 72}"
    assert tool_result_text({"success": True, "result": "写好了", "extra": 1}) == "写好了"


def test_a_failure_still_reads_as_its_reason():
    assert tool_result_text({"success": False, "error": "手机上没给日历权限"}) == "手机上没给日历权限"


def test_a_pairing_code_given_at_the_top_level_reaches_the_model():
    text = tool_result_text(
        {
            "success": True,
            "code": "482913",
            "tell_user": "在手表的 Galaxy App 接入页输入配对码 482913",
            "_latency_ms": 3.2,
        }
    )
    assert json.loads(text) == {"code": "482913", "tell_user": "在手表的 Galaxy App 接入页输入配对码 482913"}


def test_the_device_cards_reach_the_model_in_readable_chinese():
    text = tool_result_text(
        {"success": True, "members": [{"device_id": "w1", "name": "手表"}], "summary": {"members": 1}}
    )
    assert "手表" in text and "w1" in text


def test_nothing_to_say_is_still_nothing_and_a_bare_value_is_itself():
    assert tool_result_text({"success": True}) == ""
    assert tool_result_text("ok") == "ok"


async def test_the_agents_loop_hands_the_invite_code_to_the_model():
    from core.multi_llm_router import LLMResponse
    from core.openclawd import OpenClawd

    seen = []

    class _Model:
        async def chat_with_tools(self, messages, tools=None, task_type=None, max_tokens=4096, **kwargs):
            seen.append([dict(m) for m in messages])
            if len(seen) == 1:
                call = {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "devices__invite", "arguments": '{"kind": "watch"}'},
                }
                return LLMResponse(
                    content="",
                    provider="p",
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=1.0,
                    tool_calls=[call],
                )
            return LLMResponse(content="好了", provider="p", model="m", input_tokens=1, output_tokens=1, latency_ms=1.0)

    async def invite(name, args):
        return {
            "success": True,
            "human_step": "confirm_on_device",
            "code": "482913",
            "tell_user": "在手表的 Galaxy App 接入页输入配对码 482913",
        }

    clawd = OpenClawd.__new__(OpenClawd)
    clawd._get_router = lambda: _Model()
    clawd._dispatch_tool_call = invite
    await clawd._react_loop(
        [{"role": "user", "content": "把我的手表接进来"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "devices__invite",
                    "parameters": {"type": "object", "properties": {"kind": {"type": "string"}}},
                },
            }
        ],
    )
    tool_msgs = [m for m in seen[1] if m.get("role") == "tool"]
    assert tool_msgs and "482913" in tool_msgs[-1]["content"], tool_msgs
