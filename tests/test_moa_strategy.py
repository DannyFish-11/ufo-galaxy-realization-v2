"""tests/test_moa_strategy.py
================================
MoA(Mixture of Agents)多层协作策略 + 分级升级策略。

验证四件事:
 1. 成员构建:proposer 绑定【本地】provider(persona 差异),aggregator 绑定
    【最强云端】(偏好序 anthropic 优先);无云端时退回本地。
 2. 多层执行:第 2 层成员的输入携带【上一层全部候选产出】(MoA 与单层并行的
    本质区别);aggregator 收到候选并出终稿。
 3. 韧性:aggregator 失败退回既有综合逻辑;第一层全灭如实报错不抛异常。
 4. 分级:深度关键词/极高复杂度 → moa;GALAXY_MOA_ENABLED=0 → 不升级。

全部用假 router(不触网、不加载真实模型)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.agent_team import AgentTeam, TeamManager, TeamMember, TeamStrategy
from core.collaboration_mode_policy import select_collaboration_mode

# ───────────────────── 假 router ─────────────────────


@dataclass
class _FakeProviderCfg:
    name: str
    default_model: str
    source_type: str = "api"


@dataclass
class _FakeResponse:
    content: str
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class _FakeRouter:
    providers: Dict[str, _FakeProviderCfg] = field(default_factory=dict)
    adapters: Dict[str, Any] = field(default_factory=dict)
    calls: List[Dict] = field(default_factory=list)
    fail_providers: set = field(default_factory=set)

    def classify_task(self, messages):
        return "general"

    async def chat(self, messages=None, provider=None, model=None, **kw):
        self.calls.append({"provider": provider, "model": model, "messages": messages})
        if provider in self.fail_providers:
            raise RuntimeError(f"{provider} down")
        user = next((m["content"] for m in (messages or []) if m.get("role") == "user"), "")
        return _FakeResponse(content=f"[{provider}] answer to: {user[:60]}")


def _router_with(local: bool = True, cloud: bool = True, fail: set = ()) -> _FakeRouter:
    r = _FakeRouter(fail_providers=set(fail))
    if local:
        r.providers["ollama"] = _FakeProviderCfg("ollama", "gemma4:e2b", source_type="local")
        r.adapters["ollama"] = object()
    if cloud:
        r.providers["deepseek"] = _FakeProviderCfg("deepseek", "deepseek-v4-pro", source_type="api")
        r.adapters["deepseek"] = object()
        r.providers["anthropic"] = _FakeProviderCfg("anthropic", "claude-x", source_type="api")
        r.adapters["anthropic"] = object()
    return r


# ───────────────────── 1. 成员构建 ─────────────────────


def test_moa_members_local_proposers_cloud_aggregator():
    mgr = TeamManager(agent_factory=None, llm_router=_router_with())
    team = asyncio.run(mgr.create_team(strategy="moa", task_hint="深入研究一下"))
    proposers = [m for m in team.members if m.role_in_team.startswith("proposer")]
    aggs = [m for m in team.members if m.role_in_team == "aggregator"]
    assert len(proposers) >= 2
    assert all(m.provider == "ollama" for m in proposers)  # 本地免费扇出
    assert len(aggs) == 1
    assert aggs[0].provider == "anthropic"  # 云端偏好序第一位
    # persona 差异(多样性不靠不同模型,靠不同视角)
    assert len({m.agent_name for m in proposers}) == len(proposers)


def test_moa_members_no_cloud_falls_back_local_aggregator():
    mgr = TeamManager(agent_factory=None, llm_router=_router_with(cloud=False))
    team = asyncio.run(mgr.create_team(strategy="moa", task_hint="x"))
    aggs = [m for m in team.members if m.role_in_team == "aggregator"]
    assert len(aggs) == 1 and aggs[0].provider == "ollama"


def test_moa_members_no_local_uses_cloud_proposers():
    mgr = TeamManager(agent_factory=None, llm_router=_router_with(local=False))
    team = asyncio.run(mgr.create_team(strategy="moa", task_hint="x"))
    proposers = [m for m in team.members if m.role_in_team.startswith("proposer")]
    assert proposers and all(m.provider in ("deepseek", "anthropic") for m in proposers)


# ───────────────────── 2. 多层执行 ─────────────────────


def _make_team(router, members) -> AgentTeam:
    return AgentTeam(team_id="t1", strategy=TeamStrategy.MOA, members=members, agent_factory=None, llm_router=router)


def _members(router) -> List[TeamMember]:
    return [
        TeamMember("a1", "严谨分析者-ollama", "ollama", "gemma4:e2b", "proposer:严谨"),
        TeamMember("a2", "批判审视者-ollama", "ollama", "gemma4:e2b", "proposer:批判"),
        TeamMember("a3", "聚合器-anthropic", "anthropic", "claude-x", "aggregator"),
    ]


def test_moa_layer2_members_see_previous_layer_outputs(monkeypatch):
    monkeypatch.setenv("GALAXY_MOA_LAYERS", "3")  # proposer → 精炼 → 聚合
    router = _router_with()
    team = _make_team(router, _members(router))
    result = asyncio.run(team.execute("测试任务"))
    assert result.strategy == "moa"
    # 第 2 层(精炼层)的 user prompt 必须携带上一层候选(MoA 的本质)
    layer2_calls = [c for c in router.calls if any("上一层候选回答" in m.get("content", "") for m in c["messages"])]
    assert layer2_calls, "第 2 层成员没有收到上一层的候选产出——不是 MoA,只是并行"
    # aggregator 收到候选并出终稿
    agg_calls = [c for c in router.calls if c["provider"] == "anthropic"]
    assert agg_calls and any("候选回答" in m.get("content", "") for m in agg_calls[-1]["messages"])
    assert result.synthesized.startswith("[anthropic]")
    # 层号标注进了成员结果(可观测)
    assert any(mr.member.role_in_team.startswith("L1:") for mr in result.member_results)
    assert any(mr.member.role_in_team.startswith("L2:") for mr in result.member_results)


def test_moa_default_two_layers(monkeypatch):
    monkeypatch.delenv("GALAXY_MOA_LAYERS", raising=False)
    router = _router_with()
    team = _make_team(router, _members(router))
    result = asyncio.run(team.execute("测试任务"))
    # 默认 2 层 = proposer 一层 + 聚合,不应出现 L2 精炼层
    assert not any(mr.member.role_in_team.startswith("L2:proposer") for mr in result.member_results)
    assert result.synthesized.startswith("[anthropic]")


# ───────────────────── 3. 韧性 ─────────────────────


def test_moa_aggregator_failure_falls_back_to_synthesis(monkeypatch):
    monkeypatch.delenv("GALAXY_MOA_LAYERS", raising=False)
    router = _router_with(fail={"anthropic"})  # 聚合器挂了
    team = _make_team(router, _members(router))
    result = asyncio.run(team.execute("测试任务"))
    # 不空手:退回综合逻辑(综合走 router.chat 无 provider → 假 router 也能答)
    assert result.synthesized and "执行失败" not in result.synthesized


def test_moa_all_proposers_fail_reports_honestly():
    router = _router_with(fail={"ollama"})
    team = _make_team(router, _members(router))
    result = asyncio.run(team.execute("测试任务"))
    assert "所有 proposer 执行失败" in result.synthesized


def test_moa_no_aggregator_single_output_passthrough():
    router = _router_with()
    members = [TeamMember("a1", "分析者", "ollama", "gemma4:e2b", "proposer:x")]
    team = _make_team(router, members)
    result = asyncio.run(team.execute("测试任务"))
    assert result.synthesized.startswith("[ollama]")  # 单候选直通,不多花一次综合调用


# ───────────────────── 4. 分级升级策略 ─────────────────────


def test_tier_moa_keyword(monkeypatch):
    monkeypatch.delenv("GALAXY_MOA_ENABLED", raising=False)
    out = select_collaboration_mode("帮我深入研究一下量子计算的现状", complexity_score=0.3)
    assert out["mode"] == "moa" and out["source"] == "keyword"


def test_tier_moa_extreme_complexity(monkeypatch):
    monkeypatch.delenv("GALAXY_MOA_ENABLED", raising=False)
    out = select_collaboration_mode("普通消息", complexity_score=0.9)
    assert out["mode"] == "moa" and out["source"] == "complexity"


def test_tier_high_complexity_stays_critic():
    out = select_collaboration_mode("普通消息", complexity_score=0.75)
    assert out["mode"] == "critic"  # 0.7–0.85 维持既有 critic 档,不被 MoA 抢走


def test_tier_moa_disabled(monkeypatch):
    monkeypatch.setenv("GALAXY_MOA_ENABLED", "0")
    assert select_collaboration_mode("深入研究这个", complexity_score=0.9)["mode"] != "moa"


def test_tier_moa_explicit_override():
    out = select_collaboration_mode("随便什么", complexity_score=0.1, context={"collaboration_mode": "moa"})
    assert out["mode"] == "moa" and out["source"] == "override"


def test_tier_low_complexity_unchanged():
    assert select_collaboration_mode("你好", complexity_score=0.2)["mode"] == "parallel"


def test_manifest_schema_accepts_moa():
    from core.schemas.agent import TeamStrategyEnum

    assert TeamStrategyEnum("moa") is TeamStrategyEnum.MOA
