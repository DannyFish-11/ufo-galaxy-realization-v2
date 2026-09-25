"""tests/test_agent_supply.py — 模型与模态供给：Agent Factory 按各家模型的 API 造 Agent（R6）。

改良书 R6 的四条验收：

① 先无参、再带 router 调工厂 —— 必须能跑真 LLM（断点 1）；
② 三个不同角色的 route_type 不得全同（断点 3）；
③ 声明 vision_in 而当前档无视觉 —— unmet 非空且不得开跑（G14）；
④ 三格全空时 off 与 on 喂给 router 的入参逐字段相同（不声明就什么都不变）。

另钉：G13（声明不点名供应商）、断点 4（团队成员与 Agent 用同一份结论）、shadow 档的
divergence、§04H（元层用独立的路由实例）。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.agent_factory as af
import core.agent_supply as sup

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Resp:
    content = "好的"
    tool_calls = None
    provider = "cloudy"
    model = "cloudy-large"
    input_tokens = 1
    output_tokens = 1


class _Router:
    """按角色给出确定的脑，并记下每次调用喂进来的入参。"""

    BRAINS = {
        "executor": ("ollama", "qwen-local"),
        "worker": ("ollama", "qwen-local"),
        "reviewer": ("cloudy", "cloudy-large"),
        "coordinator": ("cloudy", "cloudy-large"),
        "planner": ("cloudy", "cloudy-large"),
        "analyst": ("cloudy", "cloudy-large"),
        "writer": ("cloudy", "cloudy-large"),
        "coder": ("cloudy", "cloudy-large"),
    }

    def __init__(self):
        self.providers = {}
        self.calls = []
        self.selected_roles = []

    def select_brain_for_role(self, role, complexity_score=0.5, task_type=None):
        self.selected_roles.append(role)
        provider, model = self.BRAINS.get(role, ("cloudy", "cloudy-large"))
        return SimpleNamespace(provider=provider, model=model, reason=f"fake:{role}")

    async def chat_with_tools(self, messages, tools=None, **kwargs):
        self.calls.append(kwargs)
        return _Resp()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.delenv("GALAXY_AGENT_SUPPLY", raising=False)
    monkeypatch.setattr(sup, "DIVERGENCE_LOG", tmp_path / "divergences.jsonl")
    monkeypatch.setattr(sup, "_admission_provisional", lambda model, is_local: (False, ""))
    monkeypatch.setattr(af, "_factory_instance", None)


def _factory(router):
    factory = af.AgentFactory(llm_router=router)
    factory._llm_circuit_breaker = None
    factory._persist_state = lambda: None
    return factory


def _run(factory, agent, task=None):
    return asyncio.run(factory._execute_single_task(agent, task or {"description": "查一下"}))


# ---------------------------------------------------------------------------
# ① 断点 1：单例不再吞掉后到的 router
# ---------------------------------------------------------------------------


def test_router_passed_after_a_parameterless_call_is_adopted(monkeypatch):
    monkeypatch.setattr(af.AgentFactory, "_persist_state", lambda self: None)
    first = af.get_agent_factory()
    assert first.llm_router is None
    router = _Router()
    second = af.get_agent_factory(router)
    assert second is first and first.llm_router is router
    first._llm_circuit_breaker = None
    result = _run(first, first.create_from_template("coordinator"))
    assert not result.get("simulated"), "带了 router 之后还在走 simulated 分支"
    assert router.calls, "没有真的调到 LLM"


def test_an_existing_router_is_not_swapped_out(monkeypatch):
    monkeypatch.setattr(af.AgentFactory, "_persist_state", lambda self: None)
    first_router, second_router = _Router(), _Router()
    factory = af.get_agent_factory(first_router)
    assert af.get_agent_factory(second_router).llm_router is first_router
    assert factory.llm_router is first_router


# ---------------------------------------------------------------------------
# ② 断点 3：角色进得了路由
# ---------------------------------------------------------------------------


def test_three_roles_do_not_share_one_route_type():
    router = _Router()
    decisions = [
        sup.decide_supply(f"a{i}", role=role, router=router, mode="shadow")
        for i, role in enumerate(("coordinator", "executor", "specialist"))
    ]
    assert len({d.route_type for d in decisions}) == 3, [d.route_type for d in decisions]
    assert len({d.task_type for d in decisions}) == 3
    assert [d.brain_role for d in decisions] == ["coordinator", "executor", "coder"]


def test_declared_preference_steers_the_call_in_on_mode(monkeypatch):
    monkeypatch.setenv("GALAXY_AGENT_SUPPLY", "on")
    router = _Router()
    factory = _factory(router)
    agent = factory.create_from_template("coordinator")
    agent.config.model_preference = "dispatch"
    agent.supply = sup.supply_for_config(agent.id, agent.config, router)
    _run(factory, agent)
    assert router.calls[-1] == {"task_type": "fast_response", "provider": "ollama", "model": "qwen-local"}
    assert agent.to_dict()["supply"]["route_type"] == "dispatch"


# ---------------------------------------------------------------------------
# ③ G14：供不上就报
# ---------------------------------------------------------------------------


def _plan(vision_mode):
    res = lambda mode: SimpleNamespace(mode=mode)  # noqa: E731
    return SimpleNamespace(
        get=lambda m: res(vision_mode if m == "vision_in" else "native"), to_dict=lambda: {"vision_in": vision_mode}
    )


def test_declared_vision_without_vision_is_unmet_and_refused(monkeypatch):
    monkeypatch.setenv("GALAXY_AGENT_SUPPLY", "on")
    monkeypatch.setattr("core.modality_capability.negotiate", lambda **kw: _plan("unavailable"))
    router = _Router()
    factory = _factory(router)
    agent = factory.create_from_template("data_analyst")
    agent.config.modality_required = ("vision_in",)
    agent.supply = sup.supply_for_config(agent.id, agent.config, router)
    assert agent.supply.unmet == ("vision_in",)

    result = _run(factory, agent)
    assert result["status"] == "supply_unmet" and result["success"] is False
    assert "vision_in" in result["error"]
    assert router.calls == [], "供不上还开跑了 —— 静默降级"


@pytest.mark.parametrize("mode", ["native", "bridge"])
def test_native_or_bridged_modality_counts_as_supplied(monkeypatch, mode):
    monkeypatch.setattr("core.modality_capability.negotiate", lambda **kw: _plan(mode))
    decision = sup.decide_supply("a", role="analyst", modality_required=("vision_in",), router=_Router(), mode="on")
    assert decision.unmet == () and decision.modality_plan == {"vision_in": mode}


def test_local_only_on_a_cloud_brain_is_unmet():
    decision = sup.decide_supply("a", role="coordinator", locus_constraint="local_only", router=_Router(), mode="on")
    assert decision.unmet == ("locus:local_only",) and decision.is_local is False


def test_admission_provisional_is_reported_not_refused(monkeypatch):
    monkeypatch.setattr(sup, "_admission_provisional", lambda model, is_local: (is_local, "ok"))
    decision = sup.decide_supply("a", role="executor", model_preference="dispatch", router=_Router(), mode="on")
    assert decision.admission_provisional is True and decision.runnable, "有前提的 ok 照跑，但前提要报出来"


# ---------------------------------------------------------------------------
# ④ 三格全空：off 与 on 逐字段相同
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", sorted(af.AGENT_TEMPLATES))
def test_undeclared_agents_feed_the_router_identically_in_off_and_on(monkeypatch, template):
    seen = {}
    for mode in ("off", "on"):
        monkeypatch.setenv("GALAXY_AGENT_SUPPLY", mode)
        router = _Router()
        factory = _factory(router)
        _run(factory, factory.create_from_template(template))
        seen[mode] = router.calls
    assert seen["off"] == seen["on"] == [{"task_type": "agent_control"}]


def test_off_mode_computes_nothing(monkeypatch):
    router = _Router()
    agent = _factory(router).create_from_template("planner")
    assert agent.supply is None and router.selected_roles == []
    assert "supply" not in agent.to_dict()


# ---------------------------------------------------------------------------
# shadow：算、绑、比对，但不改执行
# ---------------------------------------------------------------------------


def test_shadow_records_divergence_without_changing_the_call(monkeypatch):
    monkeypatch.setenv("GALAXY_AGENT_SUPPLY", "shadow")
    router = _Router()
    factory = _factory(router)
    agent = factory.create_from_template("device_controller")  # executor → 算出来是本地 ollama
    assert agent.supply is not None and agent.supply.provider == "ollama"
    _run(factory, agent)  # 实际响应来自 cloudy
    assert router.calls == [{"task_type": "agent_control"}]
    [line] = sup.DIVERGENCE_LOG.read_text(encoding="utf-8").splitlines()
    entry = json.loads(line)
    assert entry["decided"]["provider"] == "ollama" and entry["actual"]["provider"] == "cloudy"


def test_shadow_agreement_records_nothing(monkeypatch):
    monkeypatch.setenv("GALAXY_AGENT_SUPPLY", "shadow")
    router = _Router()
    factory = _factory(router)
    _run(factory, factory.create_from_template("coordinator"))  # 算出来 cloudy，实际也是 cloudy
    assert not sup.DIVERGENCE_LOG.exists()


# ---------------------------------------------------------------------------
# 断点 4：团队成员与 Agent 用同一份结论
# ---------------------------------------------------------------------------


def test_team_member_reuses_the_agents_supply(monkeypatch):
    from core.agent_team import TeamManager

    monkeypatch.setenv("GALAXY_AGENT_SUPPLY", "on")
    router = _Router()
    factory = _factory(router)
    original = factory.create_from_template

    def _declaring(template, **kw):
        agent = original(template, **kw)
        agent.config.model_preference = "gatekeep"
        agent.supply = sup.supply_for_config(agent.id, agent.config, router)
        return agent

    factory.create_from_template = _declaring
    team = TeamManager.__new__(TeamManager)
    team._factory, team._router = factory, router
    member = team._make_role_member(
        name="审", template="planner", role="executor", complexity_score=0.9, task_type=None, providers=[]
    )
    assert (member.provider, member.model) == ("cloudy", "cloudy-large")
    assert factory.agents[member.agent_id].supply.provider == member.provider


# ---------------------------------------------------------------------------
# G13：声明是需求，不是供应商
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pref, mods, locus, ok",
    [
        ("", (), "", True),
        ("gatekeep", ("vision_in",), "cloud_ok", True),
        ("deepseek", (), "", False),
        ("", ("gpt-4o",), "", False),
        ("", (), "qwen2.5:7b", False),
    ],
)
def test_declaration_enums(pref, mods, locus, ok):
    assert (sup.declaration_violations(pref, mods, locus) == []) is ok


def test_llm_generated_config_is_sanitized():
    clean = sup.sanitize_declaration(
        {"model_preference": "anthropic", "modality_required": ["vision_in", "smell"], "locus_constraint": "cloud_ok"}
    )
    assert clean == {"model_preference": "", "modality_required": ("vision_in",), "locus_constraint": "cloud_ok"}


def test_g13_guard_passes_on_the_repo_and_catches_a_vendor_name(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import check_agent_supply_declaration as guard
    finally:
        sys.path.pop(0)
    assert guard.scan_python() == [] and guard.scan_config() == []
    fake = tmp_path / "core"
    fake.mkdir()
    (fake / "bad.py").write_text('AgentConfig(model_preference="deepseek")\n', encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    [(where, detail)] = guard.scan_python()
    assert where == "core/bad.py:1" and "deepseek" in detail
    proc = subprocess.run(
        [sys.executable, "scripts/check_agent_supply_declaration.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# §04H：元层的供给通道与请求路径隔离
# ---------------------------------------------------------------------------


def test_meta_router_is_not_the_request_path_singleton():
    from core.meta.supply import RSI_API_SLOT, meta_llm_router, meta_supply_status
    from core.multi_llm_router import get_llm_router

    meta, hot = meta_llm_router(), get_llm_router()
    assert meta is not hot and meta is meta_llm_router()
    assert meta.circuit_breakers is not hot.circuit_breakers, "熔断器必须各一份"
    assert meta.call_history is not hot.call_history
    assert (RSI_API_SLOT["url"], RSI_API_SLOT["protocol"], RSI_API_SLOT["auth"]) == (None, None, None), "形状未定，不猜"
    assert meta_supply_status()["isolated"] is True


def test_supply_module_stays_off_the_meta_layer():
    from core.meta.guards import direct_meta_imports

    source = (REPO_ROOT / "core" / "agent_supply.py").read_text(encoding="utf-8")
    assert direct_meta_imports(source) == []
