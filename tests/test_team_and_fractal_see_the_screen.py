"""team / swarm / fractal 三条执行策略也要看得见屏幕。

③ 只接通了单 Agent 那条路。团队与分形策略仍然把 `multimodal_context` 丢在
`ExecutionPlanner` 里 —— 而一旦意图路由判成需要多成员协作（复杂任务恰恰更容易被
判成这类），「看这张截图帮我把设置改掉」就又回到"截图静默消失"。

这里同时钉住**两半**：
  - 送图的点：成员第一次面对用户原始任务（独立作答 / 子任务 / critic 执行者 /
    流水线第一站 / MoA 第一层 / 任务分解）；
  - **不送**的点：综合、聚合、复审、路由分类 —— 它们读的是别的 agent 产出的文本，
    跟画面上有什么无关。少了后半边，这个特性就退化成"给每一层都塞图"，成本乘以层数
    而信息不增加。
"""

from __future__ import annotations

import json

import pytest

from core.agent_team import AgentTeam, TeamMember, TeamStrategy
from core.fractal_agent import FractalExecutor, FractalTask
from core.schemas.multimodal import MultiModalContext, MultiModalImage

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


@pytest.fixture
def native_mm_on(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_MM_CHAT", "1")


def _ctx() -> MultiModalContext:
    return MultiModalContext(images=[MultiModalImage(data=PNG, mime="image/png")])


class _Resp:
    def __init__(self, content="好的"):
        self.content = content
        self.tool_calls = None
        self.provider = "fake"
        self.model = "fake-1"
        self.input_tokens = 1
        self.output_tokens = 1


class _RecordingRouter:
    """记录每一次送进 LLM 的 messages —— 这是「图有没有真到模型」的唯一判据。"""

    def __init__(self, json_reply=None):
        self.calls: list = []
        # 路由分类**不是**模型对话，是给任务打个标签。单独记，免得混进 calls 里被当成
        # 一次"送给模型的消息"—— 它按设计就不该带图，混在一起会让断言指错对象。
        self.classify_calls: list = []
        self._json_reply = json_reply

    async def chat(self, messages, **kw):
        self.calls.append(messages)
        return _Resp()

    async def chat_with_tools(self, messages, **kw):
        self.calls.append(messages)
        return _Resp()

    async def chat_json(self, messages, **kw):
        self.calls.append(messages)
        return self._json_reply or {"subtasks": []}

    def classify_task(self, messages):
        self.classify_calls.append(messages)
        return "general"

    def route(self, task_type):
        raise RuntimeError("no route in test")


def _member(name: str, role: str) -> TeamMember:
    return TeamMember(agent_id=f"a_{name}", agent_name=name, provider="fake", model="m", role_in_team=role)


def _team(strategy: TeamStrategy, router, members=None) -> AgentTeam:
    return AgentTeam(
        team_id="t1",
        strategy=strategy,
        members=members or [_member("A", "worker"), _member("B", "worker")],
        agent_factory=None,
        llm_router=router,
    )


def _has_image(msg) -> bool:
    c = msg.get("content")
    return isinstance(c, list) and any(p.get("type") == "image_url" for p in c)


def _user_msgs(calls):
    return [m for call in calls for m in call if m.get("role") == "user"]


def _text_of(msg) -> str:
    """取出用户消息的文字部分（content 可能是纯字符串，也可能是 content 数组）。"""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    return " ".join(p.get("text", "") for p in c if p.get("type") == "text")


def _is_synthesis(msg) -> bool:
    """综合那一步也是一条 user 消息，但它读的是各成员的文字产出，按设计不附图。"""
    return "各方回答" in _text_of(msg)


# ── 1. 各策略的「第一次面对原始任务」那一步必须带图 ────────────────────


@pytest.mark.parametrize(
    "strategy",
    [TeamStrategy.PARALLEL, TeamStrategy.SWARM],
)
async def test_every_member_sees_the_screen(native_mm_on, strategy):
    r = _RecordingRouter()
    await _team(strategy, r).execute("看这张截图，把这个设置改掉", {}, multimodal_context=_ctx())
    members = [m for m in _user_msgs(r.calls) if not _is_synthesis(m)]
    assert members, "一次成员调用都没发生"
    assert all(_has_image(m) for m in members), f"{strategy} 有成员没拿到画面"
    # 反面同样要钉住：综合那一步读的是文本，不该附图
    synth = [m for m in _user_msgs(r.calls) if _is_synthesis(m)]
    assert synth and not any(_has_image(m) for m in synth), "综合步骤不该附图"


async def test_pipeline_first_stage_sees_it_and_later_stages_do_not(native_mm_on):
    r = _RecordingRouter()
    await _team(TeamStrategy.PIPELINE, r).execute("看这张截图改设置", {}, multimodal_context=_ctx())
    users = _user_msgs(r.calls)
    assert len(users) >= 2, "流水线至少要跑两站才能验这条"
    assert _has_image(users[0]), "第一站没看见屏幕"
    assert not any(_has_image(m) for m in users[1:]), "后续站读的是上一站文本，不该再附图"


async def test_critic_executor_sees_it_but_the_reviewer_does_not(native_mm_on):
    r = _RecordingRouter()
    members = [_member("E", "executor"), _member("C", "critic")]
    await _team(TeamStrategy.CRITIC, r, members).execute("看截图改设置", {}, multimodal_context=_ctx())
    users = _user_msgs(r.calls)
    assert _has_image(users[0]), "执行者没看见屏幕"
    # 复审者读的是执行者的文字产出
    reviewer_msgs = [m for m in users if "待审产出" in str(m.get("content"))]
    assert reviewer_msgs, "没有触发复审"
    assert not any(_has_image(m) for m in reviewer_msgs), "复审读的是文本，不该附图"


async def test_moa_first_layer_sees_it_and_later_layers_do_not(native_mm_on):
    r = _RecordingRouter()
    await _team(TeamStrategy.MOA, r).execute("看截图改设置", {}, multimodal_context=_ctx())
    users = _user_msgs(r.calls)
    first = [m for m in users if not str(m.get("content")).startswith("原始任务")]
    later = [m for m in users if "上一层候选回答" in str(m.get("content"))]
    assert any(_has_image(m) for m in first), "第一层没看见屏幕"
    assert not any(_has_image(m) for m in later), "后续层读的是上一层候选文本，不该附图"


async def test_specialized_decomposition_and_subtasks_both_see_it(native_mm_on):
    class _R(_RecordingRouter):
        async def chat(self, messages, **kw):
            self.calls.append(messages)
            # 必须 ≥2 个：_decompose_task 对少于两个的结果判为分解失败并退回 parallel，
            # 那样就验不到子任务这条路了。
            return _Resp('[{"title": "一", "description": "点开设置"}, {"title": "二", "description": "改掉开关"}]')

    r2 = _R()
    await _team(TeamStrategy.SPECIALIZED, r2).execute("看截图改设置", {}, multimodal_context=_ctx())
    users = _user_msgs(r2.calls)
    decomp = [m for m in users if "分解" in str(m.get("content")) or "子任务" in str(m.get("content"))]
    assert decomp, "没有触发分解"
    assert _has_image(decomp[0]), "分解时没看见屏幕 —— 第一步错，后面全歪"
    # 精确匹配子任务描述本身 —— 综合那一步会把它作为引用内容再出现一次
    subtask = [m for m in users if _text_of(m).strip() == "点开设置"]
    assert subtask, "子任务没被执行"
    assert _has_image(subtask[0]), "子任务执行时没看见屏幕"
    # 反面：给子任务选模型的那次路由分类读的只是一句描述，不该附图
    classify_msgs = [m for call in r2.classify_calls for m in call]
    assert classify_msgs, "没有触发路由分类"
    assert not any(_has_image(m) for m in classify_msgs), "路由分类不该附图"


# ── 2. 回退路径不许把图弄丢 ───────────────────────────────────────────


async def test_critic_without_a_reviewer_falls_back_and_keeps_the_image(native_mm_on):
    """没有独立 critic 成员时退回 parallel —— 回退路径丢图 = 只在这种时候看不见屏幕。"""
    r = _RecordingRouter()
    members = [_member("E", "executor")]  # 没有 critic
    await _team(TeamStrategy.CRITIC, r, members).execute("看截图", {}, multimodal_context=_ctx())
    members_msgs = [m for m in _user_msgs(r.calls) if not _is_synthesis(m)]
    assert members_msgs and all(_has_image(m) for m in members_msgs)


async def test_specialized_falls_back_to_parallel_and_keeps_the_image(native_mm_on):
    class _R(_RecordingRouter):
        async def chat(self, messages, **kw):
            self.calls.append(messages)
            return _Resp("不是 JSON，分解失败")

    r = _R()
    await _team(TeamStrategy.SPECIALIZED, r).execute("看截图", {}, multimodal_context=_ctx())
    members_msgs = [m for m in _user_msgs(r.calls) if not _is_synthesis(m)]
    assert members_msgs and all(_has_image(m) for m in members_msgs), "分解失败回退到 parallel 时把图弄丢了"


# ── 3. 图像绝不能进 context（那里会被 json.dumps）────────────────────


async def test_context_is_still_json_serialisable(native_mm_on):
    """parallel 会把 context 整个 json.dumps 进 system prompt。图像若搭了 context 的车，
    这一步当场抛 TypeError —— 整条 team 路径直接崩，而不是"没看见图"。"""
    r = _RecordingRouter()
    ctx = {"soul": "s", "agents_policy": "p", "session_id": "x", "tools": []}
    await _team(TeamStrategy.PARALLEL, r).execute("看截图", ctx, multimodal_context=_ctx())
    sys_msgs = [m for call in r.calls for m in call if m.get("role") == "system"]
    assert any("上下文" in str(m.get("content")) for m in sys_msgs)
    json.dumps(ctx, ensure_ascii=False)  # 没被污染


async def test_no_image_payload_leaks_into_the_system_prompt(native_mm_on):
    r = _RecordingRouter()
    await _team(TeamStrategy.PARALLEL, r).execute("看截图", {"soul": "s"}, multimodal_context=_ctx())
    sys_msgs = [m for call in r.calls for m in call if m.get("role") == "system"]
    assert not any(PNG in str(m.get("content")) for m in sys_msgs), "base64 被当成文本塞进了 system prompt"


# ── 4. 默认行为逐字不变 ───────────────────────────────────────────────


async def test_text_only_is_unchanged(native_mm_on):
    r = _RecordingRouter()
    await _team(TeamStrategy.PARALLEL, r).execute("纯文本任务", {})
    assert all(isinstance(m.get("content"), str) for m in _user_msgs(r.calls))


async def test_flag_off_falls_back_to_text(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_MM_CHAT", "0")
    r = _RecordingRouter()
    await _team(TeamStrategy.PARALLEL, r).execute("看截图", {}, multimodal_context=_ctx())
    assert all(isinstance(m.get("content"), str) for m in _user_msgs(r.calls))


# ── 5. fractal ────────────────────────────────────────────────────────


def test_fractal_task_carries_images_outside_context():
    t = FractalTask(id="t", description="d", context={"soul": "s"}, multimodal_context=_ctx())
    assert t.multimodal_context is not None
    json.dumps(t.context, ensure_ascii=False)  # context 仍可序列化


def test_fractal_subtasks_inherit_the_screen():
    """拆出来的每一步面对的还是同一块屏幕；不继承 = 只有根任务看得见。"""
    import inspect

    from core import fractal_agent

    src = inspect.getsource(fractal_agent)
    assert (
        src.count("multimodal_context=task.multimodal_context") >= 2
    ), "LLM 分解与规则分解两条路都要继承 —— 漏一条就会出现「有时候子任务看得见、有时候看不见」"


async def test_fractal_atomic_execution_sees_the_screen(native_mm_on):
    r = _RecordingRouter()
    ex = FractalExecutor(llm_router=r, agent_factory=None, max_depth=1, max_subtasks=2)
    await ex.run("看这张截图改设置", {"soul": ""}, multimodal_context=_ctx())
    users = _user_msgs(r.calls)
    assert users, "一次模型调用都没发生"
    assert any(_has_image(m) for m in users), "分形执行全程没看见屏幕"


async def test_fractal_text_only_is_unchanged(native_mm_on):
    r = _RecordingRouter()
    ex = FractalExecutor(llm_router=r, agent_factory=None, max_depth=1, max_subtasks=2)
    await ex.run("纯文本", {"soul": ""})
    assert all(isinstance(m.get("content"), str) for m in _user_msgs(r.calls))


# ── 6. 计划层真的把字段递了下去 ───────────────────────────────────────


def test_planner_passes_the_field_to_both_team_and_fractal():
    """源码级：两处调用都必须显式传 multimodal_context，且不能塞进 context。"""
    import inspect

    from core.agent import execution_planner

    src = inspect.getsource(execution_planner)
    assert "multimodal_context=plan.multimodal_context" in src
    assert src.count("multimodal_context=plan.multimodal_context") == 2, "team 与 fractal 两处都要传"
    # context 字典里不许出现它
    for block in ("_run_team", "_run_fractal"):
        body = src[src.index(f"async def {block}") :][:4000]
        assert '"multimodal' not in body, f"{block} 把图像塞进了会被 json.dumps 的 context"
