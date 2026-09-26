"""智能体能不能真的开关家里的设备 —— 从智能体的工具调用一路走到 Home Assistant。

链路:智能体调 ``home__control`` → OpenClawd 内联分发 → core.smart_home_tools
→ 统一执行器 invoke_node("Node_27_SmartHome", "control") → 权限白名单 → 自治档位
→ fusion_entry → SmartHomeService → HA ``POST /api/services/<domain>/<service>``。

HA 用一个本地假服务器顶替,断言它**真的收到了**带 entity_id 与令牌的那次调用;
除此之外全是真代码,不打桩统一执行器、白名单或节点。
"""

from __future__ import annotations

import asyncio
import json
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core import smart_home_tools as sht

STATES = [
    {"entity_id": "light.living_room", "state": "off", "attributes": {"friendly_name": "客厅灯"}},
    {"entity_id": "light.bedroom", "state": "on", "attributes": {"friendly_name": "卧室灯"}},
    {"entity_id": "switch.bedroom_fan", "state": "off", "attributes": {"friendly_name": "卧室风扇"}},
]


class _FakeHA:
    def __init__(self, token: str = "ha-token"):
        self.calls = []
        self.token = token
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                return self.headers.get("Authorization") == f"Bearer {outer.token}"

            def do_GET(self):
                outer.calls.append(("GET", self.path, None))
                if not self._authed():
                    return self._reply({"message": "unauthorized"}, 401)
                self._reply(STATES if self.path == "/api/states" else {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.calls.append(("POST", self.path, body))
                if not self._authed():
                    return self._reply({"message": "unauthorized"}, 401)
                self._reply([])

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def posts(self):
        return [(p, b) for m, p, b in self.calls if m == "POST"]


@pytest.fixture
def ha(monkeypatch, tmp_path):
    fake = _FakeHA()
    monkeypatch.setenv("HOME_ASSISTANT_URL", fake.url)
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "ha-token")
    monkeypatch.setenv("GALAXY_AUTONOMY", "guided")
    from core import autonomy_policy
    from core.control_plane import _globals as cp_globals
    from core.control_plane.security_interceptor import ApprovalRegistry

    # 授权与审批队列隔离到本用例:不读写仓库里的 .galaxy_grants.json、不串用例。
    monkeypatch.setattr(autonomy_policy, "_grants_path", lambda: str(tmp_path / "grants.json"))
    autonomy_policy.reset_grant_store()
    monkeypatch.setattr(cp_globals, "get_approval_registry", _fresh_registry(ApprovalRegistry))
    yield fake
    autonomy_policy.reset_grant_store()
    fake.server.shutdown()


def _fresh_registry(cls):
    reg = cls()
    return lambda: reg


def _approve_on_watch(monkeypatch, approved: bool, asked: list):
    from core.interaction import high_risk_confirmation as hrc

    async def confirm(**kw):
        asked.append(kw)
        return hrc.ConfirmationOutcome(approved, "用户已明确批准" if approved else "用户明确拒绝", "dec-1", "watch")

    monkeypatch.setattr(hrc, "confirm_high_risk_tool", confirm)


def _agent_call(tool: str, args: dict) -> dict:
    """走 OpenClawd 真正的工具分发入口,而不是直接调模块函数。"""
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(
        _capability_dispatcher=None,
        _tool_permission_checker=None,
        _current_session_id="sess-home",
        _current_device_id="watch-1",
        _current_trace_id="",
    )
    return asyncio.run(OpenClawd._dispatch_tool_call(agent, tool, args))


# ── 工具出现在智能体手里 ──────────────────────────────────────────────────


def test_tools_appear_only_when_home_assistant_is_configured(monkeypatch):
    monkeypatch.delenv("HOME_ASSISTANT_URL", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)
    assert not sht.home_tools_enabled()
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "t")
    assert sht.home_tools_enabled()
    names = {t["function"]["name"] for t in sht.HOME_BUILTIN_TOOLS}
    assert names == {"home__devices", "home__control", "home__scene"}


def test_openclawd_offers_the_tools_and_routes_the_prefix():
    import inspect

    from core.openclawd import OpenClawd

    collect = inspect.getsource(OpenClawd._collect_tools)
    assert "if home_tools_enabled():" in collect and "tools.extend(HOME_BUILTIN_TOOLS)" in collect
    dispatch = inspect.getsource(OpenClawd._dispatch_tool_call)
    # 必须走内联:CanonicalDispatcher 不认 home__ 前缀,委派过去就是"未知工具前缀"。
    assert '"home__",' in dispatch and 'tool_name.startswith("home__")' in dispatch


# ── 整条链路 ──────────────────────────────────────────────────────────────


def test_listing_devices_reads_home_assistant_without_asking(ha, monkeypatch):
    asked = []
    _approve_on_watch(monkeypatch, True, asked)
    out = _agent_call("home__devices", {"query": "卧室"})
    assert out["success"], out
    assert {d["entity_id"] for d in out["devices"]} == {"light.bedroom", "switch.bedroom_fan"}
    assert asked == []  # 读状态不打扰人


def test_turning_on_a_light_by_name_reaches_home_assistant_after_watch_approval(ha, monkeypatch):
    asked = []
    _approve_on_watch(monkeypatch, True, asked)
    out = _agent_call("home__control", {"device": "客厅灯", "action": "on"})
    assert out["success"], out
    assert out["entity_id"] == "light.living_room"
    assert ha.posts() == [("/api/services/homeassistant/turn_on", {"entity_id": "light.living_room"})]
    assert len(asked) == 1 and "客厅灯" in asked[0]["tool_name"]


def test_the_approval_is_for_this_one_time_only(ha, monkeypatch):
    asked = []
    _approve_on_watch(monkeypatch, True, asked)
    _agent_call("home__control", {"device": "light.living_room", "action": "on"})
    _agent_call("home__control", {"device": "light.living_room", "action": "off"})
    assert len(asked) == 2
    assert [p for p, _ in ha.posts()] == [
        "/api/services/homeassistant/turn_on",
        "/api/services/homeassistant/turn_off",
    ]


def test_denied_on_the_watch_means_nothing_is_sent(ha, monkeypatch):
    asked = []
    _approve_on_watch(monkeypatch, False, asked)
    out = _agent_call("home__control", {"device": "light.living_room", "action": "on"})
    assert not out["success"]
    assert "拒绝" in out["error"]
    assert ha.posts() == []


def test_autonomous_level_does_not_ask(ha, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    asked = []
    _approve_on_watch(monkeypatch, True, asked)
    out = _agent_call("home__control", {"device": "light.bedroom", "action": "set_brightness", "params": {"brightness_pct": 30}})
    assert out["success"], out
    assert ha.posts() == [("/api/services/light/turn_on", {"entity_id": "light.bedroom", "brightness_pct": 30})]
    assert asked == []


def test_device_list_id_is_accepted(ha, monkeypatch):
    # 设备列表里 HA 实体的 device_id 形如 ha_<entity_id>(core/ha_bridge.py)
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    out = _agent_call("home__control", {"device": "ha_switch.bedroom_fan", "action": "toggle"})
    assert out["success"], out
    assert ha.posts() == [("/api/services/homeassistant/toggle", {"entity_id": "switch.bedroom_fan"})]


def test_ambiguous_name_is_not_guessed(ha, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    out = _agent_call("home__control", {"device": "卧室", "action": "off"})
    assert not out["success"]
    assert {c["entity_id"] for c in out["candidates"]} == {"light.bedroom", "switch.bedroom_fan"}
    assert ha.posts() == []


def test_home_assistant_rejecting_the_token_is_a_failure_not_success(ha, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "wrong")
    out = _agent_call("home__control", {"device": "light.living_room", "action": "on"})
    assert not out["success"]
    assert "Home Assistant" in out["error"] or "401" in out["error"] or "unauthorized" in out["error"]


def test_token_saved_in_the_panel_takes_effect_without_restart(ha, monkeypatch):
    """Node_27 的模块只导入一次;面板保存后改的是环境变量,必须每次重读。"""
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "wrong")
    assert not _agent_call("home__control", {"device": "light.living_room", "action": "on"})["success"]
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "ha-token")
    assert _agent_call("home__control", {"device": "light.living_room", "action": "on"})["success"]


def test_scene_goes_through_the_same_gate(ha, monkeypatch):
    asked = []
    _approve_on_watch(monkeypatch, True, asked)
    out = _agent_call("home__scene", {"scene": "scene.movie_night"})
    assert out["success"], out
    assert ha.posts() == [("/api/services/scene/turn_on", {"entity_id": "scene.movie_night"})]
    assert len(asked) == 1


def test_not_configured_says_where_to_fill_it(monkeypatch):
    monkeypatch.delenv("HOME_ASSISTANT_URL", raising=False)
    out = asyncio.run(sht.dispatch_home_tool("control", {"device": "light.x", "action": "on"}))
    assert not out["success"] and "HOME_ASSISTANT_URL" in out["error"]


# ── 面板能填 ──────────────────────────────────────────────────────────────


def test_home_assistant_settings_are_in_the_panel_and_the_token_is_a_secret():
    from core.routes.config_schema_registry import CONFIG_SCHEMA

    assert CONFIG_SCHEMA["HOME_ASSISTANT_URL"]["category"] == "devices"
    assert CONFIG_SCHEMA["HOME_ASSISTANT_TOKEN"]["type"] == "password"
    from core.config_schema import classify_key

    assert classify_key("HOME_ASSISTANT_TOKEN") == "secret"


def test_turning_the_bridge_off_in_the_panel_turns_it_off(monkeypatch):
    from core.ha_bridge import ha_bridge_enabled

    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "t")
    monkeypatch.setenv("GALAXY_HA_BRIDGE", "false")  # 面板存布尔值的写法
    assert not ha_bridge_enabled()
    monkeypatch.setenv("GALAXY_HA_BRIDGE", "true")
    assert ha_bridge_enabled()


def test_saving_home_assistant_settings_reconnects_the_bridge(ha, monkeypatch):
    """面板保存 → restart_ha_bridge:按新地址重新拉一遍设备;关掉开关则停下。"""
    from core import ha_bridge

    async def go():
        first = await ha_bridge.restart_ha_bridge()
        monkeypatch.setenv("GALAXY_HA_BRIDGE", "false")
        second = await ha_bridge.restart_ha_bridge()
        return first, second

    first, second = asyncio.run(go())
    assert first["status"] == "ok" and first["mirrored"] == len(STATES)
    assert ("GET", "/api/states", None) in ha.calls
    assert second == {"status": "disabled"}
    assert ha_bridge._bridge_instance is None


def test_the_settings_page_save_calls_the_reconnect():
    import inspect

    from core.routes import config as config_routes

    src = inspect.getsource(config_routes)
    assert '{"HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN", "GALAXY_HA_BRIDGE"}' in src
    assert "await restart_ha_bridge()" in src


def test_turning_lan_discovery_off_in_the_panel_turns_it_off(monkeypatch):
    from core.lan_discovery import lan_discovery_enabled

    monkeypatch.setenv("GALAXY_LAN_DISCOVERY", "false")
    assert not lan_discovery_enabled()
