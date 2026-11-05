"""边界清单落成一个模块(设计文档第 5 节、第 4 步):代码只守这七条,每条一个函数、一个测试。

``core/device_boundaries.py`` 的 ``BOUNDARIES`` 与设计文档那张表一一对应;下发路径按顺序调用:
1 成员资格 → (讲 AIP 的设备)3 参数 → 4 自发打扰的额度 → 2 权限门 → 发(5 串行、必有结果、记进任务流程图)
→ 6 结果以设备回的为准 → 7 中心不留设备数据的副本。去掉任一条,下面对应的那一项变红。
第 2、3 条的逐格测试在 ``tests/test_device_actions_pass_the_boundaries.py``。
"""

from __future__ import annotations

import asyncio
import re
import time
import types
from pathlib import Path

import pytest

from core import device_boundaries as b
from tests.device_self_frames import phone_self, watch_self
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    _connect,
    _eventually,
    _online,
    _register,
    gateway,
    watch_id,
)

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core import autonomy_policy
    from core.device_onboarding.conversation import reset_conversation_confirmations
    from core.interruptibility_registry import reset_interruptibility_registry
    from core.task_graph_runtime import reset_task_graph_runtime
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_AUTONOMY", "guided")
    monkeypatch.delenv("GALAXY_REQUIRE_DEVICE_APPROVAL", raising=False)
    monkeypatch.setattr(autonomy_policy, "_grants_path", lambda: str(tmp_path / "grants.json"))
    resets = (
        autonomy_policy.reset_grant_store,
        reset_conversation_confirmations,
        reset_interruptibility_registry,
        reset_task_graph_runtime,
        reset_unified_connection_manager,
        reset_unified_device_manager,
        b.reset_interrupt_budget,
    )
    for r in resets:
        r()
    yield monkeypatch
    for r in resets:
        r()


def _udm():
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager()


def _add(device_id, desc=None, *, connected=True, **meta):
    _udm().register_device_from_dict(
        device_id, {"device_type": "android_phone", "transport": "websocket", "device_name": device_id}
    )
    metadata = dict(meta)
    if desc is not None:
        metadata["self_description"] = desc
    if metadata:
        _udm().upsert_device_state(device_id, {"metadata": metadata}, source="test")
    if connected:
        from core.unified.connection_manager import get_unified_connection_manager

        get_unified_connection_manager()._websockets[device_id] = object()


def _self_described(desc):
    from core.device_self import read

    return read({"self_description": desc})


def _proactive(monkeypatch, source="ambient"):
    import core.liminal_activity as la

    monkeypatch.setattr(la, "current_runtime_session", lambda: types.SimpleNamespace(source=source))


# ── 表与代码一一对应 ─────────────────────────────────────────────────────────


def test_the_table_in_the_design_and_the_functions_in_the_module_match():
    doc = (REPO / "docs" / "DEVICE_SELF_DESCRIPTION_DESIGN.md").read_text(encoding="utf-8")
    section = doc.split("## 5. 边界清单", 1)[1].split("\n## 6.", 1)[0]
    rows = [int(n) for n in re.findall(r"^\| (\d) \| \*\*", section, re.M)]
    assert rows == list(range(1, 8)) == sorted(b.BOUNDARIES), "设计文档第 5 节那张表就是这七条"
    for number, names in b.BOUNDARIES.items():
        for name in names:
            assert callable(getattr(b, name, None)), f"第 {number} 条的 {name} 不在模块里"
    assert all(f"\n{n}  " in b.__doc__ for n in range(1, 8)), "模块说明里的表也是这七条"


# ── 1 成员资格 ────────────────────────────────────────────────────────────────


def test_1_a_device_not_in_the_roster_or_not_online_gets_nothing_and_nobody_is_asked(env):
    asked = []

    async def ask(**kw):
        asked.append(kw)

    import core.interaction.pending_decision_registry as pdr

    env.setattr(pdr, "request_human_decision", ask)
    from core.device_onboarding.agent_tools import dispatch_devices_tool

    assert "没有这个成员" in b.member("nobody")["error"]
    _add("phone-1", _self_described(phone_self(["app_control"])), connected=False)
    out = asyncio.run(
        dispatch_devices_tool("invoke", {"device_id": "phone-1", "action": "app_control", "params": {"app": "微信"}})
    )
    assert out["success"] is False and "不在线" in out["error"]
    assert asked == [], "不在线的设备,不该先去问人要不要做"


def test_1_with_device_admission_on_an_unapproved_device_stays_connected_but_gets_no_actions(env):
    _add("phone-1", admission_approved=False)
    assert b.member("phone-1") is None, "没开准入:照旧"
    env.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", "1")
    assert "还没被批准" in b.member("phone-1")["error"]
    _add("phone-2")  # 没记过批没批:开了准入就按没批准
    assert "还没被批准" in b.member("phone-2")["error"]
    _add("phone-3", admission_approved=True)
    assert b.member("phone-3") is None


def test_1_admission_is_recorded_when_the_watch_registers_through_the_real_gateway(gateway, watch_id, monkeypatch):
    from core.device_onboarding.agent_tools import dispatch_devices_tool

    monkeypatch.setenv("GALAXY_REQUIRE_DEVICE_APPROVAL", "1")
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")  # 不强制令牌:没带令牌也连得上,只是没被批准
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id, token="")
        assert _eventually(lambda: _online(watch_id))
        out = gateway.portal.start_task_soon(
            lambda: dispatch_devices_tool(
                "invoke", {"device_id": watch_id, "action": "notify", "params": {"text": "x"}}
            )
        ).result(timeout=15)
    assert out["success"] is False and "还没被批准" in out["error"]
    assert _udm().get_device(watch_id).metadata.get("admission_approved") is False

    approved = f"{watch_id}-ok"
    with _connect(gateway, approved) as ws:
        _register(ws, approved)  # 带着网关令牌:批准过
        assert _eventually(lambda: _online(approved))
        assert b.member(approved) is None


def test_1_a_device_behind_a_bridge_is_reached_through_its_bridge(env):
    _udm().register_device_from_dict("ha_light", {"device_type": "iot_generic", "transport": "home_assistant"})
    _udm().upsert_device_state("ha_light", {"bridge_id": "ha:192.168.1.20:8123"}, source="test")
    assert b.member("ha_light") is None, "通不通由那座桥说"


# ── 2 权限门与自治档位 ────────────────────────────────────────────────────────


def test_2_an_action_that_changes_the_device_is_asked_first_in_guided_mode(env):
    spec = {"name": "app_control", "effect": "act"}
    _add("phone-1")
    stop = asyncio.run(b.permission("phone-1", "app_control", {"app": "微信"}, spec, "s"))
    assert stop and stop.get("needs_confirmation") is True, "没有能回答提问的设备在线:在对话里问"
    env.setenv("GALAXY_AUTONOMY", "autonomous")
    assert asyncio.run(b.permission("phone-1", "app_control", {"app": "微信"}, spec, "s")) is None


# ── 3 参数合法 ────────────────────────────────────────────────────────────────


def test_3_parameters_that_do_not_fit_the_devices_schema_are_not_sent():
    spec = next(a for a in watch_self(["notify"])["actions"] if a["name"] == "notify")
    stop = b.params_ok(spec, "notify", {"title": "没有正文"})
    assert stop["success"] is False and "text" in stop["error"] and stop["params_schema"] == spec["params"]
    assert b.params_ok(spec, "notify", {"text": "该出门了"}) is None


# ── 4 主动打扰有额度 ──────────────────────────────────────────────────────────


def test_4_a_proactive_notify_is_held_while_someone_says_do_not_disturb(env):
    from core.interruptibility_registry import get_interruptibility_registry

    get_interruptibility_registry().observe("watch-1", "blocked", note="极可能在睡", source="Galaxy Watch7")
    assert b.interrupt_budget("phone-1", "notify") is None, "人在等结果的请求不算主动打扰"
    _proactive(env)
    stop = b.interrupt_budget("phone-1", "notify")
    assert stop and "Galaxy Watch7" in stop["error"] and "自发" in stop["error"]
    assert b.interrupt_budget("phone-1", "read") is None, "只看不打扰人"


def test_4_proactive_notifies_have_an_hourly_budget(env):
    env.setenv("GALAXY_AMBIENT_SPEAK_PER_HOUR", "2")
    _proactive(env, source="heartbeat")
    assert b.interrupt_budget("watch-1", "notify", now=1000.0) is None
    assert b.interrupt_budget("phone-1", "notify", now=1001.0) is None
    stop = b.interrupt_budget("watch-1", "notify", now=1002.0)
    assert stop and "额度用完" in stop["error"] and "2/2" in stop["error"]
    assert b.interrupt_budget("watch-1", "notify", now=1000.0 + b.INTERRUPT_WINDOW_S + 1) is None, "过了一小时恢复"


def test_4_the_budget_is_checked_before_the_watch_is_given_anything(env):
    from core.interruptibility_registry import get_interruptibility_registry

    _add("watch-1", _self_described(watch_self(["notify"])))
    get_interruptibility_registry().observe("watch-1", "blocked", source="Galaxy Watch7")
    _proactive(env)
    stop = asyncio.run(b.gate("watch-1", "notify", {"text": "要不要喝水"}, "s"))
    assert stop and "不宜打扰" in stop["error"]


# ── 5 每台设备串行;每次下发必有结果;记进任务流程图 ──────────────────────────


def test_5_one_device_does_one_thing_at_a_time_and_different_devices_run_together(env):
    running = {"phone": 0, "watch": 0}
    peak = {"phone": 0, "watch": 0}
    overlap = []

    def job(device):
        async def run():
            running[device] += 1
            peak[device] = max(peak[device], running[device])
            overlap.append(dict(running))
            await asyncio.sleep(0.05)
            running[device] -= 1
            return {"success": True}

        return run

    async def scenario():
        await asyncio.gather(
            b.one_at_a_time("phone", job("phone")),
            b.one_at_a_time("phone", job("phone")),
            b.one_at_a_time("watch", job("watch")),
        )

    asyncio.run(scenario())
    assert peak["phone"] == 1, "同一台设备不同时做两件事"
    assert any(o["phone"] and o["watch"] for o in overlap), "不同设备照样并行"


def test_5_every_dispatch_has_a_result(env):
    async def nothing():
        return None

    async def silent_failure():
        return {"success": False}

    async def boom():
        raise RuntimeError("连接断了")

    async def slow():
        await asyncio.sleep(1)
        return {"success": True}

    run = lambda job, **kw: asyncio.run(b.one_at_a_time("phone", job, **kw))  # noqa: E731
    assert run(nothing) == {"success": False, "error": "「phone」那边没有回结果"}
    assert run(silent_failure)["error"] == "没有成功,也没说原因"
    assert run(boom) == {"success": False, "error": "连接断了"}
    assert "没做完" in run(slow, timeout=0.05)["error"]


def test_5_each_dispatch_is_recorded_in_the_task_graph(env):
    from core.task_graph_runtime import GraphNodeState, get_task_graph_runtime

    ok, bad = b.record_start("phone-1", "location"), b.record_start("phone-1", "contacts")
    b.record_end(ok, True, {"lat": 1})
    b.record_end(bad, False, None, "没给通讯录权限")
    nodes = {n.task_id: n for n in get_task_graph_runtime().all_nodes()}
    assert nodes[ok].state == GraphNodeState.COMPLETED and nodes[ok].device_id == "phone-1"
    assert nodes[bad].state == GraphNodeState.FAILED and nodes[bad].error == "没给通讯录权限"


# ── 6 结果以设备回的为准 ──────────────────────────────────────────────────────


def test_6_what_the_model_is_told_is_what_the_device_said():
    assert b.as_reported({"payload": {"success": False, "error": "屏幕锁着"}}) == (
        False,
        {"success": False, "error": "屏幕锁着"},
        "屏幕锁着",
    )
    assert b.as_reported({"error": "超时"}) == (False, {"error": "超时"}, "超时")
    assert b.as_reported({"payload": {"success": False}})[2] == "设备说没做成,没说原因"
    assert b.as_reported(None) == (False, None, "设备没有回结果")
    assert b.as_reported({"payload": {"success": True, "lat": 31.2}}) == (True, {"success": True, "lat": 31.2}, "")


def test_6_a_device_that_says_it_failed_is_not_reported_as_done(env):
    from core.capabilities.canonical_dispatcher import get_canonical_dispatcher
    from core.unified.connection_manager import get_unified_connection_manager

    ucm = get_unified_connection_manager()

    class Phone:
        async def send_json(self, msg):
            reply = {"command_id": msg["command_id"], "payload": {"success": False, "error": "屏幕锁着"}}
            asyncio.get_running_loop().call_soon(ucm.resolve_command_response, msg["command_id"], reply)

    async def go():
        await ucm.register_connection("phone-1", Phone(), {})
        return await get_canonical_dispatcher().dispatch("device__phone-1__tap", {}, session_id="s")

    r = asyncio.run(go())
    assert r.success is False and r.error == "屏幕锁着"


# ── 7 隐私 ────────────────────────────────────────────────────────────────────


def test_7_the_center_keeps_whether_it_worked_and_why_not_the_devices_data():
    assert b.kept(True, {"contacts": [{"name": "王小明", "phone": "13800000000"}]}) == ("ok", "")
    assert b.kept(False, {"partial": "王小明"}, "没给通讯录权限") == ("", "没给通讯录权限")


def test_7_contacts_read_from_the_phone_do_not_stay_in_the_task_graph_or_on_the_card(env):
    from core.capabilities.canonical_dispatcher import get_canonical_dispatcher
    from core.device_onboarding.agent_tools import _list
    from core.task_graph_runtime import get_task_graph_runtime
    from core.unified.connection_manager import get_unified_connection_manager

    ucm = get_unified_connection_manager()
    contacts = {"success": True, "contacts": [{"name": "王小明", "phone": "13800000000"}]}

    class Phone:
        async def send_json(self, msg):
            reply = {"command_id": msg["command_id"], "payload": contacts}
            asyncio.get_running_loop().call_soon(ucm.resolve_command_response, msg["command_id"], reply)

    async def go():
        await ucm.register_connection("phone-1", Phone(), {})
        return await get_canonical_dispatcher().dispatch("device__phone-1__contacts", {"query": "王"}, session_id="s")

    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone", "transport": "websocket"})
    r = asyncio.run(go())
    assert r.success is True and r.result == contacts, "这一次的结果交给调用它的智能体"
    kept = str([(n.result_summary, n.error, n.metadata) for n in get_task_graph_runtime().all_nodes()])
    assert "王小明" not in kept and "13800000000" not in kept
    card = next(m for m in _list({})["members"] if m["device_id"] == "phone-1")
    assert card["recent"] and "王小明" not in str(card)


def test_7_a_finished_plan_keeps_no_step_results_on_disk(env):
    from core import task_plan
    from core.device_onboarding import agent_tools

    async def invoke(args, session_id):
        return {"success": True, "result": {"heart_rate": 72, "contacts": ["王小明"]}}

    env.setattr(agent_tools, "_invoke", invoke)
    out = asyncio.run(
        task_plan.run_plan({"goal": "读心率", "steps": [{"id": "a", "device_id": "watch", "action": "heart_rate"}]})
    )
    assert out["steps"][0]["result"]["result"]["heart_rate"] == 72, "这一次的结果交给发起计划的智能体"
    on_disk = (Path(task_plan._path())).read_text(encoding="utf-8")
    assert "王小明" not in on_disk and 'heart_rate": 72' not in on_disk
    looked = asyncio.run(agent_tools.dispatch_devices_tool("plan", {"plan_id": out["plan_id"]}))
    assert looked["steps"][0]["status"] == "success" and "result" not in looked["steps"][0]
    assert "不留" in looked["results"]
