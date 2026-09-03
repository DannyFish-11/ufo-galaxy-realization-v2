"""执行路径（task_execute / hybrid）上的图像必须原生送达模型。

背景：CHAT_ONLY 分支一路把 ``multimodal_context`` 带到 ``_fallback_chat``，图像能走
OpenAI content 数组。但 ``task_execute`` / ``hybrid`` 组装 ``ExecutionPlan`` 时压根没有
这个字段——恰恰是「看这张截图，帮我把这个设置改掉」这类最需要看图的请求，图像在组装
计划的那一行就静默消失了。

本文件按真实调用链验证（不是 mock 掉自己刚写的那层）：
  kernel 组装 ExecutionPlan → _run_single_agent 塞进 task dict →
  agent_factory._execute_single_task 摘出来 → build_user_message_content → LLM messages
"""

from __future__ import annotations

import json

import pytest

from core.agent.execution_planner import ExecutionPlan
from core.agent.intent_router import IntentResult
from core.agent.multimodal_messages import MULTIMODAL_TASK_KEY, build_user_message_content
from core.schemas.multimodal import MultiModalContext, MultiModalImage

PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _ctx() -> MultiModalContext:
    return MultiModalContext(images=[MultiModalImage(data=PNG_1PX, mime="image/png")])


@pytest.fixture
def native_mm_on(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_MM_CHAT", "1")


# ── 1. ExecutionPlan 真的能承载图像 ────────────────────────────────────


def test_execution_plan_carries_multimodal_context():
    plan = ExecutionPlan(message="看这张截图", intent=IntentResult(), multimodal_context=_ctx())
    assert plan.multimodal_context is not None
    assert len(plan.multimodal_context.images) == 1


def test_execution_plan_multimodal_context_defaults_to_none():
    """纯文本调用方不写这个字段也必须能构造——默认必须是 None 而不是必填。"""
    assert ExecutionPlan(message="hi", intent=IntentResult()).multimodal_context is None


# ── 2. kernel 组装 ExecutionPlan 时确实传了这个字段 ─────────────────────


def test_kernel_passes_multimodal_context_into_execution_plan():
    """源码级检查：kernel 里构造 ExecutionPlan 的那处必须带 multimodal_context。

    走源码是因为 _process 前面串了意图路由 / SOUL 加载 / CanonicalTask，端到端跑一遍
    需要一整套 LLM 桩，收益不如直接钉住这一行不被人删掉。
    """
    import inspect

    from core.agent import kernel as kernel_mod

    src = inspect.getsource(kernel_mod)
    idx = src.index("plan = ExecutionPlan(")
    block = src[idx : src.index("\n        )", idx)]
    assert "multimodal_context=multimodal_context" in block, "kernel 组装 ExecutionPlan 时又把图像丢了"


# ── 3. _run_single_agent 把图像放进 task dict 的约定键 ──────────────────


@pytest.mark.asyncio
async def test_single_agent_puts_images_into_task_dict(monkeypatch):
    from core.agent import execution_planner as ep

    captured: dict = {}

    class _FakeAgent:
        id = "agent_x"

        class config:  # noqa: D106
            name = "tester"

    class _FakeFactory:
        def create_from_template(self, name):
            return _FakeAgent()

        async def execute_agent_task(self, agent_id, task):
            captured.update(task)
            return {"success": True, "reply": "done"}

    monkeypatch.setattr("core.agent_factory.get_agent_factory", lambda *a, **k: _FakeFactory())

    planner = ep.ExecutionPlanner(None)  # llm_router=None → 走模板兜底，不打网络
    plan = ExecutionPlan(message="看这张截图", intent=IntentResult(), multimodal_context=_ctx())
    await planner._run_single_agent(plan, [], [])

    assert MULTIMODAL_TASK_KEY in captured, "图像没被放进 task dict"
    assert captured[MULTIMODAL_TASK_KEY].images[0].data == PNG_1PX


@pytest.mark.asyncio
async def test_single_agent_omits_key_when_no_images(monkeypatch):
    """纯文本请求不应该凭空多出一个 None 键——消费端 json.dumps 的输入要保持原样。"""
    from core.agent import execution_planner as ep

    captured: dict = {}

    class _FakeAgent:
        id = "agent_x"

        class config:  # noqa: D106
            name = "tester"

    class _FakeFactory:
        def create_from_template(self, name):
            return _FakeAgent()

        async def execute_agent_task(self, agent_id, task):
            captured.update(task)
            return {"success": True, "reply": "done"}

    monkeypatch.setattr("core.agent_factory.get_agent_factory", lambda *a, **k: _FakeFactory())

    planner = ep.ExecutionPlanner(None)
    await planner._run_single_agent(ExecutionPlan(message="纯文本", intent=IntentResult()), [], [])
    assert MULTIMODAL_TASK_KEY not in captured


# ── 4. agent_factory 真的把图像投给了 LLM ─────────────────────────────


class _Resp:
    content = "好的"
    tool_calls = None
    provider = "fake"
    input_tokens = 1
    output_tokens = 1


class _RecordingRouter:
    """记录送进 LLM 的 messages —— 这是「图像有没有真到模型」的唯一判据。"""

    def __init__(self):
        self.messages = None

    async def chat_with_tools(self, messages, tools=None, task_type=""):
        self.messages = messages
        return _Resp()


async def _run_task_through_factory(task: dict):
    from core.agent_factory import AgentFactory

    router = _RecordingRouter()
    factory = AgentFactory(llm_router=router)
    factory._llm_circuit_breaker = None
    agent = factory.create_from_template("coordinator")
    result = await factory._execute_single_task(agent, task)
    return router, result


@pytest.mark.asyncio
async def test_images_arrive_as_openai_content_array(native_mm_on):
    router, _ = await _run_task_through_factory({"description": "看这张截图", MULTIMODAL_TASK_KEY: _ctx()})
    user_msg = router.messages[-1]
    assert isinstance(user_msg["content"], list), "图像没走 content 数组，仍然只是文本"
    kinds = [part["type"] for part in user_msg["content"]]
    assert kinds == ["text", "image_url"]
    assert user_msg["content"][1]["image_url"]["url"] == f"data:image/png;base64,{PNG_1PX}"


@pytest.mark.asyncio
async def test_multimodal_key_never_lands_in_the_json_text(native_mm_on):
    """约定键本身是内部管道，不能被 json.dumps 成用户可见的任务描述。"""
    router, _ = await _run_task_through_factory({"description": "看这张截图", MULTIMODAL_TASK_KEY: _ctx()})
    text_part = router.messages[-1]["content"][0]["text"]
    assert MULTIMODAL_TASK_KEY not in text_part
    assert json.loads(text_part) == {"description": "看这张截图"}


@pytest.mark.asyncio
async def test_text_only_task_is_unchanged(native_mm_on):
    """没有图像时必须逐字保持旧行为：纯字符串 content。"""
    router, _ = await _run_task_through_factory({"description": "纯文本"})
    assert router.messages[-1]["content"] == json.dumps({"description": "纯文本"}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_flag_off_falls_back_to_text(monkeypatch):
    """默认关闭：Gemini 等适配器会对 content 做字符串拼接，收到数组会崩。"""
    monkeypatch.setenv("GALAXY_NATIVE_MM_CHAT", "0")
    router, _ = await _run_task_through_factory({"description": "看这张截图", MULTIMODAL_TASK_KEY: _ctx()})
    assert isinstance(router.messages[-1]["content"], str)


@pytest.mark.asyncio
async def test_flag_unset_defaults_to_off(monkeypatch):
    monkeypatch.delenv("GALAXY_NATIVE_MM_CHAT", raising=False)
    router, _ = await _run_task_through_factory({"description": "看这张截图", MULTIMODAL_TASK_KEY: _ctx()})
    assert isinstance(router.messages[-1]["content"], str)


# ── 5. 回显不能把 base64 原样吐回响应 ─────────────────────────────────


def test_task_echo_strips_media_payload():
    from core.agent_factory import _task_echo

    echoed = _task_echo({"description": "看图", MULTIMODAL_TASK_KEY: _ctx()})
    assert echoed[MULTIMODAL_TASK_KEY] == "<multimodal payload stripped>"
    assert PNG_1PX not in json.dumps(echoed, ensure_ascii=False)


def test_task_echo_is_identity_for_text_only_tasks():
    from core.agent_factory import _task_echo

    task = {"description": "纯文本"}
    assert _task_echo(task) is task


def test_task_echo_does_not_mutate_the_original():
    from core.agent_factory import _task_echo

    ctx = _ctx()
    task = {"description": "看图", MULTIMODAL_TASK_KEY: ctx}
    _task_echo(task)
    assert task[MULTIMODAL_TASK_KEY] is ctx, "回显不能就地改掉还要送给模型的那份 task"


@pytest.mark.asyncio
async def test_result_payload_is_json_serializable_with_images(native_mm_on):
    """带图任务的返回值要能过 json.dumps —— 否则 API 层序列化响应时当场炸。"""
    _, result = await _run_task_through_factory({"description": "看这张截图", MULTIMODAL_TASK_KEY: _ctx()})
    json.dumps(result, ensure_ascii=False, default=str)
    assert PNG_1PX not in json.dumps(result, ensure_ascii=False, default=str)


# ── 6. 已知边界要说清楚，而不是假装覆盖了 ──────────────────────────────


def test_team_path_documented_as_not_yet_covered():
    """team / swarm 路径尚未消费图像，这一点必须写在字段文档里而不是留给别人踩。"""
    import inspect

    from core.agent.execution_planner import ExecutionPlan as _EP

    # pydantic 不收集字段下方的裸 docstring，只能退回源码检查
    src = inspect.getsource(_EP)
    assert "team" in src and "swarm" in src, "多模态字段必须标注 team/swarm 尚未覆盖"


def test_build_user_message_content_handles_none_context():
    assert build_user_message_content("hi", None) == "hi"
