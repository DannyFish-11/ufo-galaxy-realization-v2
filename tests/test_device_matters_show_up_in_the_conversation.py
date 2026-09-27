"""设备的事在对话里自己出现:要人点头的在对话里问、在对话里答;发现新设备主动说一声。

走真的:OpenClawd 的工具分发入口、接入平面、``RuntimeSession`` 经真正的
``bind_runtime_session`` 挂进请求上下文(和 ``DesktopPresenceRuntime.handle_request`` 一样)。
只替掉面板推送(断言说了什么)。

对话里的确认,四条规则各有用例:
1. 问的那一回合里再调一次,不算答应(智能体不能自己批准自己);
2. 只认人发起的回合,自发注意力之类不算;
3. 看人的原话:明确的「好」算、「不要」算拒绝、含糊的继续问;
4. 答应一次只管一件事。
"""

from __future__ import annotations

import asyncio
import types

import pytest

#: 一块插在主脑上的板子 —— 用它当"需要同意一下"的候选样本。
#: (NATS worker 不是发现来源,见 core/device_onboarding/sources.py 模块头。)
_SERIAL = {"device": "/dev/ttyACM0", "vid": "2341", "pid": "0043", "serial_number": "758", "product": "nas"}
_SERIAL_ID = "serial-usb-2341-0043-758"
_SERIAL_NAME = "nas(/dev/ttyACM0)"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import core.lumiv_websocket_bridge as lwb
    from core import autonomy_policy
    from core.device_onboarding.conversation import reset_conversation_confirmations
    from core.device_onboarding.service import reset_onboarding_service
    from core.interaction import pending_decision_registry as pdr
    from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "ob"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_AUTONOMY", "guided")
    for k in ("GALAXY_ONBOARDING_AUTO", "HOME_ASSISTANT_URL", "GALAXY_HEADSCALE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(autonomy_policy, "_grants_path", lambda: str(tmp_path / "grants.json"))

    async def no_watch():
        return []

    monkeypatch.setattr(pdr, "_discover_target_devices", no_watch)
    said: list = []
    monkeypatch.setattr(lwb, "emit_conversation", lambda role, text, **kw: said.append(text))
    resets = (
        reset_unified_device_manager,
        reset_unified_connection_manager,
        reset_onboarding_service,
        reset_auto_enrollment_service,
        reset_conversation_confirmations,
    )
    for r in resets:
        r()
    yield types.SimpleNamespace(said=said)
    for r in resets:
        r()


def _turn(text: str, source: str = "chat"):
    """一个经正门的回合:和 handle_request 一样建 RuntimeSession、挂进上下文。"""
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
    token = bind_runtime_session(rs)
    try:
        return await OpenClawd._dispatch_tool_call(agent, tool, args)
    finally:
        unbind_runtime_session(token)


def _in_turn(rs, tool, args):
    return asyncio.run(_call(rs, tool, args))


def _candidate() -> str:
    from core.device_onboarding import local_buses as lb
    from core.device_onboarding.service import get_onboarding_service

    get_onboarding_service().observe(lb.serial_observation(_SERIAL))
    [c] = get_onboarding_service().overview()["candidates"]
    return c["candidate_id"]


def _udm_has(did: str) -> bool:
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager().get_device(did) is not None


# ── 在对话里问、在对话里答 ─────────────────────────────────────────────────────


def test_with_no_watch_the_question_comes_back_to_ask_in_the_conversation(env):
    cid = _candidate()
    out = _in_turn(_turn("把 nas 接进来"), "devices__join", {"candidate_id": cid})
    assert out["success"] is False and out["needs_confirmation"] is True
    assert f"把「{_SERIAL_NAME}」接入为设备" in out["ask_user"] and "好" in out["ask_user"]
    assert not _udm_has(_SERIAL_ID)


def test_the_user_saying_yes_in_the_next_turn_joins_it(env):
    cid = _candidate()
    _in_turn(_turn("把 nas 接进来"), "devices__join", {"candidate_id": cid})
    out = _in_turn(_turn("好的"), "devices__join", {"candidate_id": cid})
    assert out["success"] and out["outcome"]["kind"] == "joined"
    assert _udm_has(_SERIAL_ID)


def test_the_agent_cannot_approve_itself_in_the_same_turn(env):
    cid = _candidate()
    rs = _turn("把 nas 接进来,不用问我了")
    _in_turn(rs, "devices__join", {"candidate_id": cid})
    out = _in_turn(rs, "devices__join", {"candidate_id": cid})
    assert out["needs_confirmation"] and not _udm_has(_SERIAL_ID)


def test_a_system_turn_on_the_same_session_does_not_count_as_the_user(env):
    cid = _candidate()
    _in_turn(_turn("把 nas 接进来"), "devices__join", {"candidate_id": cid})
    out = _in_turn(_turn("好", source="ambient"), "devices__join", {"candidate_id": cid})
    assert out["needs_confirmation"] and not _udm_has(_SERIAL_ID)


def test_saying_no_refuses_and_an_unclear_reply_asks_again(env):
    cid = _candidate()
    _in_turn(_turn("把 nas 接进来"), "devices__join", {"candidate_id": cid})
    again = _in_turn(_turn("这是什么设备?"), "devices__join", {"candidate_id": cid})
    assert again["needs_confirmation"] and again["ask_user"].startswith("没听清")
    no = _in_turn(_turn("不要了"), "devices__join", {"candidate_id": cid})
    assert no["success"] is False and "不要" in no["error"] and not _udm_has(_SERIAL_ID)


def test_one_yes_approves_one_thing_only(env):
    from core.unified.device_manager import get_unified_device_manager

    get_unified_device_manager().register_device_from_dict("phone-1", {"device_type": "android_phone"})
    get_unified_device_manager().register_device_from_dict("phone-2", {"device_type": "android_phone"})
    _in_turn(_turn("把 phone-1 删了"), "devices__remove", {"device_id": "phone-1"})
    yes = _turn("好")
    assert _in_turn(yes, "devices__remove", {"device_id": "phone-1"})["success"]
    # 同一句「好」不能顺带批准另一件没问过的事
    other = _in_turn(yes, "devices__remove", {"device_id": "phone-2"})
    assert other["needs_confirmation"] and _udm_has("phone-2")


def test_with_a_watch_it_asks_there_and_says_so_in_the_conversation(env, monkeypatch):
    from core.interaction import high_risk_confirmation as hrc
    from core.interaction import pending_decision_registry as pdr

    async def watch():
        return ["watch-1"]

    async def approve(**kw):
        return hrc.ConfirmationOutcome(True, "用户已明确批准", "d1", "watch")

    monkeypatch.setattr(pdr, "_discover_target_devices", watch)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", approve)
    cid = _candidate()
    out = _in_turn(_turn("把 nas 接进来"), "devices__join", {"candidate_id": cid})
    assert out["success"] and _udm_has(_SERIAL_ID)
    assert f"我在手表上问你了:要把「{_SERIAL_NAME}」接入为设备吗?" in env.said


@pytest.mark.parametrize(
    "text,verdict",
    [
        ("好", True),
        ("好的", True),
        ("嗯,可以", True),
        ("OK", True),
        ("接入", True),
        ("不要", False),
        ("别接", False),
        ("算了", False),
        ("嗯", None),
        ("行吧我再想想", None),
        ("这个设备是干嘛的", None),
        ("", None),
    ],
)
def test_only_a_short_clear_yes_counts(text, verdict):
    from core.device_onboarding.conversation import interpret_reply

    assert interpret_reply(text) is verdict


# ── 主动说一声 ───────────────────────────────────────────────────────────────────


def test_a_newly_discovered_device_is_mentioned_once(env):
    from core.device_onboarding.conversation import _digest
    from core.device_onboarding.models import Observation
    from core.device_onboarding.service import get_onboarding_service

    svc = get_onboarding_service()
    svc.observe(Observation(source="ssdp", key="uuid-tv", name="客厅电视", kind_hint="tv"))
    svc.observe(Observation(source="ssdp", key="uuid-tv", name="客厅电视", kind_hint="tv"))  # 再看见不再说
    _digest.flush_now()
    assert env.said == ["附近发现一台新设备「客厅电视」(你点个头就能接入)。要接入的话跟我说一声。"]


def test_many_new_devices_become_one_sentence(env):
    from core.device_onboarding.conversation import DiscoveryDigest

    text = DiscoveryDigest.render([(f"设备{i}", "x") for i in range(7)])
    assert text.count("「") == 5 and "等 7 台" in text


def test_a_yes_is_used_up_once_it_has_approved(env):
    """同一句「好」不能把同一件事批准两次(比如同一回合里连调两次 invoke)。"""
    from core.device_onboarding.conversation import confirm_in_conversation
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session

    def in_turn(rs):
        token = bind_runtime_session(rs)
        try:
            return confirm_in_conversation("对「电视」执行 power_off", "s1")["state"]
        finally:
            unbind_runtime_session(token)

    assert in_turn(_turn("把电视关了")) == "asked"
    yes = _turn("好")
    assert in_turn(yes) == "approved"
    assert in_turn(yes) == "asked"


def test_a_notice_lands_in_the_mainline_without_touching_semantic_memory(env, monkeypatch):
    """面板重开从主线读回这句话;但写入不能经过会加载向量模型的那条门(会卡住网关的事件循环)。"""
    import core.session_memory_facade as smf
    from core.conversation_mainline import mainline_session_id
    from core.device_onboarding.conversation import announce
    from core.session_manager import get_session_manager

    def must_not_be_used(**kw):
        raise AssertionError("设备播报不该走 record_session_turn")

    monkeypatch.setattr(smf, "record_session_turn", must_not_be_used)
    asyncio.run(announce("「书房」连上了"))
    sid = mainline_session_id()
    assert sid
    history = get_session_manager().get_full_history(sid)
    assert history[-1]["content"] == "「书房」连上了" and history[-1]["role"] == "assistant"
