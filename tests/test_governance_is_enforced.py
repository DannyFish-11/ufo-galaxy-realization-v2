"""tests/test_governance_is_enforced.py — 治理面写好的规则真的作用在执行上。

此前这一组全是「能改、能读，不起作用」：

* 零信任规则表（``PUT /api/v1/security/policy``）只被 ``/evaluate`` 端点读，派发从不问它；
* 预算执行器只挂在 ``/api/v1/governance/budget`` 上，没人在调模型前问它，也没人记真实花费；
* 模型路由策略文件只在构造时读一次；
* worker 注册、网格 MCP 调用绕过了防腐层，任务派发 / 结果却都过；
* 技能调用结果从不按契约校验。
"""

from __future__ import annotations

import logging
import os
import time
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# 零信任规则表
# ---------------------------------------------------------------------------


@pytest.fixture
def _policy_table():
    from core.routes import security_policy as sp

    saved = dict(sp._active_policy)
    yield sp
    sp._active_policy.clear()
    sp._active_policy.update(saved)


class TestZeroTrustTableGatesDispatch:
    def test_table_adds_confirmation_but_cannot_remove_the_builtin_one(self, _policy_table):
        from core.command_router import CommandRouter

        router = CommandRouter(executor=lambda *a, **k: None)
        assert router._is_high_risk_command("destroy_volume") is True  # 只有表里有
        assert router._is_high_risk_command("list_files") is False
        _policy_table._active_policy["rules"] = [{"match": {"action": "reboot"}, "require_hitl": False}]
        assert router._is_high_risk_command("reboot") is True  # 内置的仍需确认
        _policy_table._active_policy["rules"] = [{"match": {"action": "take_photo"}, "require_hitl": True}]
        assert router._is_high_risk_command("take_photo") is True  # 运维加的规则立刻生效

    @pytest.mark.asyncio
    async def test_table_only_command_goes_through_the_policy_interceptor(self, _policy_table, monkeypatch):
        import core.control_plane._globals as g
        from core.command_router import CommandRouter

        _policy_table._active_policy["rules"] = [{"match": {"action": "take_photo"}, "require_hitl": True}]
        calls = []

        class _Interceptor:
            async def check_and_intercept(self, action, **kw):
                calls.append(("policy", action))
                return {"ack_token": "tok", "approved": True, "risk_level": "high", "require_hitl": True}

            async def require_approval(self, action, **kw):
                calls.append(("builtin", action))
                return "tok"

        monkeypatch.setattr(g, "get_security_interceptor", lambda *a, **k: _Interceptor())

        async def _exec(*_a, **_k):
            return {"success": True, "result": "ok"}

        router = CommandRouter(executor=_exec)
        for command in ("take_photo", "reboot"):
            await router._execute_command("dev", command, {"_hitl_approved": True}, f"c-{command}", f"t-{command}")
        assert ("policy", "take_photo") in calls
        assert ("builtin", "reboot") in calls


# ---------------------------------------------------------------------------
# 预算
# ---------------------------------------------------------------------------


@pytest.fixture
def _budget(monkeypatch):
    import core.governance.budget_enforcer as be
    from core.governance.policy_schema import BudgetPolicy, OnBudgetExceed

    def _make(**policy):
        enforcer = be.BudgetEnforcer(BudgetPolicy(**policy))
        monkeypatch.setattr(be, "_enforcer", enforcer)
        return enforcer

    yield _make, OnBudgetExceed
    monkeypatch.setattr(be, "_enforcer", None)


def _router_with_backend(backend):
    from core.unified.llm_router import UnifiedLLMRouter

    router = object.__new__(UnifiedLLMRouter)
    router.__dict__.update(UnifiedLLMRouter().__dict__)
    router._backend = backend
    return router


class _Backend:
    providers: dict = {}

    def __init__(self):
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(provider="p1", model="m1", content="hi", usage={"total_tokens": 1000}, tool_calls=None)


class TestBudgetIsEnforced:
    @pytest.mark.asyncio
    async def test_real_spend_is_recorded_and_readable(self, _budget, monkeypatch):
        make, _ = _budget
        enforcer = make()
        router = _router_with_backend(_Backend())
        monkeypatch.setattr(router, "_estimate_cost_per_1k", lambda *_a: 0.02)
        monkeypatch.setattr(router, "_get_provider_order", lambda *_a, **_k: (["p1"], {}))
        await router.chat_with_tools(messages=[{"role": "user", "content": "x"}], tools=[{"x": 1}], session_id="s-1")
        status = await enforcer.get_status("s-1", "default")
        assert status.session_spent_usd == pytest.approx(0.02)
        assert status.daily_spent_usd == pytest.approx(0.02)

        await router.chat_with_tools(messages=[{"role": "user", "content": "x"}], tools=[{"x": 1}])
        assert (await enforcer.get_status("s-1", "default")).daily_spent_usd == pytest.approx(0.04)
        assert enforcer.all_session_ids() == ["s-1"]  # 没有会话号的调用不留会话计数

    @pytest.mark.asyncio
    async def test_deny_policy_stops_the_call_before_the_model_is_hit(self, _budget, monkeypatch):
        from core.governance.budget_enforcer import BudgetExceededError

        make, on_exceed = _budget
        enforcer = make(daily_budget_usd=0.01, on_exceed=on_exceed.DENY)
        await enforcer.record_usage("earlier", "default", "m1", 1000, 0.02)  # 今天已经花超了
        backend = _Backend()
        router = _router_with_backend(backend)
        monkeypatch.setattr(router, "_get_provider_order", lambda *_a, **_k: (["p1"], {}))
        with pytest.raises(BudgetExceededError):
            await router.chat_with_tools(
                messages=[{"role": "user", "content": "x"}], tools=[{"x": 1}], session_id="s-2"
            )
        assert backend.calls == 0

    def test_governance_endpoint_reads_the_same_enforcer(self, _budget):
        from core.governance.budget_enforcer import get_budget_enforcer
        from core.routes import governance

        make, _ = _budget
        enforcer = make()
        governance._budget_enforcer = None
        assert governance._get_budget_enforcer() is enforcer is get_budget_enforcer()
        governance._budget_enforcer = None


class TestRoutingPolicyHotReload:
    def test_changed_policy_file_is_reloaded(self, tmp_path, monkeypatch):
        from core.periodic_maintenance import LLMRoutingPolicyHotReload
        from core.unified import llm_router

        policy = tmp_path / "llm_routing_policy.yaml"
        policy.write_text("a: 1\n", encoding="utf-8")
        monkeypatch.setattr(llm_router, "_POLICY_PATH", policy)
        reloaded = []
        monkeypatch.setattr(
            llm_router.UnifiedLLMRouter, "_instance", SimpleNamespace(reload_policy=lambda: reloaded.append(1))
        )
        sweep = LLMRoutingPolicyHotReload()
        assert sweep() is False  # 第一次只记下修改时间
        assert sweep() is False
        os.utime(policy, (time.time() + 5, time.time() + 5))
        assert sweep() is True
        assert reloaded == [1]


# ---------------------------------------------------------------------------
# 防腐层与技能契约
# ---------------------------------------------------------------------------


class TestAntiCorruptionLayerAtIngress:
    @pytest.mark.asyncio
    async def test_worker_registration_goes_through_the_acl(self):
        from core.master_brain import MasterBrain

        seen = []

        class _Acl:
            async def validate_worker_registration(self, raw):
                seen.append(raw)
                return {"success": False, "error": "nope"}

        brain = MasterBrain(acl_layer=_Acl(), state_path=None)
        registered = []
        brain.register_worker = lambda reg: registered.append(reg)  # type: ignore[assignment]
        await brain._on_worker_event({"worker_id": "w1", "device_type": "pc"})
        assert seen and registered == []

    @pytest.mark.asyncio
    async def test_mesh_mcp_call_rejected_by_acl_gets_an_error_reply(self, monkeypatch):
        from core.mcp_gateway import MCPDynamicGateway

        class _Acl:
            async def validate_mcp_call(self, raw):
                return {"success": False, "error": "too big"}

        gateway = MCPDynamicGateway(acl_layer=_Acl())
        replies = []

        async def _reply(request_id, *, result=None, error="", started=0.0):
            replies.append((request_id, error))

        monkeypatch.setattr(gateway, "_publish_call_response", _reply)
        monkeypatch.setattr(gateway, "execute_tool", lambda *a, **k: pytest.fail("must not execute"))
        await gateway._on_nats_call({"request_id": "r1", "tool_name": "x"})
        assert replies and replies[0][0] == "r1" and "too big" in replies[0][1]


class TestSkillResponsesAreChecked:
    def test_contract_violation_is_logged(self, caplog):
        from core.skill_contract import SkillMetrics, SkillRequest, SkillResponse, SkillStatus
        from core.skill_registry import get_skill_registry

        bad = SkillResponse.success("s", "tr", {"ok": 1}, SkillMetrics(started_at=time.time()))
        bad.status = SkillStatus.FAILURE  # 失败却没带错误
        with caplog.at_level(logging.WARNING):
            get_skill_registry()._emit_log(SkillRequest(skill_name="s", inputs={}), bad)
        assert "contract violation" in caplog.text
