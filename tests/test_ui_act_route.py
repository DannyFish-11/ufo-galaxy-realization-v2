"""tests/test_ui_act_route.py
================================

结构化操作活入口 /api/v1/ui/act:意图+界面图 → 规划 → 派发。
这是把 grounded_planner 从孤岛接进活路径的证明 —— 它现在真被调用了。
"""
from __future__ import annotations

import asyncio

import pytest

import core.routes.ui_act as ui_act
from core.routes.ui_act import UIActRequest
from core.schemas.ui_element import (
    UIActionKind, UIBounds, UIElementNode, UIGraph, UISource,
)


def _wechat_graph() -> dict:
    g = UIGraph(root=UIElementNode(role="window", label="微信", children=[
        UIElementNode(role="edit", label="输入消息", editable=True, clickable=True,
                      node_id="0.0", bounds=UIBounds(x=60, y=2010, width=1000, height=80),
                      actions=[UIActionKind.SET_TEXT]),
        UIElementNode(role="button", label="发送", clickable=True, node_id="0.1",
                      bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                      actions=[UIActionKind.TAP]),
    ]), source=UISource.ANDROID_A11Y, app="com.tencent.mm")
    return g.model_dump()


class _FakeResult:
    success = True
    error = ""
    def to_legacy_dict(self):
        return {"success": True}


class TestUIAct:
    def test_structural_hit_dispatches_via_invoke_node(self, monkeypatch):
        captured = {}

        async def _fake_invoke(node_id, action, params, **kw):
            captured.update(node_id=node_id, action=action, params=params, kw=kw)
            return _FakeResult()

        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        out = asyncio.run(ui_act.ui_act(UIActRequest(
            instruction="点「发送」", ui_graph=_wechat_graph(), node_id="Node_36_UIAWindows")))

        assert out["success"] and out["dispatched"]
        assert out["planned"]["action"] == "tap"
        # tap → UIAWindows 的 click
        assert captured["action"] == "click" and captured["node_id"] == "Node_36_UIAWindows"
        assert captured["params"]["x"] == 1240 and captured["params"]["y"] == 2060
        # ui_graph 随派发流转(结构化界面态)
        assert captured["kw"].get("ui_graph") is not None

    def test_set_text_carries_text(self, monkeypatch):
        captured = {}
        async def _fake_invoke(node_id, action, params, **kw):
            captured.update(action=action, params=params)
            return _FakeResult()
        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        out = asyncio.run(ui_act.ui_act(UIActRequest(
            instruction='在「输入消息」输入「你好」', ui_graph=_wechat_graph(),
            node_id="Node_36_UIAWindows")))
        assert out["dispatched"]
        assert captured["action"] == "type_text" and captured["params"]["text"] == "你好"

    def test_absent_target_needs_model_no_dispatch(self, monkeypatch):
        called = {"invoked": False}
        async def _fake_invoke(*a, **k):
            called["invoked"] = True
            return _FakeResult()
        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        out = asyncio.run(ui_act.ui_act(UIActRequest(
            instruction="点「悬浮球」", ui_graph=_wechat_graph())))
        assert out["needs_model"] and not out["dispatched"]
        assert "悬浮球" in out["grounding_prompt"]
        assert called["invoked"] is False  # 点不准不瞎派发

    def test_dry_run_plans_without_dispatch(self, monkeypatch):
        called = {"invoked": False}
        async def _fake_invoke(*a, **k):
            called["invoked"] = True
            return _FakeResult()
        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        out = asyncio.run(ui_act.ui_act(UIActRequest(
            instruction="点「发送」", ui_graph=_wechat_graph(), execute=False)))
        assert out["planned"]["action"] == "tap" and not out["dispatched"]
        assert called["invoked"] is False

    def test_missing_ui_graph_errors(self):
        out = asyncio.run(ui_act.ui_act(UIActRequest(instruction="点发送")))
        assert not out["success"]


class TestNodeIdSanitization:
    def test_malicious_node_id_falls_back_to_safe_default(self, monkeypatch):
        # node_id 来自不可信请求体;路径穿越形状应被拒,回落安全缺省节点。
        captured = {}
        async def _fake_invoke(node_id, action, params, **kw):
            captured["node_id"] = node_id
            return _FakeResult()
        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        out = asyncio.run(ui_act.ui_act(UIActRequest(
            instruction="点「发送」", ui_graph=_wechat_graph(),
            node_id="../../etc/passwd")))
        assert out["dispatched"]
        assert captured["node_id"] == "Node_36_UIAWindows"  # 非法值未透传

    def test_safe_node_id_helper(self):
        assert ui_act._safe_node_id("Node_36_UIAWindows") == "Node_36_UIAWindows"
        for bad in ("../../x", "Node_36/../y", "/abs/path", "", "evil;rm"):
            assert ui_act._safe_node_id(bad) is None


class TestRouteRegistered:
    def test_router_has_act_endpoint(self):
        paths = {r.path for r in ui_act.router.routes}
        assert "/api/v1/ui/act" in paths
