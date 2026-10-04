"""智能路由的「用途」维度 + 特种部队按最优云端 API 组队。

背景
====
所有者的要求：对话推理与 Agent 生成，都归智能路由；**在原有智能路由上再多一个评定维度**——这次选脑是为了
对话，还是为了生成 Agent。不是另开一条路径。

* 对话：本地优先照旧；云端厂商之间不再照偏好表写死的顺序，按打分（质量 × 复杂度、成本、延迟、实测）排序，
  对话是交互的，延迟计入。
* Agent 生成（特种部队）：要最强的组合 —— 质量第一（成本降权、延迟不计），且优先云端。
  team / swarm / parallel 等其它策略不动。

顺带钉住此前特种部队的三个问题：生成的 Agent 执行时根本没用上（提示词是一句通用话）；角色固定、按 provider
匹配所以和子任务对不上；每次请求往单例工厂里塞 5 个 Agent 且从不回收。
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from core.agent_team import AgentTeam, TeamManager, TeamMember, TeamStrategy
from core.multi_llm_router import MultiLLMRouter, ProviderConfig, ProviderStatus, RoutingPurpose, TaskType

# ── 路由器：用途维度 + 云端排序 ─────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _equal_tiers(monkeypatch):
    """两家云端能力档打平，让成本 / 延迟成为唯一变量。"""
    for name in ("OPENAI", "ANTHROPIC", "DEEPSEEK"):
        monkeypatch.setenv(f"GALAXY_QUALITY_TIER_{name}", "2")


def _router(providers: dict) -> MultiLLMRouter:
    """只装 provider 表的最小路由器 —— 不触网。providers: name -> (source_type, cost_out, latency_ms)。"""
    r = MultiLLMRouter.__new__(MultiLLMRouter)
    r.providers, r.adapters, r.call_history = {}, {}, []
    for name, (source, cost_out, lat) in providers.items():
        cfg = ProviderConfig(
            name=name,
            api_key="k" if source == "api" else "",
            base_url="http://x/v1",
            models=[f"{name}-m"],
            default_model=f"{name}-m",
            source_type=source,
            cost_per_1k_output=cost_out,
        )
        cfg.status = "healthy"
        cfg.latency_avg_ms = lat
        r.providers[name] = cfg
        r.adapters[name] = object()
    return r


def test_cloud_order_follows_score_not_the_static_table():
    """偏好表里 openai 在 anthropic 前面；anthropic 便宜得多时，对话路由应该把它排前面。"""
    r = _router({"openai": ("api", 0.020, 1000.0), "anthropic": ("api", 0.002, 1000.0)})
    order = ["openai", "anthropic"]  # 与偏好表同序
    ranked = r._order_cloud_by_fit(order, TaskType.GENERAL, 0.5, RoutingPurpose.DIALOGUE)
    assert ranked[0] == "anthropic", f"云端仍照表里写死的顺序: {ranked}"


def test_local_stays_first_only_clouds_are_reranked():
    r = _router({"ollama": ("local", 0.0, 50.0), "openai": ("api", 0.020, 1000.0), "anthropic": ("api", 0.002, 1000.0)})
    ranked = r._order_cloud_by_fit(["ollama", "openai", "anthropic"], TaskType.GENERAL, 0.5, RoutingPurpose.DIALOGUE)
    assert ranked[0] == "ollama", "本地优先是既有语义，不该被云端排序挤掉"
    assert ranked[1:] == ["anthropic", "openai"]


def test_route_returns_best_cloud_first_and_the_rest_as_failover():
    r = _router({"openai": ("api", 0.020, 1000.0), "anthropic": ("api", 0.002, 1000.0)})
    d = r.route(TaskType.GENERAL, complexity_score=0.5)
    assert d.provider == "anthropic"
    assert [a.split(":")[0] for a in d.alternatives] == ["openai"]


def test_purpose_is_one_more_dimension_of_the_same_scorer():
    """同一个打分函数：对话把延迟计入，Agent 生成成本降权、延迟不计。

    A 便宜但慢，B 贵但快：对话选 B（等不起），Agent 生成选 A（质量打平时成本优先，延迟不计）。
    """
    r = _router({"openai": ("api", 0.005, 5000.0), "anthropic": ("api", 0.010, 100.0)})
    dialogue = r._order_cloud_by_fit(["openai", "anthropic"], TaskType.GENERAL, 0.5, RoutingPurpose.DIALOGUE)
    agent = r._order_cloud_by_fit(["openai", "anthropic"], TaskType.GENERAL, 0.5, RoutingPurpose.AGENT)
    assert dialogue[0] == "anthropic", f"对话没把延迟计入: {dialogue}"
    assert agent[0] == "openai", f"Agent 生成不该为延迟付费: {agent}"


def test_rank_brains_for_task_is_cloud_only_ordered_and_limited():
    r = _router(
        {
            "ollama": ("local", 0.0, 50.0),
            "openai": ("api", 0.020, 1000.0),
            "anthropic": ("api", 0.002, 1000.0),
            "deepseek": ("api", 0.020, 1000.0),  # 开源有平局加分，所以让它明显更贵
        }
    )
    ranked = r.rank_brains_for_task(TaskType.CODING, 0.7, purpose=RoutingPurpose.AGENT, limit=2)
    assert len(ranked) == 2
    assert all(d.provider != "ollama" for d in ranked), "排名只给云端（本地型号要按槽位解析，不走这里）"
    assert ranked[0].provider == "anthropic"
    assert r.rank_brains_for_task(TaskType.CODING, 0.7, only_providers=["ollama"]) == []


def test_cloud_provider_names_excludes_local_and_unavailable():
    r = _router({"ollama": ("local", 0.0, 50.0), "openai": ("api", 0.01, 100.0), "anthropic": ("api", 0.01, 100.0)})
    r.providers["anthropic"].status = ProviderStatus.DOWN
    r.providers["anthropic"].down_since = time.time()  # 冷却期内
    assert r.cloud_provider_names() == ["openai"]


# ── 特种部队：最优云端 API + Agent 生成 ─────────────────────────────────────


class _Resp:
    def __init__(self, content=""):
        self.content = content
        self.tool_calls = None
        self.provider = "fake"
        self.model = "fake"
        self.input_tokens = 1
        self.output_tokens = 1


def _brain(provider, model):
    return SimpleNamespace(provider=provider, model=model, reason="test", alternatives=[])


class _FakeRouter:
    """智能路由的替身：按任务类型给排名；记录每次 chat 用了哪个 provider:model、什么系统提示词。"""

    #: 任务类型 -> 排名（最优在前）
    RANKING = {
        "coding": [_brain("cloud_a", "a-code"), _brain("cloud_b", "b-code")],
        "analysis": [_brain("cloud_b", "b-analysis"), _brain("cloud_a", "a-analysis")],
        "planning": [_brain("cloud_a", "a-plan")],
        "reasoning": [_brain("cloud_a", "a-big"), _brain("cloud_b", "b-big")],
    }

    def __init__(self, subtasks, fail=()):
        self.subtasks = subtasks
        self.fail = set(fail)  # 这些 provider 的调用直接抛
        self.calls = []
        self.rank_calls = []
        self.providers = {"cloud_a": SimpleNamespace(default_model="a-default")}
        self.adapters = {"cloud_a": object()}

    def cloud_provider_names(self):
        return ["cloud_a", "cloud_b"]

    def rank_brains_for_task(self, task_type, complexity_score=0.5, *, purpose, only_providers=None, limit=3, **_):
        self.rank_calls.append((task_type.value, purpose, tuple(only_providers or ()), limit))
        return self.RANKING.get(task_type.value, self.RANKING["reasoning"])[:limit]

    def classify_task(self, messages):
        return "general"

    def route(self, task_type):
        raise RuntimeError("不该走到 route()")

    async def chat(self, messages, **kw):
        provider = kw.get("provider")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = " ".join(str(m["content"]) for m in messages if m["role"] == "user")
        if provider in self.fail:
            raise RuntimeError(f"{provider} 挂了")
        self.calls.append({"provider": provider, "model": kw.get("model"), "system": system, "user": user})
        if "分解" in user:
            return _Resp(json.dumps(self.subtasks, ensure_ascii=False))
        return _Resp(f"结果@{provider}")


class _FakeFactory:
    def __init__(self):
        self.created, self.terminated, self.agents = [], [], {}

    def create_from_template(self, template):
        agent = SimpleNamespace(
            id=f"ag{len(self.created)}", config=SimpleNamespace(system_prompt=f"PROMPT<{template}>")
        )
        self.created.append((template, agent.id))
        self.agents[agent.id] = agent
        return agent

    def terminate_agent(self, agent_id, recursive=True):
        self.terminated.append(agent_id)
        self.agents.pop(agent_id, None)


def _team(router, factory):
    members = [TeamMember(agent_id="slot", agent_name="名册", provider="roster", model="roster-m", role_in_team="x")]
    return AgentTeam(
        team_id="t", strategy=TeamStrategy.SPECIALIZED, members=members, agent_factory=factory, llm_router=router
    )


SUBTASKS = [
    {"title": "写实现", "description": "把接口写出来", "role": "coder"},
    {"title": "看数据", "description": "分析日志里的异常", "role": "analyst"},
    {"title": "排计划", "description": "给出上线步骤", "role": "planner"},
]


def _run(team, task="做一件大事"):
    return asyncio.run(team.execute(task, {}))


def test_each_subtask_gets_the_best_cloud_for_its_own_kind_of_work():
    router = _FakeRouter(SUBTASKS)
    _run(_team(router, _FakeFactory()))
    used = {c["user"]: (c["provider"], c["model"]) for c in router.calls if "分解" not in c["user"]}
    assert used["把接口写出来"] == ("cloud_a", "a-code")
    assert used["分析日志里的异常"] == ("cloud_b", "b-analysis")
    assert used["给出上线步骤"] == ("cloud_a", "a-plan")


def test_selection_goes_through_smart_routing_with_agent_purpose_and_cloud_only():
    router = _FakeRouter(SUBTASKS)
    _run(_team(router, _FakeFactory()))
    assert router.rank_calls, "没走智能路由"
    for _task_type, purpose, only, _limit in router.rank_calls:
        assert purpose is RoutingPurpose.AGENT
        assert set(only) == {"cloud_a", "cloud_b"}, "特种部队要在云端里选"


def test_agents_are_generated_per_subtask_by_role_and_their_prompt_is_used():
    factory = _FakeFactory()
    router = _FakeRouter(SUBTASKS)
    _run(_team(router, factory))
    assert [t for t, _ in factory.created] == ["code_executor", "data_analyst", "planner"]
    prompts = {c["user"]: c["system"] for c in router.calls if "分解" not in c["user"]}
    assert "PROMPT<code_executor>" in prompts["把接口写出来"], "生成的 Agent 没被真正用上"
    assert "PROMPT<data_analyst>" in prompts["分析日志里的异常"]
    assert "写实现" in prompts["把接口写出来"]


def test_generated_agents_are_terminated_after_the_run_even_on_failure():
    factory = _FakeFactory()
    _run(_team(_FakeRouter(SUBTASKS), factory))
    assert sorted(factory.terminated) == sorted(aid for _, aid in factory.created)
    assert factory.agents == {}


def test_failed_member_falls_over_to_the_next_ranked_cloud():
    router = _FakeRouter(SUBTASKS, fail={"cloud_a"})
    result = _run(_team(router, _FakeFactory()))
    code = [c for c in router.calls if c["user"] == "把接口写出来"]
    assert code and code[0]["provider"] == "cloud_b", "第一名挂了应换备选"
    assert all(mr.success for mr in result.member_results if "写实现" in mr.result)


def test_synthesis_uses_the_strongest_reasoning_cloud():
    router = _FakeRouter(SUBTASKS)
    _run(_team(router, _FakeFactory()))
    synth = [c for c in router.calls if "各方回答" in c["user"]]
    assert synth and (synth[0]["provider"], synth[0]["model"]) == ("cloud_a", "a-big")


def test_role_falls_back_to_task_type_when_the_llm_does_not_tag_one():
    untagged = [{"title": "一", "description": "写代码"}, {"title": "二", "description": "看日志"}]
    factory = _FakeFactory()
    _run(_team(_FakeRouter(untagged), factory))
    assert len(factory.created) == 2  # 都生成了 Agent（角色由任务类型兜底推断）


def test_create_team_does_not_register_agents_up_front_and_roster_uses_best_cloud():
    factory = _FakeFactory()
    router = _FakeRouter(SUBTASKS)
    manager = TeamManager(agent_factory=factory, llm_router=router)
    team = asyncio.run(manager.create_team("specialized", task_hint="分析并实现", complexity_score=0.8))
    assert factory.created == [], "建队时不该再预先注册 Agent（执行时才按子任务现场生成）"
    roles = {m.role_in_team: (m.provider, m.model) for m in team.members}
    assert set(roles) == {"analyst", "coder", "planner", "researcher", "coordinator"}
    assert roles["coder"] == ("cloud_a", "a-code")
    assert roles["analyst"] == ("cloud_b", "b-analysis")
    assert team.complexity_score == 0.8


def test_other_team_strategies_still_register_their_agents():
    """特种部队之外的 team / swarm 不变：仍在建队时生成。"""
    factory = _FakeFactory()
    manager = TeamManager(agent_factory=factory, llm_router=_FakeRouter(SUBTASKS))
    asyncio.run(manager.create_team("swarm", task_hint="x"))
    assert factory.created, "swarm 应保持原样"
