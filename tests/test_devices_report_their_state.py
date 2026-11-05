"""设备此刻的状态由设备自己报(设计文档 3.5、第 3 步)。

状态跟着心跳走(``heartbeat`` 帧的 ``payload.state``),每一份都是此刻的全部;中心在 ``core/device_state.py``
读入、整份替换上一份。卡片上的状态只有两种来源:中心看到的(在线、最后见到、网络路径、有没有命令在跑)
和设备报的(电量、充电、屏幕、戴没戴着、通话、能不能打扰、一句 note)。设备没报的不写,不推断。

``tests/fixtures/device_self/`` 里的 ``watch_state_heartbeat`` / ``watch_state_unknown`` / ``phone_state``
是安卓仓 ``DeviceState.kt`` / ``WatchState`` / ``WatchMember.stateFrame`` / ``PhoneState`` 真拼出来的。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

import pytest

from core import device_state
from core.device_onboarding import agent_tools
from core.interruptibility_registry import (
    STALE_AFTER_S,
    get_interruptibility_registry,
    reset_interruptibility_registry,
)
from tests.test_phone_joins_through_its_bridge_agent import (  # noqa: F401
    _phone_auth,
    _phone_register,
    _until,
    phone_id,
)
from tests.test_the_agent_calls_a_phones_actions import _report as _phone_report
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    _connect,
    _eventually,
    _online,
    _recv,
    _register,
    _report,
    _watch_capability_report_frame,
    gateway,
    watch_id,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "device_self"
DEVICE_KEYS = set(device_state.KEYS)


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_interruptibility_registry()
    yield
    reset_interruptibility_registry()


def _card(gateway, device_id):
    async def call():
        return await agent_tools.dispatch_devices_tool("list", {}, session_id="s-state")

    out = gateway.portal.start_task_soon(call).result(timeout=15)
    return next((c for c in out.get("members") or [] if c["device_id"] == device_id), {})


def _watch_heartbeat(device_id, state):
    """``WatchMember.stateFrame`` 拼的形状(取自 Kotlin 真拼的那份,换上设备 id 和状态)。"""
    frame = _fixture("watch_state_heartbeat")
    frame["device_id"] = device_id
    frame["timestamp"] = int(time.time() * 1000)
    frame["payload"]["state"] = state
    return frame


def _phone_heartbeat(device_id, state):
    """``GalaxyWebSocketClient.sendHeartbeat``:扁平帧,没有 version;装上状态后多一个 ``payload.state``。"""
    return {
        "type": "heartbeat",
        "timestamp": int(time.time() * 1000),
        "device_id": device_id,
        "device_type": "Android_Agent",
        "route_mode": "cross_device",
        "trace_id": uuid.uuid4().hex,
        "reconnect_attempts": 0,
        "idempotency_key": f"idem_{uuid.uuid4().hex[:16]}",
        "payload": {"state": state},
    }


def _beat(ws, frame):
    ws.send_json(frame)
    ack = _recv(ws, timeout=10.0)
    assert ack.get("type") == "heartbeat_ack", ack


# ── schema:三边对着同一份 ─────────────────────────────────────────────────────


def test_what_the_watch_and_the_phone_really_send_fits_the_schema():
    assert device_state.problems(_fixture("watch_state_heartbeat")["payload"]["state"]) == []
    assert device_state.problems(_fixture("watch_state_unknown")) == []
    assert device_state.problems(_fixture("phone_state")) == []


def test_the_schema_refuses_a_body_signal_and_values_the_center_does_not_know():
    assert device_state.problems({"bpm": 72})
    assert device_state.problems({"interruptible": "low"})
    assert device_state.problems({"battery": 62})
    assert device_state.problems({"note": ""})


# ── 读入:宽松,但只收认识的键 ─────────────────────────────────────────────────


def test_reading_keeps_only_known_keys_and_valid_values():
    got = device_state.read(
        {
            "battery": 0.62,
            "charging": "yes",  # 不是布尔:丢掉,不猜
            "screen_on": False,
            "interruptible": "BUSY",
            "note": "  在开会  ",
            "heart_rate": 88,  # 原始信号就算被塞上来,也进不了中心
        }
    )
    assert got == {"battery": 0.62, "screen_on": False, "interruptible": "busy", "note": "在开会"}
    assert device_state.read({"battery": 62}) == {"battery": 0.62}, "旧帧按百分数报"
    assert device_state.read({"battery": 250, "interruptible": "low", "note": " "}) == {}
    assert len(device_state.read({"note": "很" * 500})["note"]) == device_state.NOTE_MAX
    assert device_state.read("not a dict") == {}


def test_a_heartbeat_without_state_and_one_with_an_empty_state_are_different():
    assert device_state.carried({"type": "heartbeat"}) is None, "没带:不动上一份"
    assert device_state.carried({"type": "heartbeat", "payload": {"state": {}}}) == {}, "带了空的:现在什么都不知道"
    assert device_state.carried({"type": "heartbeat", "state": {"battery": 0.5}}) == {"battery": 0.5}


# ── 经真网关 ──────────────────────────────────────────────────────────────────


def test_the_watch_reports_its_state_in_a_heartbeat_and_the_card_shows_it(gateway, watch_id):
    sent = _fixture("watch_state_heartbeat")["payload"]["state"]
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        _report(ws, _watch_capability_report_frame(watch_id))
        _beat(ws, _watch_heartbeat(watch_id, sent))
        card = _card(gateway, watch_id)
        reg = get_interruptibility_registry()
        line = reg.prompt_line()
        blocked = reg.is_blocked()

    status = card["status"]
    assert {k: status[k] for k in DEVICE_KEYS if k in status} == sent, "设备报的原样进卡片"
    assert status["online"] is True
    # 常驻注意力循环看到的:是哪台设备说的,说了什么 —— 不写死「手表」
    assert blocked is True
    assert card["name"] in line and "极可能在睡" in line, line


def test_a_new_state_replaces_the_last_one_and_what_it_no_longer_says_is_unknown(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        _report(ws, _watch_capability_report_frame(watch_id))
        _beat(ws, _watch_heartbeat(watch_id, _fixture("watch_state_heartbeat")["payload"]["state"]))
        # 手表说不出所以然了(UNKNOWN):这一份里没有 interruptible
        _beat(ws, _watch_heartbeat(watch_id, _fixture("watch_state_unknown")))
        status = _card(gateway, watch_id)["status"]
        blocked = get_interruptibility_registry().is_blocked()

    assert {k: status[k] for k in DEVICE_KEYS if k in status} == _fixture("watch_state_unknown")
    assert "interruptible" not in status and "note" not in status, "不沿用上一份"
    assert blocked is False, "上一份的「明确别打扰」跟着撤掉"


def test_the_phone_reports_its_state_on_every_heartbeat(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        ws.send_json(_phone_auth(phone_id))
        assert _until(ws, lambda m: m.get("type") == "auth_ok")
        ws.send_json(_phone_register(phone_id))
        assert _until(ws, lambda m: m.get("type") == "device_register_ack", timeout=30.0).get("success") is True
        ws.send_json(_phone_report(phone_id, ["location"]))
        assert _until(ws, lambda m: m.get("type") == "capability_report_ack", timeout=10.0)
        ws.send_json(_phone_heartbeat(phone_id, _fixture("phone_state")))
        assert _until(ws, lambda m: m.get("type") == "heartbeat_ack", timeout=10.0)
        status = _card(gateway, phone_id)["status"]

    assert {k: status[k] for k in DEVICE_KEYS if k in status} == _fixture("phone_state")
    assert "worn" not in status and "interruptible" not in status, "手机没报的就不写"


def test_a_device_that_never_reported_state_has_only_what_the_center_sees(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        _report(ws, _watch_capability_report_frame(watch_id))
        assert _eventually(lambda: _online(watch_id))
        status = _card(gateway, watch_id)["status"]

    assert not DEVICE_KEYS & set(status), f"没报就是不知道,卡片上不写: {status}"
    assert status["online"] is True


def test_an_old_device_status_frame_still_shows_its_battery(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        _report(ws, _watch_capability_report_frame(watch_id))
        ws.send_json(
            {
                "version": "3.0",
                "type": "device_status",
                "device_id": watch_id,
                "payload": {"battery_level": 37, "cpu": 0.2, "memory": 0.5},
            }
        )
        assert _recv(ws, timeout=10.0).get("type") == "device_status_ack"
        status = _card(gateway, watch_id)["status"]

    assert status.get("battery") == 0.37
    assert "cpu" not in status and "memory" not in status


# ── 卡片上的状态:离线不写、陈旧不写 ──────────────────────────────────────────


def test_state_is_not_shown_for_an_offline_device_or_once_it_is_stale():
    meta = {device_state.METADATA_KEY: {"battery": 0.5, "screen_on": True, "reported_at": 1000.0}}
    assert device_state.current(meta, online=True, now=1000.0 + 60) == {"battery": 0.5, "screen_on": True}
    assert device_state.current(meta, online=False, now=1000.0 + 60) == {}, "离线了,它现在怎样中心不知道"
    assert device_state.current(meta, online=True, now=1000.0 + STALE_AFTER_S + 1) == {}
    assert device_state.current({}, online=True) == {}
    # 元数据里就算混进了别的键(旧版本、别的写口),卡片也只给这几个
    odd = {device_state.METADATA_KEY: {"battery": 0.5, "bpm": 72, "reported_at": 1000.0}}
    assert device_state.current(odd, online=True, now=1000.0) == {"battery": 0.5}


def test_the_registry_names_whoever_reported_and_forgets_when_they_stop_saying():
    reg = get_interruptibility_registry()
    reg.observe("phone-1", "blocked", note="手机开着勿扰", source="Pixel 9", now=100.0)
    assert reg.is_blocked(now=110.0) and reg.blocking_source(now=110.0) == "Pixel 9"
    assert reg.prompt_line(now=110.0).startswith("（Pixel 9：此刻明确不宜打扰(手机开着勿扰)")
    reg.forget("phone-1")
    assert reg.is_blocked(now=110.0) is False and reg.prompt_line(now=110.0) == ""
    assert reg.observe("phone-1", "unknown", now=120.0) is None, "说不出就别报这个键,报了也不记"


# ── 拿到安卓仓时:Kotlin 拼的键与 schema 逐字一致 ───────────────────────────────


def test_the_kotlin_builder_speaks_the_schema_when_the_android_repo_is_checked_out():
    root = os.environ.get("ANDROID_REPO_ROOT", "").strip()
    if not root:
        pytest.skip("ANDROID_REPO_ROOT not set")
    src = (Path(root) / "shared-protocol/src/main/java/com/ufo/galaxy/shared/protocol/DeviceState.kt").read_text(
        encoding="utf-8"
    )
    schema = device_state.schema()
    body = re.search(r"fun toJson\(\): JsonObject = buildJsonObject \{(.*?)\n    \}", src, re.S)
    assert body, "DeviceState.toJson 找不到了"
    assert set(re.findall(r'put\("([a-z_]+)"', body.group(1))) == set(schema["properties"]) == DEVICE_KEYS
    values = set(
        re.findall(
            r'const val [A-Z]+ = "([a-z]+)"', src.split("object Interruptible", 1)[1].split("companion object", 1)[0]
        )
    )
    assert values == set(device_state.INTERRUPTIBLE) == set(schema["properties"]["interruptible"]["enum"])
    assert 'const val KEY = "state"' in src and f"MAX_NOTE = {device_state.NOTE_MAX}" in src


def test_the_cross_repo_gate_names_the_state_schema():
    from contracts.cross_repo_schema_version_gate import build_cross_repo_schema_gate_manifest

    entry = build_cross_repo_schema_gate_manifest()["device_state_schema"]
    assert entry["id"] == "device_state/1" == device_state.schema()["$id"].split(":", 1)[1]
    assert (Path(__file__).resolve().parent.parent / entry["path"]).resolve() == device_state.SCHEMA_PATH
