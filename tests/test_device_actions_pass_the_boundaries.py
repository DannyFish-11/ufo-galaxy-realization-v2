"""给设备下发一个动作之前过的边界(``core/device_boundaries.py``,设计文档第 5 节)里的第 2、3 条:权限门与参数。

* **参数合法**:按设备自述里这个动作的参数格式校验,不合法不发、原因交回模型;
* **权限门与自治档位**:按动作做了会怎样(``effect``)、要不要人在设备上点(``needs_human``)和自治档位判
  直接做 / 问 / 高风险确认。

此前 ``device__<id>__<action>`` 匹配不上任何风险策略,一律放行、不确认;自治档位按动作名猜读写,
``heart_rate``、``calendar`` 这类读动作认不出来。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core import device_boundaries as b
from core import device_self
from tests.device_self_frames import phone_self, watch_self
from tests.test_phone_joins_through_its_bridge_agent import _until, phone_id  # noqa: F401
from tests.test_the_agent_calls_a_phones_actions import _card_actions, _connect, _invoke, _join, _result
from tests.test_watch_reaches_the_central_agent import _eventually, gateway  # noqa: F401

# ── 那张表 ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "level, effect, needs_human, expected",
    [
        ("guided", "read", False, b.GO),
        ("guided", "notify", False, b.GO),
        ("guided", "act", False, b.ASK),
        ("guided", "send", False, b.CONFIRM),
        ("guided", "danger", False, b.CONFIRM),
        ("safe", "read", False, b.ASK),
        ("safe", "notify", False, b.ASK),
        ("safe", "act", False, b.ASK),
        ("safe", "send", False, b.CONFIRM),
        ("autonomous", "act", False, b.GO),
        ("autonomous", "send", False, b.CONFIRM),
        ("autonomous", "danger", False, b.CONFIRM),
        # 设备上那一下就是确认:哪一档都不另外问
        ("safe", "send", True, b.GO),
        ("guided", "act", True, b.GO),
    ],
)
def test_the_table(level, effect, needs_human, expected):
    assert b.verdict_for(level, effect, needs_human) == expected


def test_an_effect_the_device_did_not_state_is_counted_on_the_strict_side():
    assert b.effect_of({"effect": "notify"}, "notify") == "notify"
    assert b.effect_of({}, "get_status") == "read", "动作名一看就是读的按读"
    assert b.effect_of({}, "tap") == "act", "拿不准的按改设备状态"
    assert b.effect_of({"effect": "write"}, "x") == "act", "认不出的 effect 当没说"


def test_parameters_are_checked_against_what_the_device_said():
    sms = next(a for a in phone_self(["sms"])["actions"] if a["name"] == "sms")
    assert b.check_params(sms, {"to": "10086", "text": "到了"}) is None
    problem = b.check_params(sms, {"to": "10086"})
    assert problem and "text" in problem
    assert b.check_params({}, {"anything": 1}) is None, "设备没给格式的不查"
    assert b.check_params({"params": {"type": "object", "properties": {}}}, {"x": 1}) is None


# ── 过边界:真 UDM,问人那一步换成替身 ─────────────────────────────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    import core.autonomy_policy as ap
    from core.device_onboarding.conversation import reset_conversation_confirmations
    from core.unified.device_manager import get_unified_device_manager, reset_unified_device_manager

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_AUTONOMY", raising=False)
    monkeypatch.setattr(ap, "_grants_path", lambda: str(tmp_path / "grants.json"))
    ap.reset_grant_store()
    reset_unified_device_manager()
    reset_conversation_confirmations()
    udm = get_unified_device_manager()

    def add(device_id, desc):
        udm.register_device_from_dict(device_id, {"device_type": "x", "transport": "websocket", "name": device_id})
        udm.upsert_device_state(
            device_id, {"metadata": {"self_description": device_self.read({"self_description": desc})}}, source="t"
        )

    asked = SimpleNamespace(decisions=[], confirms=[], answer="always", approve=True, deciders=["w1"])

    async def fake_decision(**kw):
        asked.decisions.append(kw)
        return SimpleNamespace(status="resolved", selected_option=asked.answer, timed_out=False)

    async def fake_confirm(**kw):
        from core.interaction.high_risk_confirmation import ConfirmationOutcome

        asked.confirms.append(kw)
        return ConfirmationOutcome(asked.approve, "用户已明确批准" if asked.approve else "用户明确拒绝")

    async def fake_deciders(what):
        return list(asked.deciders) if what == "answers_decisions" else []

    import core.device_declarations as dd
    import core.interaction.high_risk_confirmation as hrc
    import core.interaction.pending_decision_registry as pdr

    monkeypatch.setattr(pdr, "request_human_decision", fake_decision)
    monkeypatch.setattr(hrc, "confirm_high_risk_tool", fake_confirm)
    monkeypatch.setattr(dd, "online_devices_that", fake_deciders)
    yield SimpleNamespace(add=add, asked=asked)
    ap.reset_grant_store()
    reset_unified_device_manager()
    reset_conversation_confirmations()


def _gate(device_id, action, params=None):
    return asyncio.run(b.gate(device_id, action, params or {}, session_id="s-b"))


def test_reading_and_notifying_go_straight_through_in_the_default_mode(env):
    env.add("w1", watch_self(["notify", "heart_rate"]))
    assert _gate("w1", "heart_rate") is None
    assert _gate("w1", "notify", {"text": "喝水"}) is None
    assert env.asked.decisions == [] and env.asked.confirms == []


def test_changing_the_device_is_asked_on_a_device_that_answers_and_always_is_remembered(env):
    env.add("p1", phone_self(["app_control"]))
    assert _gate("p1", "app_control", {"app": "微信"}) is None
    assert len(env.asked.decisions) == 1
    ask = env.asked.decisions[0]
    assert [o["id"] for o in ask["options"]] == ["deny", "once", "session", "always"]
    assert ask["default_option"] is None and "app_control" in ask["title"]
    assert _gate("p1", "app_control", {"app": "设置"}) is None
    assert len(env.asked.decisions) == 1, "选了永久允许,下次不再问"


def test_once_is_not_remembered_and_no_or_silence_means_no(env):
    env.add("p1", phone_self(["app_control"]))
    env.asked.answer = "once"
    assert _gate("p1", "app_control", {"app": "微信"}) is None
    assert _gate("p1", "app_control", {"app": "微信"}) is None
    assert len(env.asked.decisions) == 2, "仅此次:下次还要问"
    for answer in ("deny", "approve", ""):
        env.asked.answer = answer
        out = _gate("p1", "app_control", {"app": "微信"})
        assert out and out["success"] is False, answer


def test_with_no_device_to_answer_it_is_asked_in_the_conversation(env):
    env.add("p1", phone_self(["app_control"]))
    env.asked.deciders = []
    out = _gate("p1", "app_control", {"app": "微信"})
    assert out["needs_confirmation"] is True and "app_control" in out["ask_user"], out
    assert env.asked.decisions == []


def test_sending_needs_a_tap_on_a_device_unless_the_device_itself_waits_for_one(env):
    desc = phone_self(["sms"])
    env.add("p1", desc)
    assert _gate("p1", "sms", {"to": "10086", "text": "到了"}) is None
    assert env.asked.confirms == [], "手机只备好短信,人点发送才发:那一下就是确认"

    desc["actions"][0]["needs_human"] = False
    env.add("p2", desc)
    env.asked.approve = False
    out = _gate("p2", "sms", {"to": "10086", "text": "到了"})
    assert out["success"] is False and "拒绝" in out["error"]
    assert env.asked.confirms and "对外发出" in env.asked.confirms[0]["risk_level"]


def test_autonomous_mode_skips_asking_but_not_the_high_risk_tap(env, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    desc = phone_self(["app_control", "sms"])
    desc["actions"][1]["needs_human"] = False
    env.add("p1", desc)
    assert _gate("p1", "app_control", {"app": "微信"}) is None and env.asked.decisions == []
    _gate("p1", "sms", {"to": "1", "text": "x"})
    assert len(env.asked.confirms) == 1


def test_a_device_without_a_self_description_is_treated_on_the_strict_side(env):
    from core.unified.device_manager import get_unified_device_manager

    get_unified_device_manager().register_device_from_dict("old", {"device_type": "x", "transport": "websocket"})
    assert _gate("old", "get_status") is None
    assert _gate("old", "notify", {"text": "x"}) is None, "回答了问(替身默认永久允许)"
    assert len(env.asked.decisions) == 1, "旧版设备没说 notify 会怎样,按改设备状态先问"


def test_bad_parameters_never_reach_the_device(env):
    env.add("p1", phone_self(["sms"]))
    out = _gate("p1", "sms", {"to": "10086"})
    assert out["success"] is False and "text" in out["error"] and out["params_schema"]["required"] == ["to", "text"]


# ── 经真实的规范设备入口 ─────────────────────────────────────────────────────────


def test_through_the_real_gateway_reads_go_asks_wait_and_bad_parameters_stay_home(gateway, phone_id, monkeypatch):
    import core.device_declarations as dd

    async def nobody(what):
        return []

    monkeypatch.setattr(dd, "online_devices_that", nobody)
    with _connect(gateway, phone_id) as ws:
        _join(ws, phone_id, ["location", "sms", "app_control"])
        assert _eventually(lambda: "app_control" in _card_actions(phone_id))

        # 改设备状态:没有能回答的设备 → 在对话里问,不发
        out = _invoke(gateway, phone_id, "app_control", {"app": "微信"}).result(timeout=15)
        assert out.get("needs_confirmation") is True, out

        # 参数不全:不发
        out = _invoke(gateway, phone_id, "sms", {"to": "10086"}).result(timeout=15)
        assert out["success"] is False and "text" in out["error"], out

        # 人点一下才发的短信:直接发给手机去备好
        pending = _invoke(gateway, phone_id, "sms", {"to": "10086", "text": "到了"})
        cmd = _until(ws, lambda m: m.get("type") == "command", timeout=10.0)
        assert cmd.get("command") == "sms", cmd
        ws.send_json(_result(phone_id, cmd["command_id"], True, {"prepared": True}))
        assert pending.result(timeout=15)["success"] is True


def test_a_phone_that_answers_questions_is_asked_and_its_answer_lets_the_action_through(gateway, phone_id):
    """手机声明了能回答提问(通知打得开):改设备状态的动作在手机上问,人点「永久允许」后照做,下次不再问。

    帧形状与安卓 ``PhoneDecisions`` / ``DecisionFrames`` 一致:``decision_request`` 进,``human_input`` 以 command 回。
    """
    import core.autonomy_policy as ap

    ap.reset_grant_store()
    with _connect(gateway, phone_id) as ws:
        _join(ws, phone_id, ["app_control"])
        assert _eventually(lambda: "app_control" in _card_actions(phone_id))

        pending = _invoke(gateway, phone_id, "app_control", {"app": "微信"})
        ask = _until(ws, lambda m: m.get("type") == "decision_request", timeout=10.0)
        assert ask, "该在手机上问"
        p = ask["payload"]
        assert [o["id"] for o in p["options"]] == ["deny", "once", "session", "always"] and "app_control" in p["title"]
        ws.send_json(
            {
                "type": "command",
                "version": "3.0",
                "device_id": phone_id,
                "correlation_id": "hi_1",
                "payload": {
                    "id": 1,
                    "command": "human_input",
                    "payload": {
                        "decision_id": p["decision_id"],
                        "selected_option": "always",
                        "device": "android_phone",
                    },
                },
            }
        )
        cmd = _until(ws, lambda m: m.get("type") == "command" and m.get("command") == "app_control", timeout=10.0)
        assert cmd.get("params") == {"app": "微信"}, cmd
        ws.send_json(_result(phone_id, cmd["command_id"], True, {"opened": True}))
        assert pending.result(timeout=15)["success"] is True

        # 永久允许:第二次不再问,直接发
        pending = _invoke(gateway, phone_id, "app_control", {"app": "设置"})
        nxt = _until(ws, lambda m: m.get("type") in ("command", "decision_request"), timeout=10.0)
        assert nxt.get("type") == "command" and nxt.get("command") == "app_control", nxt
        ws.send_json(_result(phone_id, nxt["command_id"], True, {"opened": True}))
        assert pending.result(timeout=15)["success"] is True
    ap.reset_grant_store()
