"""要人点头的操作只经 ``core.approval_gate`` 一个口问 —— 电脑前的人批得了,从哪发起就在哪批。

改之前(第 8 轮读代码 + 实测):默认本地模式只有一台电脑,工具门没连手表就直接拒(「没有已连接的设备可以询问」),
节点拨盘门把请求排进队列、面板上却没有入口 —— 坐在电脑前的人什么都批不了;同一次节点调用先后问两遍;
门禁自己出错就放行;授权写在仓库根目录、粒度只有「节点:动作」、「本会话」其实是进程存活期。

所有者的决定(docs/GROUNDED_AGENT_DESIGN.md §0):电脑发起的在电脑面板上批,手机 / 手表发起的在那边批;
批一次默认记「同一个动作 + 同一个对象」到这段对话结束;「一直允许」要人明确选,面板上能撤。
"""

from __future__ import annotations

import asyncio
import json
import types

import httpx
import pytest

import core.approval_gate as gate
import core.autonomy_policy as ap


@pytest.fixture()
def registry(monkeypatch):
    from core.control_plane import _globals as cp_globals
    from core.control_plane.security_interceptor import ApprovalRegistry

    reg = ApprovalRegistry()
    monkeypatch.setattr(cp_globals, "get_approval_registry", lambda: reg)
    return reg


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(ap, "_LEGACY_GRANTS", str(tmp_path / "legacy_grants.json"))
    monkeypatch.delenv("GALAXY_AUTONOMY", raising=False)
    ap.reset_grant_store()
    monkeypatch.setattr(gate, "publish_pending", lambda: None)
    yield
    ap.reset_grant_store()


@pytest.fixture()
def desktop(monkeypatch):
    """桌面外壳连着(面板 / 覆盖层)。"""
    monkeypatch.setattr(gate, "desktop_reachable", lambda: True)


@pytest.fixture()
def no_desktop(monkeypatch):
    monkeypatch.setattr(gate, "desktop_reachable", lambda: False)


def _approvals_app():
    from fastapi import FastAPI

    from core.routes.approvals import create_router

    app = FastAPI()
    app.include_router(create_router())
    return app


async def _wait_pending(reg, n=1):
    for _ in range(200):
        if len(reg.list_pending()) >= n:
            return reg.list_pending()
        await asyncio.sleep(0.01)
    raise AssertionError("面板上一直没出现待批的那一条")


async def _click(reg, *, approve=True, grant="session"):
    """像面板那样点:先经带鉴权的 GET 拿令牌,再 POST。"""
    (req,) = await _wait_pending(reg)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_approvals_app()), base_url="http://t") as c:
        listed = (await c.get("/api/v1/approvals")).json()["approvals"]
        token = listed[0]["ack_token"]
        body = {"action": "approve", "token": token, "grant": grant} if approve else {"action": "deny"}
        r = await c.post(f"/api/v1/approvals/{req.request_id}", json=body)
        assert r.status_code == 200, r.text
    return req


# ── 电脑前的人批得了 ─────────────────────────────────────────────────────


def test_the_computer_panel_can_approve_and_the_call_goes_ahead(registry, desktop):
    async def run():
        ask = asyncio.create_task(
            gate.request_approval(
                key="tool:mcp__fs__delete_file", target="/tmp/a.txt", what="删 a.txt", session_id="s1"
            )
        )
        await _click(registry)
        return await ask

    out = asyncio.run(run())
    assert out.approved and out.source == "desktop" and out.scope == "session"
    assert registry.list_pending() == [], "批完了面板上那一条该收掉"


def test_once_approved_the_same_action_on_the_same_object_is_not_asked_again_in_this_conversation(registry, desktop):
    async def run():
        ask = asyncio.create_task(gate.request_approval(key="tool:x", target="A", what="做 x", session_id="s1"))
        await _click(registry)
        assert (await ask).approved
        again = await asyncio.wait_for(gate.request_approval(key="tool:x", target="A", session_id="s1"), timeout=2)
        other_obj = asyncio.create_task(gate.request_approval(key="tool:x", target="B", session_id="s1", timeout_s=1))
        other_conv = asyncio.create_task(gate.request_approval(key="tool:x", target="A", session_id="s2", timeout_s=1))
        return again, await other_obj, await other_conv

    again, other_obj, other_conv = asyncio.run(run())
    assert again.approved and again.source == "grant:session"
    assert not other_obj.approved, "换了一个对象就不算批过"
    assert not other_conv.approved, "换了一段对话就不算批过"


def test_saying_no_on_the_panel_means_it_does_not_run(registry, desktop):
    async def run():
        ask = asyncio.create_task(gate.request_approval(key="tool:x", what="做 x"))
        await _click(registry, approve=False)
        return await ask

    out = asyncio.run(run())
    assert not out.approved and "拒绝" in out.reason


def test_nobody_clicking_is_not_an_approval(registry, desktop):
    from core.control_plane.security_interceptor import ApprovalStatus

    out = asyncio.run(gate.request_approval(key="tool:x", what="做 x", timeout_s=1))
    assert not out.approved and "没有人批" in out.reason
    assert registry.list_pending() == []
    assert registry.get_request(out.request_id).status == ApprovalStatus.TIMED_OUT


def test_only_once_is_not_remembered(registry, desktop):
    async def run():
        ask = asyncio.create_task(gate.request_approval(key="tool:x", target="A", session_id="s1"))
        await _click(registry, grant="once")
        assert (await ask).approved
        return await gate.request_approval(key="tool:x", target="A", session_id="s1", timeout_s=1)

    assert not asyncio.run(run()).approved


def test_always_survives_a_restart_and_can_be_revoked(registry, desktop):
    async def run():
        ask = asyncio.create_task(gate.request_approval(key="tool:x", target="A", session_id="s1"))
        await _click(registry, grant="always")
        return await ask

    assert asyncio.run(run()).approved
    ap.reset_grant_store()  # 模拟重启
    assert ap.get_grant_store().check_key("tool:x", "A", "another-conversation") == "always"
    assert ap.get_grant_store().revoke("tool:x@A")
    assert ap.get_grant_store().check_key("tool:x", "A", "s1") is None


def test_no_desktop_shell_and_no_watch_is_refused_at_once_not_after_a_timeout(registry, no_desktop, monkeypatch):
    import core.interaction.pending_decision_registry as hitl

    async def _none():
        return []

    monkeypatch.setattr(hitl, "_discover_target_devices", _none)
    out = asyncio.run(asyncio.wait_for(gate.request_approval(key="tool:x", what="做 x"), timeout=2))
    assert not out.approved and "没有已连接的设备" in out.reason
    assert registry.list_pending() == []


# ── 从哪发起就在哪批 ─────────────────────────────────────────────────────


def _bind_session(desktop_originated: bool, origin: str = ""):
    from core.liminal_activity import bind_runtime_session

    session = types.SimpleNamespace(
        desktop_originated=desktop_originated, origin_device_id=origin, runtime_session_id="rt-1"
    )
    return bind_runtime_session(session)


def test_a_request_from_the_watch_is_asked_on_that_watch_not_on_the_computer(registry, desktop, monkeypatch):
    from core.interaction import high_risk_confirmation as hrc

    asked = []

    async def confirm(**kw):
        asked.append(kw)
        return hrc.ConfirmationOutcome(True, "用户已明确批准", "dec-1", "watch")

    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind_session(False, "watch-1")
        return await gate.request_approval(key="tool:x", what="开灯")

    out = asyncio.run(run())
    assert out.approved and out.source == "device"
    assert asked[0]["devices"] == ["watch-1"], "只问发起的那块手表"
    assert registry.list_pending() == [], "不在电脑面板上另起一条"


def test_a_request_from_the_computer_is_asked_on_the_computer_even_with_a_watch_around(registry, desktop, monkeypatch):
    from core.interaction import high_risk_confirmation as hrc

    async def confirm(**kw):  # pragma: no cover - 被调用即失败
        raise AssertionError("电脑发起的不该去问手表")

    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind_session(True)
        ask = asyncio.create_task(gate.request_approval(key="tool:x", what="做 x"))
        await _click(registry)
        return await ask

    assert asyncio.run(run()).source == "desktop"


def test_a_watch_that_cannot_be_reached_falls_back_to_the_computer(registry, desktop, monkeypatch):
    from core.interaction import high_risk_confirmation as hrc

    async def confirm(**kw):
        return hrc.ConfirmationOutcome(False, "没有已连接的设备可以询问", source="unreachable")

    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)

    async def run():
        _bind_session(False, "watch-1")
        ask = asyncio.create_task(gate.request_approval(key="tool:x", what="做 x"))
        await _click(registry)
        return await ask

    assert asyncio.run(run()).source == "desktop"


# ── 一次调用只问一次 ─────────────────────────────────────────────────────


def test_a_node_call_approved_at_the_tool_gate_is_not_asked_again_at_the_node_gate(registry, desktop):
    params = {"x": 10, "y": 20}

    async def dispatch():
        """一次工具调用的派发:先过工具门,再走到节点门 —— 真实派发里两步在同一个任务里。"""
        key = gate.tool_key("node__Node_36_UIAWindows__click", {"params": params})
        assert (await gate.request_approval(key=key, target="", what="点一下")).approved
        return await gate.gate_node_call("Node_36_UIAWindows", "click", params)

    async def run():
        call = asyncio.create_task(dispatch())
        await _click(registry, grant="once")  # 人在面板上点(另一次 HTTP 请求)
        return await call

    verdict = asyncio.run(run())
    assert verdict.proceed, verdict.error
    assert registry.list_pending() == [], "节点门不该再排一条"


def test_the_pre_approval_does_not_leak_to_the_next_call(registry, desktop):
    """「这一次批过」只给这一次:用掉就没了,下一次同样的调用照样要问(选的是「只这一次」)。"""

    async def dispatch():
        key = gate.node_key("Node_36_UIAWindows", "click")
        assert (await gate.request_approval(key=key, what="点一下")).approved
        first = await gate.gate_node_call("Node_36_UIAWindows", "click", {})
        second = await gate.gate_node_call("Node_36_UIAWindows", "click", {})
        return first, second

    async def run():
        call = asyncio.create_task(dispatch())
        await _click(registry, grant="once")
        return await call

    first, second = asyncio.run(run())
    assert first.proceed
    assert not second.proceed and second.error.startswith("approval_required")


def test_the_tool_name_and_the_node_id_give_the_same_key():
    assert gate.tool_key("node__36__click") == gate.node_key("Node_36_UIAWindows", "click") == "node:36:click"
    assert gate.tool_key("node__08__execute") == gate.node_key("Node_08_Fetch", "execute")
    # 分派型动作:开灯和关灯不是同一个动作
    assert gate.node_key("Node_27_SmartHome", "control", {"action": "on"}) != gate.node_key(
        "Node_27_SmartHome", "control", {"action": "off"}
    )


def test_an_interactive_node_call_is_asked_on_the_spot(registry, desktop):
    async def run():
        with gate.interactive():
            call = asyncio.create_task(gate.gate_node_call("Node_36_UIAWindows", "click", {"x": 1}))
            await _click(registry)
            return await call

    assert asyncio.run(run()).proceed


def test_a_non_interactive_node_call_is_queued_and_the_panel_sees_it(registry):
    verdict = asyncio.run(gate.gate_node_call("Node_36_UIAWindows", "click", {"x": 1}))
    assert not verdict.proceed and verdict.error.startswith("approval_required")
    (req,) = registry.list_pending()
    assert req.context["approval_key"] == "node:36:click"


# ── 门坏了不等于门开着 ───────────────────────────────────────────────────


class _BrokenChecker:
    def check(self, **kw):
        raise RuntimeError("策略表坏了")


def test_a_broken_tool_gate_refuses_instead_of_letting_it_through():
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(
        _capability_dispatcher=None,
        _tool_permission_checker=_BrokenChecker(),
        _current_session_id="s",
        _current_device_id="",
        _current_trace_id="",
    )
    out = asyncio.run(OpenClawd._dispatch_tool_call(agent, "mcp__fs__delete_file", {"path": "/x"}))
    assert out["success"] is False and "权限检查出错" in out["error"]


def test_a_broken_dispatcher_gate_refuses_instead_of_letting_it_through():
    from core.capabilities.canonical_dispatcher import CanonicalDispatcher

    d = CanonicalDispatcher(tool_permission_checker=_BrokenChecker())
    result = d._check_permission("mcp__fs__delete_file", "s", "")
    assert result is not None and result.success is False and "权限检查出错" in result.error


def test_a_broken_autonomy_gate_refuses_writes_but_lets_reads_through(monkeypatch):
    from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor

    async def broken(*a, **kw):
        raise RuntimeError("拨盘门坏了")

    monkeypatch.setattr(gate, "gate_node_call", broken)
    write = asyncio.run(
        UnifiedNodeExecutor().execute(NodeInvocationEnvelope(node_id="Node_36_UIAWindows", action="click"))
    )
    assert write.success is False and (write.error or "").startswith("gate_fault")
    read = asyncio.run(
        UnifiedNodeExecutor().execute(NodeInvocationEnvelope(node_id="Node_36_UIAWindows", action="screenshot"))
    )
    assert not (read.error or "").startswith("gate_fault"), "读操作不因门禁故障被拦"


# ── 授权落在数据目录 ─────────────────────────────────────────────────────


def test_grants_live_in_the_data_directory(tmp_path):
    st = ap.get_grant_store()
    st.grant_key("tool:x", "always", target="A")
    assert (tmp_path / "data" / "approval_grants.json").exists()


def test_an_old_grant_file_in_the_repo_root_keeps_working(tmp_path):
    legacy = tmp_path / "legacy_grants.json"
    legacy.write_text(json.dumps({"always": {"Node_36_UIAWindows:click": {"node_id": "Node_36_UIAWindows"}}}))
    ap.reset_grant_store()
    assert ap.get_grant_store().check_key("node:36:click", "", "") == "always"
    assert not ap.evaluate_autonomy("Node_36_UIAWindows", "click").needs_approval


# ── 面板收到的那一帧不带令牌 ─────────────────────────────────────────────


def test_the_ws_frame_carries_no_token(registry, desktop):
    async def run():
        ask = asyncio.create_task(gate.request_approval(key="tool:x", target="A", what="做 x", timeout_s=1))
        (req,) = await _wait_pending(registry)
        snapshot = gate.frame()
        await ask
        return req, snapshot

    req, snapshot = asyncio.run(run())
    assert snapshot["type"] == "approvals"
    (row,) = snapshot["payload"]["pending"]
    assert row["what"] == "做 x" and row["target"] == "A" and row["waiting"] is True
    assert req.ack_token not in json.dumps(snapshot)


# ── 工具的时间预算留得出等人、跑长任务的时间 ─────────────────────────────


def test_tool_budgets_leave_room_for_a_person_and_for_long_tasks(monkeypatch):
    from core.interaction.high_risk_confirmation import _timeout_s
    from core.tool_permissions import DEFAULT_TOOL_TIMEOUT_S, tool_call_timeout_s

    monkeypatch.setenv("GALAXY_AUTONOMY", "guided")
    # 节点工具本身不要确认,但它落到的敏感节点写操作要人点头
    assert tool_call_timeout_s("node__36__click", {"x": 1}) >= _timeout_s()
    assert tool_call_timeout_s("node__36__screenshot", {}) == DEFAULT_TOOL_TIMEOUT_S
    # 多步桌面任务:每步规划就可能要 60 秒
    assert tool_call_timeout_s("computer_use__run", {"instruction": "x", "max_steps": 10}) >= 10 * 60
    # 带验证的补丁:harness 当场跑验证
    assert tool_call_timeout_s("engineer__apply", {"proposal_id": "p", "verify_command": "pytest"}) >= 600
    assert tool_call_timeout_s("engineer__apply", {"proposal_id": "p"}) == DEFAULT_TOOL_TIMEOUT_S
    assert tool_call_timeout_s("github__install", {"url": "https://github.com/a/b"}) > _timeout_s()
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    assert tool_call_timeout_s("node__36__click", {"x": 1}) == DEFAULT_TOOL_TIMEOUT_S


def test_the_agents_own_tools_are_graded():
    from core.tool_permissions import ToolPermissionChecker

    c = ToolPermissionChecker()
    assert c.check("engineer__context").risk_level == "safe"
    assert c.check("memory__recall").risk_level == "safe"
    assert c.check("computer_use__run").risk_level == "moderate"
    assert c.requires_confirmation_for("mcp__fs__delete_file")
    assert c.check("mcp__sh__run_command").risk_level == "critical"
