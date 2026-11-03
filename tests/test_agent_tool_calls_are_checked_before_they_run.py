"""派出去的 Agent 调工具,派发前也过同一道规则校验(docs/GROUNDED_AGENT_DESIGN.md §1.1 · 第四期)。

改之前:主循环(openclawd 的 ReAct)派发前校验工具在不在表里、参数合不合 schema,
不合格不派发、把原因回喂给模型;而 Agent 工厂造出来的 Agent 走 ``core/agent/react_loop.py``,
那里**什么都不校验** —— 模型编一个不存在的工具名、漏一个必填参数,也照样派下去(还可能先去问人批准)。
现在同一份 ``validate_tool_call`` 也守着这条路。

路径**不**在这里查「在不在」:每个执行体有自己的路径空间(Node_06 落在它的沙箱根下、Node_120 落在
WORKSPACE_ROOT 下、ADB / SSH 落在别的机器上),在后端这台机器上查一个路径存不存在,本身就是在猜,
会把合法的调用拦下来。文件在不在由执行体照实回答。
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tuning__set",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                "required": ["key", "value"],
            },
        },
    }
]


def _tool_call(name: str, arguments: str):
    return {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}


def _run(first_call, tools):
    from core.agent.react_loop import run_react_tool_loop

    replies = iter(
        [
            SimpleNamespace(content="", tool_calls=[first_call]),
            SimpleNamespace(content="好的。", tool_calls=None),
        ]
    )
    dispatched, fed_back = [], []

    async def llm_call(msgs):
        fed_back.append([m for m in msgs if m.get("role") == "tool"])
        return next(replies)

    async def dispatch(name, args):
        dispatched.append((name, args))
        return {"success": True}

    asyncio.run(
        run_react_tool_loop(
            messages=[{"role": "user", "content": "调一下"}],
            llm_call=llm_call,
            dispatch_tool=dispatch,
            max_iterations=3,
            tools=tools,
        )
    )
    return dispatched, fed_back


def test_a_tool_that_is_not_offered_is_not_dispatched():
    dispatched, fed_back = _run(_tool_call("tuning__sett", '{"key": "a", "value": "1"}'), _TOOLS)
    assert dispatched == []
    tool_msgs = fed_back[-1]
    assert tool_msgs and "参数校验失败·未执行" in str(tool_msgs[-1].get("content"))
    assert "不在本轮可用工具名单中" in str(tool_msgs[-1].get("content"))


def test_a_missing_required_argument_is_fed_back_not_dispatched():
    dispatched, fed_back = _run(_tool_call("tuning__set", '{"key": "a"}'), _TOOLS)
    assert dispatched == []
    assert "value" in str(fed_back[-1][-1].get("content"))


def test_a_well_formed_call_goes_through():
    dispatched, _ = _run(_tool_call("tuning__set", '{"key": "a", "value": "1"}'), _TOOLS)
    assert dispatched == [("tuning__set", {"key": "a", "value": "1"})]


def test_without_a_tool_table_nothing_changes():
    """旧调用方不传工具表:照旧直接派发(不凭空拦)。"""
    dispatched, _ = _run(_tool_call("anything__goes", "{}"), None)
    assert dispatched == [("anything__goes", {})]


def test_a_rejected_call_is_recorded_as_not_done():
    """校验没过的调用在这一轮的账上记「没做成」—— 模型随后说「做好了」会被核对线驳回。"""
    from core import live_check

    with live_check.use_turn(live_check.TurnLedger()) as ledger:
        _run(_tool_call("tuning__set", '{"key": "a"}'), _TOOLS)
    assert [(o.name, o.success) for o in ledger.outcomes()] == [("tuning__set", False)]


def test_the_agent_factory_hands_its_tool_table_to_the_loop():
    from core import agent_factory

    src = inspect.getsource(agent_factory)
    call = src[src.index("loop = await run_react_tool_loop(") :]
    call = call[: call.index(")\n")]
    assert "tools=tools" in call, "Agent 工厂要把这一轮给模型的工具表交给循环,校验才有依据"


def test_paths_are_left_to_the_executor():
    """后端不替执行体判断路径在不在(那是另一个路径空间)。"""
    from core.tool_call_validator import validate_tool_call

    tools = [
        {
            "type": "function",
            "function": {
                "name": "node__06__execute",
                "parameters": {"type": "object", "properties": {"params": {"type": "object"}}},
            },
        }
    ]
    check = validate_tool_call(
        "node__06__execute", {"params": {"action": "delete", "path": "/definitely/not/on/this/host.txt"}}, tools
    )
    assert check.valid
