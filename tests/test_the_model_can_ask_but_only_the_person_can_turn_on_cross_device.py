"""模型可以**请求**打开跨设备模式，批准只归人。

走真的：OpenClawd 的工具收集与分发入口、``RuntimeSession`` 经真正的 ``bind_runtime_session`` 挂进请求上下文、
面板按钮同一个写入函数。只替掉面板推送、手表发现、和 ``.env`` 的落点。

守的规则：
1. 只在本地模式下出现这个工具；已经是跨设备模式就不广告一个死工具；
2. 它不挂在设备接入开关底下（按钮关着那个开关也是关的，请求不能跟着没了）；
3. 没人批准就一个键都不写；
4. 问的那一回合里再调一次不算答应（模型不能自己批准自己）；
5. 后台自发的回合连提出都不行，也不能批准；来源不明（不在一次请求里）不算；
6. 看人的原话：明确的「好」才算，「不要」算拒绝；
7. ``GALAXY_ONBOARDING_AUTO=approve`` 对它无效，永远要问；
8. 批准后写出的结果和面板按钮一模一样，回话里说明要重启；
9. 手表连着时在手表上问。
"""

from __future__ import annotations

import asyncio
import os
import types

import pytest

from core.routes import config as cfg
from core.routes.config_bundles import CONFIG_BUNDLES, owned_keys
from core.routes.config_schema_registry import CONFIG_SCHEMA

TOOL = "devices__request_cross_device"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import core.lumiv_websocket_bridge as lwb
    from core.device_onboarding.conversation import reset_conversation_confirmations
    from core.interaction import pending_decision_registry as pdr

    saved = dict(os.environ)
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    for bundle in CONFIG_BUNDLES:
        for key in owned_keys(bundle, CONFIG_SCHEMA.keys()):
            os.environ.pop(key, None)
    for key in ("GALAXY_SYSTEM_MODE", "GALAXY_NATS_URL", "GALAXY_ONBOARDING_AUTO"):
        os.environ.pop(key, None)

    async def no_watch():
        return []

    monkeypatch.setattr(pdr, "_discover_target_devices", no_watch)
    said: list = []
    monkeypatch.setattr(lwb, "emit_conversation", lambda role, text, **kw: said.append(text))
    reset_conversation_confirmations()
    yield types.SimpleNamespace(said=said, env_file=tmp_path / ".env")
    reset_conversation_confirmations()
    os.environ.clear()
    os.environ.update(saved)


def _turn(text: str, source: str = "chat"):
    from core.desktop_presence_runtime import RuntimeSession

    rs = RuntimeSession(source=source)
    rs.request_text = text
    return rs


async def _call(rs, tool: str, args: dict) -> dict:
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(
        _capability_dispatcher=None,
        _tool_permission_checker=None,
        _current_session_id="s1",
        _current_device_id="",
        _current_trace_id="",
    )
    token = bind_runtime_session(rs) if rs is not None else None
    try:
        return await OpenClawd._dispatch_tool_call(agent, tool, args)
    finally:
        if token is not None:
            unbind_runtime_session(token)


def _ask(rs, args=None) -> dict:
    return asyncio.run(_call(rs, TOOL, args or {}))


def _mode_on() -> bool:
    from core.system_mode import cross_device_requested

    return cross_device_requested()


# ── 1、2:什么时候有这个工具 ────────────────────────────────────────────────────


def _offered_names() -> set:
    # 模式工具的收集与分发都在 mode_request 里,openclawd 只是接线(下面第二条测试盯着接线)。
    from core.device_onboarding.mode_request import mode_request_tools

    return {t["function"]["name"] for t in mode_request_tools()}


def test_the_tool_exists_only_in_local_mode(env, monkeypatch):
    assert _offered_names() == {TOOL}
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    assert _offered_names() == set(), "已经是跨设备模式:不广告一个死工具"
    monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED")
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
    assert _offered_names() == set()


def test_it_is_collected_by_the_agent_and_does_not_depend_on_the_onboarding_switch(env, monkeypatch):
    import inspect

    from core.device_onboarding.agent_tools import DEVICES_BUILTIN_TOOLS, devices_tools_for_agent
    from core.openclawd import OpenClawd

    assert "devices_tools_for_agent()" in inspect.getsource(OpenClawd._collect_tools)
    names = {t["function"]["name"] for t in devices_tools_for_agent()}
    assert TOOL in names and {t["function"]["name"] for t in DEVICES_BUILTIN_TOOLS} <= names
    # 设备接入开关是跨设备按钮的成员:按钮关着它也关着。请求不能跟着没了。
    monkeypatch.setenv("GALAXY_ONBOARDING_ENABLED", "false")
    assert {t["function"]["name"] for t in devices_tools_for_agent()} == {TOOL}
    assert _offered_names() == {TOOL}


def test_the_tool_takes_no_arguments_so_it_cannot_be_used_to_change_anything_else():
    from core.device_onboarding.mode_request import MODE_BUILTIN_TOOLS

    [tool] = MODE_BUILTIN_TOOLS
    assert tool["function"]["parameters"] == {"type": "object", "properties": {}, "required": []}


# ── 3、4、6:问、答、不能自己批准 ──────────────────────────────────────────────


def test_asking_changes_nothing_and_comes_back_with_the_question(env):
    out = _ask(_turn("用我的手机拍一张照"))
    assert out["success"] is False and out["needs_confirmation"] is True
    assert "跨设备模式" in out["ask_user"] and "好" in out["ask_user"]
    assert _mode_on() is False
    assert "GALAXY_CROSS_DEVICE_ENABLED" not in os.environ
    assert not env.env_file.exists(), "没人批准就一个键都不写"


def test_the_user_saying_yes_in_the_next_turn_turns_it_on_exactly_like_the_button(env):
    _ask(_turn("用我的手机拍一张照"))
    out = _ask(_turn("好"))
    assert out["success"] is True and out["enabled"] is True and out["restart_required"] is True
    assert "重启" in out["tell_user"]
    assert _mode_on() is True
    # 和面板按钮写的一模一样:主键 + 成员 + 模式名,一次落盘。
    assert os.environ["GALAXY_CROSS_DEVICE_ENABLED"] == "true"
    assert os.environ["GALAXY_SYSTEM_MODE"] == "desktop-cross-device"
    assert os.environ["GALAXY_NATS_ENABLED"] == "true" and os.environ["GALAXY_LAN_DISCOVERY"] == "true"
    assert "GALAXY_MASTER_BRAIN_ENABLED" not in os.environ, "主脑是 opt-in,不替人打开"
    written = env.env_file.read_text(encoding="utf-8")
    assert "GALAXY_CROSS_DEVICE_ENABLED=true" in written and "GALAXY_SYSTEM_MODE=desktop-cross-device" in written


def test_the_agent_cannot_approve_itself_in_the_same_turn(env):
    rs = _turn("用我的手机拍一张照,不用问我了")
    _ask(rs)
    out = _ask(rs)
    assert out["success"] is False and out["needs_confirmation"] is True
    assert _mode_on() is False


def test_a_no_is_a_no_and_a_vague_reply_keeps_asking(env):
    _ask(_turn("用我的手机拍一张照"))
    vague = _ask(_turn("嗯"))
    assert vague["success"] is False and vague["needs_confirmation"] is True
    denied = _ask(_turn("不要"))
    assert denied["success"] is False and "不要" in denied["error"]
    assert _mode_on() is False


def test_an_approval_is_used_up_by_one_thing(env):
    _ask(_turn("用我的手机拍一张照"))
    _ask(_turn("好"))
    assert _mode_on() is True
    # 已经开了:再来是「已经开着」,不是再问一遍。
    again = _ask(_turn("再来一次"))
    assert again["success"] is True and again["already"] is True


# ── 5:自发回合、来源不明 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("source", ["ambient", "heartbeat", "vision_sampling", "scheduler", ""])
def test_a_turn_that_is_not_a_person_speaking_cannot_even_ask(env, source):
    out = _ask(_turn("好", source=source))
    assert out["success"] is False and "needs_confirmation" not in out
    assert "用户自己发起" in out["error"]
    assert _mode_on() is False


def test_a_call_outside_any_request_cannot_ask_either(env):
    out = _ask(None)
    assert out["success"] is False and "用户自己发起" in out["error"]
    assert _mode_on() is False


def test_a_background_turn_cannot_approve_what_the_user_was_asked(env):
    _ask(_turn("用我的手机拍一张照"))
    out = _ask(_turn("好", source="ambient"))
    assert out["success"] is False
    assert _mode_on() is False, "系统自发的回合不算人的答应"


# ── 7:自动同意不适用 ────────────────────────────────────────────────────────────


def test_the_onboarding_auto_approve_setting_does_not_apply(env, monkeypatch):
    monkeypatch.setenv("GALAXY_ONBOARDING_AUTO", "approve")
    out = _ask(_turn("用我的手机拍一张照"))
    assert out["success"] is False and out["needs_confirmation"] is True
    assert _mode_on() is False


# ── 9:手表连着时在手表上问 ──────────────────────────────────────────────────────


def test_with_a_watch_it_asks_there_and_says_so_in_the_conversation(env, monkeypatch):
    from core.interaction import high_risk_confirmation as hrc
    from core.interaction import pending_decision_registry as pdr

    async def watch():
        return ["watch-1"]

    async def approve(**kw):
        return hrc.ConfirmationOutcome(True, "用户已明确批准", "d1", "watch")

    monkeypatch.setattr(pdr, "_discover_target_devices", watch)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", approve)
    out = _ask(_turn("用我的手机拍一张照"))
    assert out["success"] is True and _mode_on() is True
    assert any("我在手表上问你了" in s and "跨设备模式" in s for s in env.said)


def test_a_watch_that_says_no_changes_nothing(env, monkeypatch):
    from core.interaction import high_risk_confirmation as hrc
    from core.interaction import pending_decision_registry as pdr

    async def watch():
        return ["watch-1"]

    async def refuse(**kw):
        return hrc.ConfirmationOutcome(False, "用户拒绝", "d1", "watch")

    monkeypatch.setattr(pdr, "_discover_target_devices", watch)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", refuse)
    out = _ask(_turn("用我的手机拍一张照"))
    assert out["success"] is False
    assert _mode_on() is False and not env.env_file.exists()


# ── 只能打开,不能关;不能借它改别的 ───────────────────────────────────────────


def test_there_is_no_way_to_turn_it_off_or_change_anything_else_through_it(env):
    out = asyncio.run(_call(_turn("好"), "devices__turn_off_cross_device", {}))
    assert out["success"] is False and "未知" in out["error"]
    _ask(_turn("用我的手机拍一张照"))
    _ask(_turn("好"), {"GALAXY_MASTER_BRAIN_ENABLED": "true", "GALAXY_NATS_URL": "nats://evil:4222"})
    assert os.environ.get("GALAXY_MASTER_BRAIN_ENABLED") != "true"
    assert not os.environ.get("GALAXY_NATS_URL")


def test_the_request_tool_survives_the_tool_table_being_trimmed():
    """真机实测：工具表超过 24 个时，按词法相关性裁，中文请求对英文描述的这个工具得 0 分 —— 模型看不到它。
    它是本地模式下「想用别的设备却用不了」的唯一出路，列入核心工具永不裁。"""
    from core.context_trim import slim_tools
    from core.device_onboarding.mode_request import MODE_BUILTIN_TOOLS

    filler = [
        {"type": "function", "function": {"name": f"filler__{i}", "description": f"unrelated tool number {i}"}}
        for i in range(40)
    ]
    tools = filler + list(MODE_BUILTIN_TOOLS)
    kept = {t["function"]["name"] for t in slim_tools(tools, "用我的手机拍一张照", max_tools=24)}
    assert TOOL in kept
    assert len(kept) == 24
