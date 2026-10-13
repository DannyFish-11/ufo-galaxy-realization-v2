"""单 Agent 执行完,用户看到的是**模型说的话**,不是一句「任务已完成」。

真跑(本机假的 OpenAI 兼容模型):让它讲个笑话,``POST /api/v1/chat`` 回 ``"response": "任务已完成"``。
``ExecutionPlanner`` 的单 Agent 路径只读回执顶层的 ``reply`` / ``result`` / ``success`` / ``tool_calls`` /
``provider``,而 ``AgentFactory._run_agent`` 的回执把这些都放在 ``results[*]`` 里 —— 模型的回答被丢掉,
失败也算成功,工具调用与厂商记录全空。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.agent.agent_receipt import read_agent_receipt


def _ran(*leaves, status="completed"):
    return {"agent_id": "agent_x", "results": list(leaves), "status": status}


def test_the_model_answer_is_the_reply():
    r = read_agent_receipt(
        _ran({"output": "从前有座山……", "provider": "openai", "tool_calls": [{"tool": "notes__add", "success": True}]})
    )
    assert r.reply == "从前有座山……" and r.success is True
    assert r.provider == "openai" and r.tool_calls == [{"tool": "notes__add", "success": True}]


def test_a_failed_task_is_not_reported_as_done():
    r = read_agent_receipt(_ran({"task": "x", "error": "Task timed out after 300s", "error_type": "TimeoutError"}))
    assert r.success is False
    assert "Task timed out after 300s" in r.reply and "完成" not in r.reply


def test_no_model_is_not_reported_as_done():
    r = read_agent_receipt(_ran({"output": "Agent x 已处理任务（无 LLM 模式）", "simulated": True}, status="simulated"))
    assert r.success is False and "没有真正执行" in r.reply


def test_split_children_and_serial_fallback_are_read_through():
    parallel = {"strategy": "split_and_parallel", "results": [_ran({"output": "甲"}), _ran({"output": "乙"})]}
    assert read_agent_receipt(parallel).reply == "甲\n乙"
    fallback = {"strategy": "split_fallback_serial", "fallback_result": _ran({"output": "串行重跑的结果"})}
    assert read_agent_receipt(fallback).reply == "串行重跑的结果"
    timed_out = {"strategy": "split_and_parallel", "error": "Parallel execution timed out after 600s"}
    r = read_agent_receipt(timed_out)
    assert r.success is False and "timed out" in r.reply


def test_a_top_level_reply_still_wins():
    """别的执行器 / 测试桩直接给顶层 reply 的,照旧用它。"""
    r = read_agent_receipt({"success": True, "reply": "分析完成", "results": [{"output": "别的"}]})
    assert r.reply == "分析完成" and r.success is True


@pytest.mark.asyncio
async def test_the_planner_hands_the_real_factory_answer_to_the_user():
    """走真的 ``AgentFactory.execute_agent_task`` → ``_run_agent``,只把单个任务的执行换成一句固定回答。"""
    from core.agent.execution_planner import ExecutionPlan, ExecutionPlanner
    from core.agent.intent_router import IntentMode, IntentResult
    from core.agent_factory import AgentFactory

    factory = AgentFactory(llm_router=None)
    single = AsyncMock(return_value={"task": "x", "output": "好的,明天下午三点开会,已记下。", "provider": "openai"})
    with (
        patch("core.agent_factory.get_agent_factory", return_value=factory),
        patch.object(factory, "_execute_single_task", single),
    ):
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="记事")
        plan = ExecutionPlan(message="帮我记一下明天下午三点开会", intent=intent)
        result = await ExecutionPlanner(llm_router=None)._run_single_agent(plan, [], [])

    assert single.await_count == 1
    assert result.reply == "好的,明天下午三点开会,已记下。"
    assert result.success is True and result.chosen_providers == ["openai"]


@pytest.mark.asyncio
async def test_the_reply_names_the_model_that_actually_wrote_it():
    """回答里报的型号得是真正写出回答的那个。

    真跑:Agent 生成走「质量第一」选了 gpt-6-astra,回答里的 ``model`` 却是 gpt-5.6 —— 回执里没有型号,
    上层回落到路由器的默认型号。单个任务的结果现在带上 ``model``。
    """
    from types import SimpleNamespace

    from core.agent_factory import AgentFactory

    class _Router:
        async def chat_with_tools(self, messages=None, tools=None, **_kw):
            return SimpleNamespace(content="写好了", provider="openai", model="gpt-6-astra", tool_calls=None)

    factory = AgentFactory(llm_router=_Router())
    agent = factory.create_from_template("coordinator")
    with patch("core.openclawd.get_openclawd", side_effect=RuntimeError("测试里不起主体")):
        receipt = read_agent_receipt(await factory.execute_agent_task(agent.id, {"description": "写一句话"}))
    assert receipt.reply == "写好了"
    assert receipt.provider == "openai" and receipt.model == "gpt-6-astra"


def test_task_memory_keeps_what_the_user_said_not_the_machine_annotations(tmp_path):
    """真跑:每条任务摘要的 ``task`` 后面都挂着 ``[Multimodal context: …]`` 与 ``[desktop_context_strategy …]``。
    经验制导按 BM25 拿它排相似任务,面板也会把它当「做过什么」列出来 —— 存的该是用户说的话。"""
    from core.task_memory import TaskMemory

    said = "帮我记一下明天下午三点开会\n[真的方括号] 用户自己写的"
    sent = (
        said + "\n\n[Multimodal context: 1 image(s) [webcam], device=unknown]\n\n"
        "[desktop_context_strategy presence_transition=manifest_to_liminal; sampling_intensity=moderate]"
    )
    mem = TaskMemory(data_dir=str(tmp_path))
    assert mem.record_task(sent, result_summary="记下了").task == said
    assert TaskMemory(data_dir=str(tmp_path)).get_recent_summaries(1)[0].task == said
