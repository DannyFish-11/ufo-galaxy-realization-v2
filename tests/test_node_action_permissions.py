"""tests/test_node_action_permissions.py
===========================================

节点动作权限门禁(manifest 声明 · fail-closed):
  - 声明节点:白名单内放行、名单外拒绝(即使 prompt 注入也无法越权)。
  - 未声明节点:legacy 放行;GALAXY_PERM_STRICT=1 收紧为拒绝。
  - 统一执行器集成:越权动作在加载节点前就被拦下,返回结构化 permission_denial。
"""

from __future__ import annotations

import asyncio

import pytest

import core.node_action_permissions as nap


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    nap.reset_cache()
    monkeypatch.delenv("GALAXY_PERM_STRICT", raising=False)
    yield
    nap.reset_cache()


class TestEvaluate:
    def test_declared_node_allows_whitelisted_action(self):
        d = nap.evaluate_action_permission("Node_36_UIAWindows", "click")
        assert d.allowed and d.declared and d.matched_pattern == "click"

    def test_declared_node_denies_unlisted_action(self):
        # fail-closed:UIAWindows 没声明过 "shell",即使有人(或注入的模型)想调也拦下
        d = nap.evaluate_action_permission("Node_36_UIAWindows", "shell")
        assert not d.allowed and d.declared
        assert "白名单" in d.reason

    def test_adb_shell_is_declared_but_uia_shell_is_not(self):
        # 同名动作按【节点】隔离:ADB 声明了 shell(它的本职),UIA 没有
        assert nap.evaluate_action_permission("Node_33_ADB", "shell").allowed
        assert not nap.evaluate_action_permission("Node_36_UIAWindows", "shell").allowed

    def test_meta_actions_allowed_on_declared_nodes(self):
        for meta in ("help", "status", "health"):
            assert nap.evaluate_action_permission("Node_45_DesktopAuto", meta).allowed

    def test_undeclared_node_legacy_allowed(self):
        d = nap.evaluate_action_permission("Node_00_StateMachine", "anything")
        assert d.allowed and not d.declared

    def test_strict_mode_denies_undeclared(self, monkeypatch):
        monkeypatch.setenv("GALAXY_PERM_STRICT", "1")
        d = nap.evaluate_action_permission("Node_00_StateMachine", "anything")
        assert not d.allowed and not d.declared

    def test_unparseable_node_id_legacy_allowed(self):
        assert nap.evaluate_action_permission("weird-dir", "x").allowed

    def test_new_ui_tree_actions_declared_for_uia(self):
        # 本轮补齐的 System API 动作也在声明里
        for a in ("find_element", "find_elements", "get_ui_tree"):
            assert nap.evaluate_action_permission("Node_36_UIAWindows", a).allowed


class TestExecutorIntegration:
    def test_denied_action_blocked_before_node_load(self):
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor

        env = NodeInvocationEnvelope(node_id="Node_36_UIAWindows", action="format_disk")
        result = asyncio.run(UnifiedNodeExecutor().execute(env))
        assert result.success is False
        assert "permission" in (result.error or "").lower() or "manifest" in (result.error or "")
        denial = (result.eligibility_denial or {}).get("permission_denial", {})
        assert denial.get("allowed") is False and denial.get("declared") is True

    def test_catalog_declares_exactly_verified_nodes(self):
        """声明面钉死:只有**已核实过 dispatch 表**的节点才进来。

        钉死它,是为了让往里加节点成为一个必须解释的动作 —— 声明一个没核实过
        动作面的节点,等于把 fail-closed 变成"按一份猜出来的清单拒绝",比不声明更糟。

        122 是本轮加进来的:它是 **shell 执行节点**,此前一个动作声明都没有,于是
        node_action_permissions 判它"未声明"→ legacy 放行。最需要白名单的那个节点
        恰恰没有白名单。

        它的动作面是核实过的:``nodes/Node_122_Shell/fusion_entry.py`` 的 ``execute``
        自述 available_actions = execute / script / list_processes / kill,加上它自己
        处理的 status / help 两个自述动作。
        """
        table = nap._load_permissions()
        assert set(table.keys()) == {27, 33, 34, 36, 45, 74, 92, 122, 124}
