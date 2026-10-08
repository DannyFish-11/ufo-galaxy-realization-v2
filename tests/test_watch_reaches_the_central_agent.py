"""手表真的能和中心智能体说上话 —— 在真实的规范入口上,不替换任何一环。

为什么要这道门
==============
手表是分布式系统里的一个"成员"(只响应、不发起),它和中心智能体之间只有几件事:
人说的话交给智能体、智能体的提问送到手表上、手表登记并回应、通话。

此前这几件事每一件都有各自的单元测试,却没有一条测试从手表的真实帧一路走到智能体、
再走回手表。结果是各自都绿,合起来却一条也没通:

  * 手表的认证帧把令牌放在 ``payload.token``,规范入口只读顶层 ``token``;
  * 手表的配对令牌过不了这个入口的认证;
  * ``command`` 帧(语音提问、回答决策、可打扰性……)在规范入口上没有处理器,只被回一个
    "No specific handler registered" 的通用 ack;
  * ``voice_call_*`` 同样只被 ack;
  * 智能体"在手表上问人"靠 ``_discover_target_devices`` 找收件人,它读的是旧管理器的
    本地表,规范入口的设备不在其中 —— 一律退回"在对话里问";而旧的测试恰恰是把这个
    函数替换掉的(``monkeypatch.setattr(pdr, "_discover_target_devices", ...)``)。
  * 回复的 ``correlation_id`` 填的是网关自己生成的 message_id,而手表按它自己发的
    ``cmd_N`` 认领回复 —— 配不上,语音回复从不进会话记录。

本文件只用手表真实发出的帧形状(与 galaxy-wearos 的 ``AIPClient`` 一致:信封里没有
``message_id``,相关 id 在 ``correlation_id``;``command`` 的内层是
``{id, command, payload}``),并且**不替换发现函数**。
"""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

STATIC_TOKEN = "static-api-token-for-watch-tests-0123456789"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_API_TOKEN", STATIC_TOKEN)
    monkeypatch.delenv("GALAXY_AUTH_ENABLED", raising=False)
    monkeypatch.setenv("GALAXY_VOICE_CALL", "1")

    from galaxy_gateway.app import app

    @asynccontextmanager
    async def _no_bootstrap(_app):  # 网关启动流程会联网下载模型,与这里要证明的事无关
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _no_bootstrap)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def watch_id():
    return f"wear-{uuid.uuid4().hex[:12]}"


def _recv(ws, timeout=6.0):
    """带超时的接收:没有回应就是缺陷,不能让测试挂死。"""
    box = {}

    def run():
        try:
            box["m"] = ws.receive_json()
        except Exception as exc:  # noqa: BLE001
            box["e"] = repr(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return {"__timeout__": True}
    return box.get("m", {"__error__": box.get("e")})


def _watch_auth_frame(device_id, token):
    # galaxy-wearos AIPClient: AuthMessage 被编进 payload,信封只有 type/device_id/timestamp
    return {
        "type": "auth",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "payload": {"token": token, "device_id": device_id, "device_type": "wearos"},
    }


def _watch_register_frame(device_id, token=""):
    caps = ["notification", "voice_input", "haptic", "interruptibility_telemetry"]
    return {
        "type": "device_register",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "token": token,
        "device_type": "wearos",
        "platform": "wearos",
        "capabilities": caps,
        "payload": {"device_type": "wearos", "platform": "wearos", "capabilities": caps},
    }


def _watch_command_frame(device_id, command, inner, corr, n=1):
    # sendCommand: payload = {id, command, payload?};信封没有 message_id,相关 id 在 correlation_id
    return {
        "type": "command",
        "device_id": device_id,
        "correlation_id": corr,
        "timestamp": int(time.time() * 1000),
        "payload": {"id": n, "command": command, "payload": inner},
    }


def _connect(client, device_id):
    return client.websocket_connect(f"/ws/device/{device_id}", headers={"X-Device-ID": device_id})


def _register(ws, device_id, token=STATIC_TOKEN):
    ws.send_json(_watch_register_frame(device_id, token))
    ack = _recv(ws)
    assert ack.get("type") == "device_register_ack" and ack.get("success") is True, ack
    return ack


# ---------------------------------------------------------------------------
# 一、认证:手表的帧形状 + 它在配对时拿到的令牌
# ---------------------------------------------------------------------------


def test_the_watch_authenticates_with_the_token_in_its_payload(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        ws.send_json(_watch_auth_frame(watch_id, STATIC_TOKEN))
        r = _recv(ws)
    assert r.get("type") == "auth_ok", r
    assert r.get("auth_enforced") is True


def test_the_watch_authenticates_with_the_token_it_got_when_it_paired(gateway, watch_id):
    from core.capability_token import issue_token

    paired = issue_token(watch_id, ["device:status"], ttl_s=3600)
    with _connect(gateway, watch_id) as ws:
        ws.send_json(_watch_auth_frame(watch_id, paired))
        r = _recv(ws)
    assert r.get("type") == "auth_ok", r


def test_a_paired_token_issued_to_another_device_is_refused(gateway, watch_id):
    """令牌绑设备:泄露的令牌换个 device_id 不能冒充。"""
    from core.capability_token import issue_token

    someone_elses = issue_token("some-other-device", ["device:status"], ttl_s=3600)
    with _connect(gateway, watch_id) as ws:
        ws.send_json(_watch_auth_frame(watch_id, someone_elses))
        r = _recv(ws)
    assert r.get("type") == "auth_failed", r
    assert r.get("reason") == "invalid_token"


@pytest.mark.parametrize(
    "token,reason",
    [("", "missing_token"), ("not-a-real-token", "invalid_token")],
)
def test_no_token_or_a_wrong_token_is_still_refused(gateway, watch_id, token, reason):
    with _connect(gateway, watch_id) as ws:
        ws.send_json(_watch_auth_frame(watch_id, token))
        r = _recv(ws)
    assert r.get("type") == "auth_failed", r
    assert r.get("reason") == reason


# ---------------------------------------------------------------------------
# 二、智能体找得到手表(不替换发现函数)
# ---------------------------------------------------------------------------


def test_the_agent_finds_a_registered_watch_when_it_looks_for_someone_to_ask(gateway, watch_id):
    from core.interaction.pending_decision_registry import _discover_target_devices

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)

        async def look():
            return await _discover_target_devices()

        assert watch_id in gateway.portal.call(look)


def test_a_watch_that_left_is_no_longer_asked(gateway, watch_id):
    from core.interaction.pending_decision_registry import _discover_target_devices

    async def look():
        return await _discover_target_devices()

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        assert watch_id in gateway.portal.call(look)  # 先证明在线时找得到，下面的"找不到"才有意义
    time.sleep(0.5)  # 让服务端处理断开
    assert watch_id not in gateway.portal.call(look)


# ---------------------------------------------------------------------------
# 三、智能体在手表上问人,人在手表上答 —— 一整圈
# ---------------------------------------------------------------------------


def test_the_agent_asks_on_the_watch_and_the_answer_comes_back(gateway, watch_id):
    from core.interaction.pending_decision_registry import request_human_decision

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)

        async def ask():
            return await request_human_decision(
                title="要接入这台灯吗",
                summary="客厅的灯",
                options=[{"id": "approve", "label": "接入"}, {"id": "deny", "label": "不接"}],
                timeout_s=8.0,
            )

        pending = gateway.portal.start_task_soon(ask)

        asked = _recv(ws)
        assert asked.get("type") == "decision_request", asked
        decision_id = asked["payload"]["decision_id"]

        ws.send_json(
            _watch_command_frame(
                watch_id,
                "human_input",
                {"decision_id": decision_id, "selected_option": "approve", "device": "wear_os"},
                "cmd_9",
                9,
            )
        )
        reply = _recv(ws)
        assert reply.get("type") == "command_result", reply

        outcome = pending.result(timeout=10)
    assert outcome.status.value == "resolved"
    assert outcome.selected_option == "approve"
    assert outcome.source == "wear"


# ---------------------------------------------------------------------------
# 四、上行:人说的话到智能体,回复能被手表认领
# ---------------------------------------------------------------------------


@pytest.fixture
def agent(monkeypatch):
    """替换的只有"智能体的大脑"(要联网调模型);入口、分流、回包都是真的。"""
    calls = []

    class _Runtime:
        async def handle_request(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "response": "好的,已经记下了", "runtime_session_id": "rs-1"}

    import core.desktop_presence_runtime as dpr

    monkeypatch.setattr(dpr, "get_desktop_presence_runtime", lambda: _Runtime())
    return SimpleNamespace(calls=calls)


def test_what_the_wearer_says_reaches_the_agent_and_the_reply_pairs_with_the_question(gateway, watch_id, agent):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(
            _watch_command_frame(
                watch_id, "voice_query", {"text": "帮我记一下明天开会", "source": "wear_os"}, "cmd_7", 7
            )
        )
        r = _recv(ws)

    assert r.get("type") == "command_result", r
    # 手表按自己发的 correlation_id 认领回复(ConversationRecorder.recordCommandResult)
    assert r.get("correlation_id") == "cmd_7", r
    assert r["data"]["text"] == "好的,已经记下了"
    assert r["success"] is True

    assert len(agent.calls) == 1
    call = agent.calls[0]
    assert call["message"] == "帮我记一下明天开会"
    assert call["source"] == "wear_voice"
    assert call["device_id"] == watch_id


def test_the_wearers_words_do_not_enter_the_desktop_tri_state(gateway, watch_id, agent):
    from core.presence_line import decide_presence_line

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_command_frame(watch_id, "voice_query", {"text": "你好"}, "cmd_1", 1))
        _recv(ws)
    assert decide_presence_line(agent.calls[0]["source"], watch_id).host_bound is False


def test_an_empty_transcript_is_answered_as_a_failure_not_dropped(gateway, watch_id, agent):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_command_frame(watch_id, "voice_query", {"text": "  "}, "cmd_2", 2))
        r = _recv(ws)
    assert r.get("type") == "command_result", r
    assert r["success"] is False
    assert agent.calls == []


def test_the_watch_can_ask_which_devices_exist(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_command_frame(watch_id, "query_devices", {}, "cmd_3", 3))
        r = _recv(ws)
    assert r.get("type") == "command_result", r
    assert r.get("correlation_id") == "cmd_3"


def test_interruptibility_reports_reach_the_agents_attention(gateway, watch_id):
    from core.interruptibility_registry import get_interruptibility_registry

    report = {
        "score": 0.82,
        "band": "free",
        "reasons": ["wrist_raised"],
        "confidence": 0.7,
        "device": "wear_os",
        "timestamp": int(time.time() * 1000),
    }
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_command_frame(watch_id, "interruptibility", report, "cmd_4", 4))
        r = _recv(ws)
    assert r.get("type") == "command_result", r
    assert r["data"].get("success") is True, r
    assert watch_id in str(get_interruptibility_registry().snapshot_all())


def test_a_command_that_fails_inside_is_answered_not_swallowed(gateway, watch_id, monkeypatch):
    """网关内部出错时手表要收到失败的 command_result,而不是永远等不到回包。"""
    import core.desktop_presence_runtime as dpr

    class _Boom:
        async def handle_request(self, **_):
            raise RuntimeError("model backend down")

    monkeypatch.setattr(dpr, "get_desktop_presence_runtime", lambda: _Boom())
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_command_frame(watch_id, "voice_query", {"text": "你好"}, "cmd_5", 5))
        r = _recv(ws)
    assert r.get("type") == "command_result", r
    assert r["success"] is False
    assert r.get("correlation_id") == "cmd_5"


# ---------------------------------------------------------------------------
# 五、通话:信令到达通话路由,不是通用 ack
# ---------------------------------------------------------------------------


def test_call_signalling_reaches_the_call_route(gateway, watch_id, monkeypatch):
    monkeypatch.setenv("GALAXY_VOICE_CALL", "0")  # 确定性:运维关闭时路由会说清原因
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(
            {
                "type": "voice_call_start",
                "device_id": watch_id,
                "timestamp": int(time.time() * 1000),
                "payload": {"sdp": "v=0\r\n", "sdp_type": "offer", "sample_rate": 48000, "locale": "zh-CN"},
            }
        )
        r = _recv(ws)
    assert r.get("type") == "voice_call_end", r
    assert "GALAXY_VOICE_CALL=0" in str(r.get("reason"))


def test_the_call_route_goes_away_with_the_connection(gateway, watch_id, monkeypatch):
    from galaxy_gateway import voice_call_route as vcr

    monkeypatch.setenv("GALAXY_VOICE_CALL", "0")
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(
            {
                "type": "voice_call_start",
                "device_id": watch_id,
                "timestamp": int(time.time() * 1000),
                "payload": {"sdp": "v=0\r\n", "sdp_type": "offer"},
            }
        )
        _recv(ws)
        assert [k for k, r in vcr._ROUTES.items() if r.device_id == watch_id]  # 通话是连接级资源，此刻存在
    time.sleep(0.5)
    assert not [k for k, r in vcr._ROUTES.items() if r.device_id == watch_id]  # 连接没了，它也要收掉


# ---------------------------------------------------------------------------
# 六、没认证过的连接不能借道进智能体
# ---------------------------------------------------------------------------


def test_an_unauthenticated_connection_cannot_talk_to_the_agent(gateway, watch_id, agent):
    with _connect(gateway, watch_id) as ws:  # 既没发 auth 帧，也没登记
        ws.send_json(_watch_command_frame(watch_id, "voice_query", {"text": "替我批准"}, "cmd_6", 6))
        r = _recv(ws)
    assert r.get("type") == "command_result", r
    assert r["success"] is False
    assert r["data"].get("error") == "unauthenticated"
    assert agent.calls == []


def test_an_unauthenticated_connection_cannot_answer_a_decision(gateway, watch_id):
    from core.interaction.pending_decision_registry import get_pending_decision_registry

    async def open_a_decision():  # 在网关自己的事件循环里登记，future 才和回答处在同一个循环
        return get_pending_decision_registry().register(
            options=["approve"], default_option=None, on_timeout=None, urgency="normal", timeout_s=5, devices=[]
        )

    record = gateway.portal.call(open_a_decision)
    intruder = "intruder-" + watch_id
    with _connect(gateway, intruder) as ws:  # 没认证、没登记
        ws.send_json(
            _watch_command_frame(
                intruder, "human_input", {"decision_id": record.decision_id, "selected_option": "approve"}, "cmd_8", 8
            )
        )
        r = _recv(ws)
    assert r.get("type") == "command_result", r
    assert r["success"] is False
    assert r["data"].get("error") == "unauthenticated"

    async def still_open():
        return not record.future.done()

    assert gateway.portal.call(still_open)  # 没认证的连接回答不了，这条决策还悬着


def test_a_second_connection_cannot_borrow_the_first_ones_authentication(gateway, watch_id, agent):
    """认证按连接对象判：另开一条连接自报同一个 device_id，借不到别人的认证结果。"""
    with _connect(gateway, watch_id) as honest:
        honest.send_json(_watch_auth_frame(watch_id, STATIC_TOKEN))
        assert _recv(honest).get("type") == "auth_ok"
        with _connect(gateway, watch_id) as impostor:
            impostor.send_json(_watch_command_frame(watch_id, "voice_query", {"text": "冒充"}, "cmd_66", 66))
            r = _recv(impostor)
    assert r["success"] is False
    assert agent.calls == []
