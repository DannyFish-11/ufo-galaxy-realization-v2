"""tests/test_autonomy_policy.py
===================================

自治拨盘 + 审批分级授权:
  - 档位语义: safe(敏感节点全问) / guided(读放行写审批) / autonomous(不逐步问人)。
  - 范围: 只对声明了权限白名单的敏感节点生效。
  - 授权: once 用后即焚 / session 进程期 / always 持久化且可撤销。
  - 执行器集成: 需审批的动作被排队(approval_required),授权后重试通过本门。
"""
from __future__ import annotations

import asyncio

import pytest

import core.autonomy_policy as ap


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    # 授权记录落到临时文件,互不污染;档位默认 guided。
    monkeypatch.setattr(ap, "_grants_path", lambda: str(tmp_path / "grants.json"))
    ap.reset_grant_store()
    monkeypatch.delenv("GALAXY_AUTONOMY", raising=False)
    yield
    ap.reset_grant_store()


class TestLevelAndClassification:
    def test_default_level_guided(self):
        assert ap.autonomy_level() is ap.AutonomyLevel.GUIDED

    def test_bad_level_falls_back_guided(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTONOMY", "banana")
        assert ap.autonomy_level() is ap.AutonomyLevel.GUIDED

    def test_read_actions(self):
        for a in ("screenshot", "get_ui_tree", "list_windows", "find_element",
                  "devices", "status", "locate_on_screen"):
            assert ap.is_read_action(a), a

    def test_write_actions(self):
        for a in ("click", "type_text", "shell", "tap", "install", "hotkey"):
            assert not ap.is_read_action(a), a


class TestEvaluate:
    def test_autonomous_never_asks(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
        d = ap.evaluate_autonomy("Node_36_UIAWindows", "click")
        assert not d.needs_approval

    def test_undeclared_node_never_asks(self):
        d = ap.evaluate_autonomy("Node_00_StateMachine", "anything")
        assert not d.needs_approval and "非敏感" in d.reason

    def test_guided_read_allowed_write_asks(self):
        assert not ap.evaluate_autonomy("Node_36_UIAWindows", "screenshot").needs_approval
        d = ap.evaluate_autonomy("Node_36_UIAWindows", "click")
        assert d.needs_approval and d.level == "guided"

    def test_safe_asks_even_for_read(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTONOMY", "safe")
        assert ap.evaluate_autonomy("Node_36_UIAWindows", "screenshot").needs_approval


class TestGrants:
    def test_once_is_consumed(self):
        st = ap.get_grant_store()
        st.grant("Node_36_UIAWindows", "click", ap.GrantScope.ONCE)
        assert not ap.evaluate_autonomy("Node_36_UIAWindows", "click").needs_approval  # 消费
        assert ap.evaluate_autonomy("Node_36_UIAWindows", "click").needs_approval      # 已焚

    def test_session_persists_within_process(self):
        ap.get_grant_store().grant("Node_36_UIAWindows", "click", ap.GrantScope.SESSION)
        for _ in range(3):
            assert not ap.evaluate_autonomy("Node_36_UIAWindows", "click").needs_approval

    def test_always_persists_to_disk_and_revocable(self, tmp_path):
        st = ap.get_grant_store()
        key = st.grant("Node_33_ADB", "shell", ap.GrantScope.ALWAYS)
        # 新实例(模拟重启)仍生效
        ap.reset_grant_store()
        assert not ap.evaluate_autonomy("Node_33_ADB", "shell").needs_approval
        # 撤销后恢复审批
        assert ap.get_grant_store().revoke(key)
        assert ap.evaluate_autonomy("Node_33_ADB", "shell").needs_approval

    def test_list_grants_shape(self):
        st = ap.get_grant_store()
        st.grant("Node_45_DesktopAuto", "click", ap.GrantScope.ALWAYS)
        g = st.list_grants()
        assert "Node_45_DesktopAuto:click" in g["always"]


class TestApprovalQueue:
    def test_request_queued_and_deduped(self):
        r1 = ap.ensure_approval_request("Node_36_UIAWindows", "click", {"x": 1})
        r2 = ap.ensure_approval_request("Node_36_UIAWindows", "click", {"x": 2})
        assert r1["request_id"] == r2["request_id"] and r2["reused"]

    def test_queued_request_visible_in_registry(self):
        from core.control_plane._globals import get_approval_registry
        ap.ensure_approval_request("Node_45_DesktopAuto", "type", {})
        pending = [r.action for r in get_approval_registry().list_pending()]
        assert "Node_45_DesktopAuto.type" in pending


class TestExecutorIntegration:
    def test_write_action_held_then_grant_passes_gate(self):
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor

        env = NodeInvocationEnvelope(node_id="Node_36_UIAWindows", action="click")
        held = asyncio.run(UnifiedNodeExecutor().execute(env))
        assert held.success is False and "approval_required" in (held.error or "")
        info = (held.eligibility_denial or {}).get("approval_required", {})
        assert info.get("needs_approval") is True and info.get("request_id")

        # 授权"仅此次"后重试:通过自治门(后续在别处失败也不该再是 approval_required)
        ap.get_grant_store().grant("Node_36_UIAWindows", "click", ap.GrantScope.ONCE)
        retried = asyncio.run(UnifiedNodeExecutor().execute(
            NodeInvocationEnvelope(node_id="Node_36_UIAWindows", action="click")))
        assert "approval_required" not in (retried.error or "")

    def test_read_action_not_held_in_guided(self):
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor

        env = NodeInvocationEnvelope(node_id="Node_36_UIAWindows", action="screenshot")
        result = asyncio.run(UnifiedNodeExecutor().execute(env))
        assert "approval_required" not in (result.error or "")
