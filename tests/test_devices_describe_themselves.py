"""设备自己描述自己(``device_self/1``,设计见 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 第 3 节)。

设备在 ``capability_report`` 里带 ``self_description``:名字、自报类型(只是描述)、一句形态描述、
每个动作做了会怎样(``effect``)、要不要人在设备上点(``needs_human``)、此刻做不了的动作和原因、四样声明。
中心在 ``core/device_self.py`` 把新旧两种上报读成同一个对象,设备卡片从那里读。

``tests/fixtures/device_self/`` 里的两份是安卓仓 ``DeviceSelfDescription.kt`` / ``WatchMember`` /
``PhoneSelfDescription`` 真拼出来的(不是照着 schema 手写的),这里拿 schema 核对。拿到安卓仓时
(``ANDROID_REPO_ROOT``),再逐字对照 Kotlin 里的键名与取值范围。
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

from core import device_self
from core.device_onboarding import agent_tools
from tests.test_phone_joins_through_its_bridge_agent import (  # noqa: F401
    _a2a_kind,
    _phone_auth,
    _phone_register,
    _until,
    phone_id,
)
from tests.test_the_agent_calls_a_phones_actions import _report as _phone_report
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    _connect,
    _eventually,
    _register,
    gateway,
    watch_id,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "device_self"


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _card(gateway, device_id):
    async def call():
        return await agent_tools.dispatch_devices_tool("list", {}, session_id="s-self")

    out = gateway.portal.start_task_soon(call).result(timeout=15)
    return next((c for c in out.get("members") or [] if c["device_id"] == device_id), {})


# ── schema:三边对着同一份 ─────────────────────────────────────────────────────


def test_what_the_watch_and_the_phone_really_send_fits_the_schema():
    assert device_self.problems(_fixture("watch_capability_report")["self_description"]) == []
    assert device_self.problems(_fixture("phone_self_description")) == []


def test_the_schema_refuses_what_the_center_would_not_understand():
    good = _fixture("phone_self_description")
    bad_effect = copy.deepcopy(good)
    bad_effect["actions"][0]["effect"] = "write"
    fifth_declaration = copy.deepcopy(good)
    fifth_declaration["declares"]["shows_messages"] = True
    no_reason = copy.deepcopy(good)
    no_reason["unavailable"] = [{"name": "contacts", "reason": ""}]
    for broken in (bad_effect, fifth_declaration, no_reason):
        assert device_self.problems(broken), broken


# ── 读入:新旧两种读成同一个对象 ───────────────────────────────────────────────


def test_an_old_report_reads_as_the_same_shape():
    old = {
        "device_id": "w1",
        "device_type": "wearos",
        "supported_actions": ["notify", "heart_rate"],
        "capability_schemas": [{"action": "notify", "description": "弹通知"}],
        "action_descriptions": {"heart_rate": "测心率"},
        "answers_decisions": True,
        "bridge_agent": "bridge/1",
    }
    d = device_self.read(old)
    assert d["source"] == "legacy" and d["kind"] == "wearos"
    assert [(a["name"], a["description"], a["effect"]) for a in d["actions"]] == [
        ("notify", "弹通知", ""),
        ("heart_rate", "测心率", ""),
    ], "旧版设备没说做了会怎样,记成空串(没声明)"
    assert d["declares"] == {
        "answers_decisions": True,
        "shows_request_progress": False,
        "hosts_agent": "bridge/1",
        "tailnet": "",
    }


def test_a_self_description_wins_over_the_old_fields_it_repeats():
    report = dict(_fixture("watch_capability_report"))
    report["supported_actions"] = ["notify", "something_stale"]
    report["answers_decisions"] = False
    merged, d = device_self.absorb(report)
    assert d["source"] == "self_description"
    assert merged["supported_actions"] == ["notify", "haptic", "get_status", "heart_rate"]
    assert merged["answers_decisions"] is True
    by_action = {s["action"]: s for s in merged["capability_schemas"]}
    assert by_action["notify"]["effect"] == "notify" and by_action["notify"]["params"]["required"] == ["text"]
    assert "bridge_agent" not in merged, "手表没声明能装 Agent"


def test_reading_is_lenient_one_bad_field_does_not_lose_the_device():
    sd = _fixture("phone_self_description")
    sd["actions"][0]["effect"] = "write"
    sd["actions"].append({"description": "没名字的动作"})
    sd["mood"] = "开心"
    d = device_self.read({"device_id": "p1", "self_description": sd})
    names = [a["name"] for a in d["actions"]]
    assert names[0] == sd["actions"][0]["name"] and d["actions"][0]["effect"] == "", "认不出的 effect 当没声明"
    assert len(names) == len(sd["actions"]) - 1, "没名字的动作丢掉,其余照用"
    assert d["declares"]["hosts_agent"] == "bridge/1"


# ── 经真实的规范设备入口 ─────────────────────────────────────────────────────────


def test_a_watch_that_describes_itself_shows_up_that_way_on_its_card(gateway, watch_id):
    report = _fixture("watch_capability_report")
    report["device_id"] = watch_id
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(report)
        assert _eventually(lambda: _card(gateway, watch_id).get("about"), timeout=10.0), _card(gateway, watch_id)
        card = _card(gateway, watch_id)
    assert card["kind"] == "wearos" and "手腕" in card["about"]
    assert "form" not in card, "说了自己是什么的设备,卡上不再按类型猜一个词"
    effects = {a["name"]: a.get("effect") for a in card["actions"]}
    assert effects == {"notify": "notify", "haptic": "notify", "get_status": "read", "heart_rate": "read"}
    assert card["unavailable"] == [
        {"name": "steps", "reason": "戴表的人没给手表「体能活动」权限,读不了步数(在手表的应用权限里打开)"}
    ]
    assert card["answers_decisions"] is True and card["can_take_agent"] is False


def test_a_phone_that_declares_it_hosts_an_agent_only_in_its_self_description_gets_one(gateway, phone_id):
    report = _phone_report(phone_id, [])
    for old in ("supported_actions", "action_descriptions"):
        report.pop(old)
    report["self_description"] = _fixture("phone_self_description")
    with _connect(gateway, phone_id) as ws:
        ws.send_json(_phone_auth(phone_id))
        assert _until(ws, lambda m: m.get("type") == "auth_ok")
        ws.send_json(_phone_register(phone_id))
        assert _until(ws, lambda m: m.get("type") == "device_register_ack", timeout=30.0).get("success") is True
        ws.send_json(report)
        assert _until(ws, _a2a_kind("agent_dispatch"), timeout=10.0), "自述里声明了 hosts_agent,中心该派桥接 Agent"
        assert _eventually(lambda: _card(gateway, phone_id).get("about"), timeout=10.0)
        card = _card(gateway, phone_id)
    actions = {a["name"]: a for a in card["actions"]}
    assert "contacts" not in actions and card["unavailable"][0]["name"] == "contacts"
    assert actions["sms"]["effect"] == "send" and actions["sms"]["needs_human"] is True
    assert actions["location"]["effect"] == "read" and "needs_human" not in actions["location"]
    assert card["can_take_agent"] is True and card["name"] == "Pixel 9"


def test_an_old_watch_without_a_self_description_still_gets_its_card(gateway, watch_id):
    from tests.test_the_watch_the_phone_and_the_center_work_as_one import _watch_report

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_report(watch_id, ["notify", "haptic"]))
        assert _eventually(lambda: len(_card(gateway, watch_id).get("actions") or []) == 2, timeout=10.0)
        card = _card(gateway, watch_id)
    assert card["form"] == "watch" and "about" not in card and "unavailable" not in card
    assert all("effect" not in a for a in card["actions"])


# ── 拿到安卓仓时:Kotlin 拼的键与 schema 逐字一致 ───────────────────────────────


def test_the_kotlin_builder_speaks_the_schema_when_the_android_repo_is_checked_out():
    root = os.environ.get("ANDROID_REPO_ROOT", "").strip()
    if not root:
        pytest.skip("ANDROID_REPO_ROOT not set")
    src = (
        Path(root) / "shared-protocol/src/main/java/com/ufo/galaxy/shared/protocol/DeviceSelfDescription.kt"
    ).read_text(encoding="utf-8")
    schema = device_self.schema()
    defs = schema["$defs"]
    assert f'const val SCHEMA = "{device_self.SCHEMA}"' in src

    def keys_in(fun_owner: str) -> set:
        body = re.search(
            rf"{fun_owner}.*?fun toJson\(\): JsonObject = buildJsonObject \{{(.*?)\n        \}}", src, re.S
        )
        assert body, f"{fun_owner}.toJson 找不到了"
        return set(re.findall(r'put\("([a-z_]+)"', body.group(1)))

    assert keys_in("data class Action\\(") == set(defs["action"]["properties"])
    assert keys_in("data class Unavailable\\(") == set(defs["unavailable"]["properties"])
    assert keys_in("data class Declares\\(") == set(defs["declares"]["properties"])
    top = re.search(r"\n    fun toJson\(\): JsonObject = buildJsonObject \{(.*?)\n    \}", src, re.S)
    assert top and set(re.findall(r'put\("([a-z_]+)"', top.group(1))) == set(schema["properties"])
    effects = set(
        re.findall(r'const val [A-Z]+ = "([a-z]+)"', src.split("object Effect", 1)[1].split("object Tailnet", 1)[0])
    )
    assert effects == set(device_self.EFFECTS) == set(defs["action"]["properties"]["effect"]["enum"])


def test_the_cross_repo_gate_names_the_self_description_schema():
    from contracts.cross_repo_schema_version_gate import build_cross_repo_schema_gate_manifest

    entry = build_cross_repo_schema_gate_manifest()["device_self_schema"]
    assert entry["id"] == device_self.SCHEMA == device_self.schema()["properties"]["schema"]["const"]
    assert (Path(__file__).resolve().parent.parent / entry["path"]).resolve() == device_self.SCHEMA_PATH
