"""智能体的设备工具:看得见、接得进、调得动,需要人的地方一定问人。

走 OpenClawd 真正的工具分发入口(``_dispatch_tool_call``),接入平面、UDM、UCM、
Node_27 全是真的;只在两处边界替身:手表上的确认回答,以及设备/MCP 那一端的传输
(断言它**真的被调到**、参数对)。
"""

from __future__ import annotations

import asyncio
import json
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.device_onboarding.service import get_onboarding_service, reset_onboarding_service

_WORKER = {
    "worker_id": "worker-nas",
    "hostname": "nas",
    "device_type": "linux",
    "capabilities": [{"name": "code_exec"}],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core import autonomy_policy
    from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "ob"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    for k in ("GALAXY_ONBOARDING_AUTO", "HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN", "GALAXY_HEADSCALE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GALAXY_AUTONOMY", "guided")
    monkeypatch.setattr(autonomy_policy, "_grants_path", lambda: str(tmp_path / "grants.json"))
    autonomy_policy.reset_grant_store()
    for r in (
        reset_unified_device_manager,
        reset_unified_connection_manager,
        reset_onboarding_service,
        reset_auto_enrollment_service,
    ):
        r()
    asked: list = []
    yield types.SimpleNamespace(asked=asked, monkeypatch=monkeypatch)
    for r in (
        reset_unified_device_manager,
        reset_unified_connection_manager,
        reset_onboarding_service,
        reset_auto_enrollment_service,
    ):
        r()
    autonomy_policy.reset_grant_store()


def _watch_says(env, approved: bool):
    from core.interaction import high_risk_confirmation as hrc

    async def confirm(**kw):
        env.asked.append(kw["tool_name"])
        return hrc.ConfirmationOutcome(approved, "用户已明确批准" if approved else "用户明确拒绝", "d1", "watch")

    env.monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)


def _agent(tool: str, args: dict) -> dict:
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(
        _capability_dispatcher=None,
        _tool_permission_checker=None,
        _current_session_id="s1",
        _current_device_id="watch-1",
        _current_trace_id="",
    )
    return asyncio.run(OpenClawd._dispatch_tool_call(agent, tool, args))


def _udm():
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager()


def _worker_candidate():
    from core.device_onboarding.sources import _on_worker_register

    asyncio.run(_on_worker_register(_WORKER))
    return _agent("devices__list", {})["candidates"][0]["candidate_id"]


# ── 工具在智能体手里 ────────────────────────────────────────────────────


def test_the_agent_is_offered_the_device_tools():
    import inspect

    from core.device_onboarding.agent_tools import DEVICES_BUILTIN_TOOLS
    from core.openclawd import OpenClawd

    names = {t["function"]["name"] for t in DEVICES_BUILTIN_TOOLS}
    assert {"devices__list", "devices__join", "devices__invoke", "devices__remove", "devices__invite"} <= names
    assert "tools.extend(DEVICES_BUILTIN_TOOLS)" in inspect.getsource(OpenClawd._collect_tools)
    assert '"devices__",' in inspect.getsource(OpenClawd._dispatch_tool_call)


def test_list_shows_members_by_role_and_candidates(env):
    _udm().register_device_from_dict("phone-1", {"device_type": "Android_Agent", "transport": "websocket"})
    _worker_candidate()
    out = _agent("devices__list", {})
    assert out["success"]
    assert [m["device_id"] for m in out["members"]["subjects"]] == ["phone-1"]
    assert out["members"]["subjects"][0]["can_initiate"] is True
    [c] = out["candidates"]
    assert (c["name"], c["join_path"], c["human_step"]) == ("nas", "edge_worker", "approve")


# ── 接入 ────────────────────────────────────────────────────────────────


def test_joining_asks_on_the_watch_and_joins_when_approved(env):
    _watch_says(env, True)
    cid = _worker_candidate()
    out = _agent("devices__join", {"candidate_id": cid})
    assert out["success"] and out["outcome"]["kind"] == "joined"
    assert env.asked == ["把「nas」接入为设备"]
    assert _udm().get_device("worker-nas") is not None


def test_joining_is_refused_when_the_user_says_no(env):
    _watch_says(env, False)
    cid = _worker_candidate()
    out = _agent("devices__join", {"candidate_id": cid})
    assert not out["success"] and "拒绝" in out["error"]
    assert _udm().get_device("worker-nas") is None


def test_physical_steps_come_back_as_what_to_tell_the_user(env):
    from core.lan_discovery import LanDiscovery

    LanDiscovery().ingest_service("_matterc._udp.local.", "PLUG._matterc._udp.local.", "192.168.1.60", 5540, {})
    cid = _agent("devices__list", {})["candidates"][0]["candidate_id"]
    out = _agent("devices__join", {"candidate_id": cid})
    assert "配网码" in out["tell_user"]
    assert out["outcome"]["needs"]["inputs"][0]["name"] == "code"


# ── 调用:按接入方式路由 ────────────────────────────────────────────────


def test_invoke_on_a_native_device_goes_through_the_canonical_dispatcher(env):
    from core import device_communication

    calls = []

    async def send_command(device_id, action, params):
        calls.append((device_id, action, params))
        return {"ok": True}

    env.monkeypatch.setattr(device_communication.device_comm, "send_command", send_command)
    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone", "transport": "websocket"})
    out = _agent("devices__invoke", {"device_id": "phone-1", "action": "screenshot", "params": {"q": 80}})
    assert out["success"], out
    assert calls == [("phone-1", "screenshot", {"q": 80})]


def test_invoke_on_a_home_assistant_device_reaches_home_assistant(env):
    posts = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._ok([{"entity_id": "switch.fan", "state": "off", "attributes": {"friendly_name": "风扇"}}])

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            posts.append((self.path, json.loads(self.rfile.read(n) or b"{}")))
            self._ok([])

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    env.monkeypatch.setenv("HOME_ASSISTANT_URL", url)
    env.monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "t")
    env.monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    from core.ha_bridge import HABridge

    HABridge(url=url, token="t")._mirror_entity(
        {"entity_id": "switch.fan", "state": "off", "attributes": {"friendly_name": "风扇"}}
    )
    try:
        out = _agent("devices__invoke", {"device_id": "ha_switch.fan", "action": "turn_on"})
    finally:
        srv.shutdown()
    assert out["success"], out
    assert posts == [("/api/services/homeassistant/turn_on", {"entity_id": "switch.fan"})]


def test_a_device_with_an_mcp_driver_is_invoked_through_it_after_asking(env):
    from core import mcp_gateway as mg

    _watch_says(env, True)
    calls = []

    async def execute_tool(tool, arguments, **kw):
        calls.append((tool, arguments))
        return {"success": True, "result": "done"}

    env.monkeypatch.setattr(mg.get_mcp_gateway(), "execute_tool", execute_tool)
    svc = get_onboarding_service()
    from core.device_onboarding.models import Observation

    c = svc.observe(
        Observation(source="ssdp", key="uuid-tv", name="客厅电视", kind_hint="tv", addresses=["192.168.1.9"])
    )
    bound = _agent("devices__bind_driver", {"candidate_id": c.candidate_id, "tool": "bravia_control"})
    assert bound["success"]
    out = _agent("devices__invoke", {"device_id": bound["device_id"], "action": "power_on"})
    assert out["success"], out
    assert env.asked == ["对「客厅电视」执行 power_on"]
    [(tool, arguments)] = calls
    assert tool == "bravia_control" and arguments["action"] == "power_on"
    assert arguments["device"]["addresses"] == ["192.168.1.9"]


# ── 移除、邀请、驱动 ────────────────────────────────────────────────────


def test_remove_needs_the_users_ok(env):
    _watch_says(env, False)
    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone"})
    out = _agent("devices__remove", {"device_id": "phone-1"})
    assert not out["success"] and _udm().get_device("phone-1") is not None
    _watch_says(env, True)
    out = _agent("devices__remove", {"device_id": "phone-1"})
    assert out["success"] and _udm().get_device("phone-1") is None


def test_invite_a_phone_gives_a_real_pairing_code(env):
    from core.agent_card import get_pairing_code_registry

    out = _agent("devices__invite", {"kind": "phone"})
    assert out["success"] and out["code"] in out["tell_user"]
    assert get_pairing_code_registry().resolve(out["code"]) == out["link"]


def test_invite_a_computer_without_headscale_says_how_to_fix(env):
    out = _agent("devices__invite", {"kind": "computer"})
    assert not out["success"] and "GALAXY_HEADSCALE_URL" in out["how_to_fix"]


def test_generating_a_driver_is_never_done_without_asking(env):
    from core import mcp_gateway as mg
    from core.device_onboarding.models import Observation

    _watch_says(env, False)
    generated = []

    async def gap(tool, ctx):
        generated.append(tool)
        return {"success": True, "tool_name": tool}

    env.monkeypatch.setattr(mg.get_mcp_gateway(), "handle_capability_gap", gap)
    c = get_onboarding_service().observe(Observation(source="ssdp", key="u2", name="Printer"))
    out = _agent("devices__acquire_driver", {"candidate_id": c.candidate_id, "generate": True})
    assert not out["success"] and generated == []

    _watch_says(env, True)
    out = _agent("devices__acquire_driver", {"candidate_id": c.candidate_id, "generate": True})
    assert out["success"] and generated and out["driver"] == generated[0]


# ── REST(面板) ─────────────────────────────────────────────────────────


def test_rest_overview_join_and_remove(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes.onboarding import create_router

    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)
    cid = _worker_candidate()
    ov = client.get("/api/v1/onboarding/overview").json()
    assert ov["summary"]["candidates"] == 1 and ov["candidates"][0]["candidate_id"] == cid
    r = client.post(f"/api/v1/onboarding/candidates/{cid}/join", json={"inputs": {}})
    assert r.status_code == 200 and r.json()["outcome"]["kind"] == "joined"
    assert client.get("/api/v1/onboarding/overview").json()["summary"]["members"] == 1
    r = client.delete("/api/v1/onboarding/members/worker-nas")
    assert r.status_code == 200 and r.json()["device_table"] is True
    assert client.post("/api/v1/onboarding/candidates/nope/join", json={}).status_code == 404
