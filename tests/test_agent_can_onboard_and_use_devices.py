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

#: 一块插在主脑上的板子 —— 用它当"需要同意一下"的候选样本。
#: (NATS worker 不是发现来源,见 core/device_onboarding/sources.py 模块头。)
_SERIAL = {"device": "/dev/ttyACM0", "vid": "2341", "pid": "0043", "serial_number": "758", "product": "nas"}
_SERIAL_ID = "serial-usb-2341-0043-758"
_SERIAL_NAME = "nas(/dev/ttyACM0)"


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
    """手表连着,并且在手表上这样回答。"""
    from core.interaction import high_risk_confirmation as hrc
    from core.interaction import pending_decision_registry as pdr

    async def confirm(**kw):
        env.asked.append(kw["tool_name"])
        return hrc.ConfirmationOutcome(approved, "用户已明确批准" if approved else "用户明确拒绝", "d1", "watch")

    async def watch_is_there():
        return ["watch-1"]

    env.monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)
    env.monkeypatch.setattr(pdr, "_discover_target_devices", watch_is_there)


async def OpenClawd_dispatch(tool: str, args: dict) -> dict:
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(
        _capability_dispatcher=None,
        _tool_permission_checker=None,
        _current_session_id="s1",
        _current_device_id="watch-1",
        _current_trace_id="",
    )
    return await OpenClawd._dispatch_tool_call(agent, tool, args)


def _agent(tool: str, args: dict) -> dict:
    return asyncio.run(OpenClawd_dispatch(tool, args))


def _udm():
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager()


def _serial_candidate():
    from core.device_onboarding import local_buses as lb

    get_onboarding_service().observe(lb.serial_observation(_SERIAL))
    return _agent("devices__list", {})["candidates"][0]["candidate_id"]


# ── 工具在智能体手里 ────────────────────────────────────────────────────


def test_the_agent_is_offered_the_device_tools():
    import inspect

    from core.device_onboarding.agent_tools import DEVICES_BUILTIN_TOOLS
    from core.openclawd import OpenClawd

    names = {t["function"]["name"] for t in DEVICES_BUILTIN_TOOLS}
    assert {"devices__list", "devices__join", "devices__invoke", "devices__remove", "devices__invite"} <= names
    [invite] = [t for t in DEVICES_BUILTIN_TOOLS if t["function"]["name"] == "devices__invite"]
    assert invite["function"]["parameters"]["properties"]["kind"]["enum"] == ["phone", "watch", "laptop", "worker"]
    assert "tools.extend(devices_tools_for_agent())" in inspect.getsource(OpenClawd._collect_tools)
    assert '"devices__",' in inspect.getsource(OpenClawd._dispatch_tool_call)


def test_list_shows_members_by_role_and_candidates(env):
    _udm().register_device_from_dict("phone-1", {"device_type": "Android_Agent", "transport": "websocket"})
    _serial_candidate()
    out = _agent("devices__list", {})
    assert out["success"]
    assert [m["device_id"] for m in out["members"]["subjects"]] == ["phone-1"]
    assert out["members"]["subjects"][0]["can_initiate"] is True
    [c] = out["candidates"]
    assert (c["name"], c["join_path"], c["human_step"]) == (_SERIAL_NAME, "local_bus", "approve")


# ── 接入 ────────────────────────────────────────────────────────────────


def test_joining_asks_on_the_watch_and_joins_when_approved(env):
    _watch_says(env, True)
    cid = _serial_candidate()
    out = _agent("devices__join", {"candidate_id": cid})
    assert out["success"] and out["outcome"]["kind"] == "joined"
    assert env.asked == [f"把「{_SERIAL_NAME}」接入为设备"]
    assert _udm().get_device(_SERIAL_ID) is not None


def test_joining_is_refused_when_the_user_says_no(env):
    _watch_says(env, False)
    cid = _serial_candidate()
    out = _agent("devices__join", {"candidate_id": cid})
    assert not out["success"] and "拒绝" in out["error"]
    assert _udm().get_device(_SERIAL_ID) is None


def test_physical_steps_come_back_as_what_to_tell_the_user(env):
    from core.lan_discovery import LanDiscovery

    LanDiscovery().ingest_service("_matterc._udp.local.", "PLUG._matterc._udp.local.", "192.168.1.60", 5540, {})
    cid = _agent("devices__list", {})["candidates"][0]["candidate_id"]
    out = _agent("devices__join", {"candidate_id": cid})
    assert "配网码" in out["tell_user"]
    assert out["outcome"]["needs"]["inputs"][0]["name"] == "code"


# ── 调用:按接入方式路由 ────────────────────────────────────────────────


def test_invoke_on_a_native_device_goes_through_ucm_and_returns_the_devices_answer(env):
    """原生设备(连在规范入口上的手机/电脑)经 UCM 下发、等它回包。

    以前走 core.device_communication.device_comm —— 生产里从没有设备连进那张表,
    每次都是「设备未连接」,外层却报成功。
    """
    from core.unified.connection_manager import get_unified_connection_manager

    ucm = get_unified_connection_manager()
    sent = []

    class Phone:
        async def send_json(self, msg):
            sent.append(msg)
            reply = {"type": "command_result", "command_id": msg["command_id"], "payload": {"success": True, "q": 80}}
            asyncio.get_running_loop().call_soon(ucm.resolve_command_response, msg["command_id"], reply)

    async def go():
        await ucm.register_connection("phone-1", Phone(), {})
        return await OpenClawd_dispatch(
            "devices__invoke", {"device_id": "phone-1", "action": "screenshot", "params": {"q": 80}}
        )

    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone", "transport": "websocket"})
    out = asyncio.run(go())
    assert out["success"], out
    assert out["result"] == {"success": True, "q": 80}
    [msg] = sent
    assert (msg["type"], msg["command"], msg["params"]) == ("command", "screenshot", {"q": 80})


def test_invoke_on_a_device_that_is_not_connected_says_so_instead_of_success(env):
    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone", "transport": "websocket"})
    out = _agent("devices__invoke", {"device_id": "phone-1", "action": "screenshot"})
    assert out["success"] is False and "没有连接" in out["error"]


def test_a_device_that_answers_failure_is_reported_as_failure(env):
    from core.unified.connection_manager import get_unified_connection_manager

    ucm = get_unified_connection_manager()

    class Phone:
        async def send_json(self, msg):
            reply = {"command_id": msg["command_id"], "payload": {"success": False, "error": "屏幕锁着"}}
            asyncio.get_running_loop().call_soon(ucm.resolve_command_response, msg["command_id"], reply)

    async def go():
        await ucm.register_connection("phone-1", Phone(), {})
        return await OpenClawd_dispatch("devices__invoke", {"device_id": "phone-1", "action": "tap"})

    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone", "transport": "websocket"})
    out = asyncio.run(go())
    assert out["success"] is False and "屏幕锁着" in out["error"]


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


def test_invite_a_worker_without_headscale_says_how_to_fix(env):
    out = _agent("devices__invite", {"kind": "worker"})
    assert not out["success"] and "GALAXY_HEADSCALE_URL" in out["how_to_fix"]


def test_invite_a_laptop_gives_one_command_with_a_real_pairing_code(env):
    from core.agent_card import get_pairing_code_registry

    out = _agent("devices__invite", {"kind": "laptop"})
    assert out["success"] and out["human_step"] == "run_command"
    short, full = out["commands"]
    assert short == f"python -m device_client --pair {out['code']} --install-autostart"
    assert full.startswith(f"python -m device_client --pair {out['code']} --gateway http")
    assert short in out["tell_user"] and full in out["tell_user"]
    assert get_pairing_code_registry().resolve(out["code"]) is not None


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
    cid = _serial_candidate()
    ov = client.get("/api/v1/onboarding/overview").json()
    assert ov["summary"]["candidates"] == 1 and ov["candidates"][0]["candidate_id"] == cid
    r = client.post(f"/api/v1/onboarding/candidates/{cid}/join", json={"inputs": {}})
    assert r.status_code == 200 and r.json()["outcome"]["kind"] == "joined"
    assert client.get("/api/v1/onboarding/overview").json()["summary"]["members"] == 1
    r = client.delete(f"/api/v1/onboarding/members/{_SERIAL_ID}")
    assert r.status_code == 200 and r.json()["device_table"] is True
    assert client.post("/api/v1/onboarding/candidates/nope/join", json={}).status_code == 404
