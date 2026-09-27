"""被接入设备的驱动:同一种设备第二台起直接复用;找驱动先看已经装好的。

走真的接入平面、驱动簿(持久化)、OpenClawd 工具分发入口;只替掉 MCP 网关
「列出已装工具 / 执行工具」这两个边界(断言真的被调到、参数对)。
"""

from __future__ import annotations

import asyncio
import types

import pytest

SONY = {
    "server": "Linux/4.4 UPnP/1.0 Sony-BRAVIA/1.0",
    "device_type_urn": "urn:schemas-upnp-org:device:MediaRenderer:1",
}
LG = {"server": "WebOS/4.1 UPnP/1.0 LG-webOSTV/1.0", "device_type_urn": "urn:schemas-upnp-org:device:MediaRenderer:1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core import autonomy_policy
    from core.device_onboarding.conversation import reset_conversation_confirmations
    from core.device_onboarding.drivers import reset_driver_book
    from core.device_onboarding.service import reset_onboarding_service
    from core.interaction import high_risk_confirmation as hrc
    from core.interaction import pending_decision_registry as pdr
    from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "ob"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    monkeypatch.delenv("GALAXY_ONBOARDING_AUTO", raising=False)
    monkeypatch.setattr(autonomy_policy, "_grants_path", lambda: str(tmp_path / "grants.json"))

    async def watch():
        return ["watch-1"]

    async def approve(**kw):
        return hrc.ConfirmationOutcome(True, "用户已明确批准", "d1", "watch")

    monkeypatch.setattr(pdr, "_discover_target_devices", watch)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", approve)
    resets = (
        reset_unified_device_manager,
        reset_unified_connection_manager,
        reset_onboarding_service,
        reset_auto_enrollment_service,
        reset_conversation_confirmations,
        reset_driver_book,
    )
    for r in resets:
        r()
    yield types.SimpleNamespace(monkeypatch=monkeypatch)
    for r in resets:
        r()


def _agent(tool: str, args: dict) -> dict:
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(
        _capability_dispatcher=None,
        _tool_permission_checker=None,
        _current_session_id="s1",
        _current_device_id="",
        _current_trace_id="",
    )
    return asyncio.run(OpenClawd._dispatch_tool_call(agent, tool, args))


def _tv(key: str, name: str, props: dict):
    from core.device_onboarding.models import Observation
    from core.device_onboarding.service import get_onboarding_service

    return get_onboarding_service().observe(
        Observation(source="ssdp", key=key, name=name, kind_hint="tv", addresses=["192.168.1.9"], properties=props)
    )


def test_the_second_tv_of_the_same_model_joins_with_the_same_driver(env):
    from core import mcp_gateway as mg

    first = _tv("uuid-1", "客厅电视", SONY)
    assert _agent("devices__bind_driver", {"candidate_id": first.candidate_id, "tool": "bravia_control"})["success"]

    second = _tv("uuid-2", "卧室电视", SONY)
    assert (second.join_path, second.human_step) == ("known_mcp_driver", "approve")
    out = _agent("devices__join", {"candidate_id": second.candidate_id})
    assert out["success"] and out["outcome"]["kind"] == "joined", out

    calls = []

    async def execute_tool(tool, arguments, **kw):
        calls.append((tool, arguments["action"]))
        return {"success": True}

    env.monkeypatch.setattr(mg.get_mcp_gateway(), "execute_tool", execute_tool)
    assert _agent("devices__invoke", {"device_id": out["outcome"]["device_id"], "action": "power_on"})["success"]
    assert calls == [("bravia_control", "power_on")]


def test_a_different_model_does_not_get_that_driver(env):
    first = _tv("uuid-1", "客厅电视", SONY)
    _agent("devices__bind_driver", {"candidate_id": first.candidate_id, "tool": "bravia_control"})
    other = _tv("uuid-3", "LG 电视", LG)
    assert other.join_path != "known_mcp_driver"


def test_a_device_nobody_can_tell_the_model_of_is_never_remembered(env):
    from core.device_onboarding.drivers import get_driver_book, kind_key

    vague = _tv("uuid-4", "某个东西", {})
    assert kind_key(vague) is None
    _agent("devices__bind_driver", {"candidate_id": vague.candidate_id, "tool": "some_tool"})
    assert get_driver_book().store.values() == []


def test_what_was_learned_survives_a_restart(env):
    from core.device_onboarding.drivers import reset_driver_book
    from core.device_onboarding.service import reset_onboarding_service

    first = _tv("uuid-1", "客厅电视", SONY)
    _agent("devices__bind_driver", {"candidate_id": first.candidate_id, "tool": "bravia_control"})
    reset_driver_book()
    reset_onboarding_service()
    assert _tv("uuid-5", "书房电视", SONY).join_path == "known_mcp_driver"


def test_looking_for_a_driver_first_checks_what_is_installed(env):
    from core import mcp_gateway as mg
    from core.schemas.contracts import MCPToolDescriptorModel

    async def list_all_tools(filter_tags=None):
        return [
            MCPToolDescriptorModel(name="bravia_control", description="Power, input and volume for Sony BRAVIA TVs"),
            MCPToolDescriptorModel(name="weather", description="Current weather for a city"),
        ]

    env.monkeypatch.setattr(mg.get_mcp_gateway(), "list_all_tools", list_all_tools)
    cand = _tv("uuid-6", "客厅电视", SONY)
    out = _agent("devices__acquire_driver", {"candidate_id": cand.candidate_id})
    assert out["success"]
    assert [m["tool"] for m in out["installed_matches"]] == ["bravia_control"]
    assert "bravia" in out["installed_matches"][0]["matched"]


def test_nothing_installed_matches_says_what_else_to_do(env):
    from core import mcp_gateway as mg

    async def none(filter_tags=None):
        return []

    env.monkeypatch.setattr(mg.get_mcp_gateway(), "list_all_tools", none)
    cand = _tv("uuid-7", "客厅电视", SONY)
    out = _agent("devices__acquire_driver", {"candidate_id": cand.candidate_id})
    assert out["success"] is False and "source_url" in out["error"] and "generate" in out["error"]
