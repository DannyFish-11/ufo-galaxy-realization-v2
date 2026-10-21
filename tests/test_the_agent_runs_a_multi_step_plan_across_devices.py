"""智能体写一份多步计划,系统按依赖分层执行:同层并行、同一台设备串行、一步失败把原因交回模型、重启后接着做。

跨设备整体方案阶段 4(``devices__plan``,方案里叫 ``tasks__plan``;执行用现成的 ConstellationRuntime
分层执行,挑设备听模型的)。前半部分把「对某台设备做一件事」换成可观测的假实现,看顺序与并发;最后一段走
真实的规范设备入口,让手表按计划先后收到两条命令。
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from core import device_queue, task_plan
from core.device_onboarding import agent_tools
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    _connect,
    _eventually,
    _online,
    _recv,
    _register,
    _watch_command_result_frame,
    gateway,
    watch_id,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    device_queue.reset_queues()
    yield
    device_queue.reset_queues()


class _Devices:
    """假的「对某台设备做一件事」:记下每件事在哪台设备、什么时候开始结束。"""

    def __init__(self, fail=(), delay=0.15):
        self.log, self.fail, self.delay = [], set(fail), delay

    async def invoke(self, args, session_id):
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        self.log.append((args["device_id"], args["action"], start, time.monotonic()))
        if args["action"] in self.fail:
            return {"success": False, "error": f"{args['action']} 在 {args['device_id']} 上没做成:屏幕锁着"}
        return {"success": True, "result": {"did": args["action"]}}

    def span(self, action):
        return next((s, e) for _d, a, s, e in self.log if a == action)


def _plan(steps, goal="下班回家前把家里准备好"):
    return {"goal": goal, "steps": steps}


def _run(args, devices, monkeypatch):
    monkeypatch.setattr(agent_tools, "_invoke", devices.invoke)
    return asyncio.run(agent_tools.dispatch_devices_tool("plan", args, session_id="sess-plan"))


# ── 计划本身 ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "steps,expect",
    [
        ([], "至少一步"),
        ([{"id": "a", "action": "notify"}], "没写 device_id"),
        ([{"id": "a", "device_id": "w", "action": "notify", "goal": "x"}], "二选一"),
        ([{"id": "a", "device_id": "w", "action": "notify", "depends_on": ["zz"]}], "不在这份计划里"),
        (
            [
                {"id": "a", "device_id": "w", "action": "x", "depends_on": ["b"]},
                {"id": "b", "device_id": "w", "action": "y", "depends_on": ["a"]},
            ],
            "有环",
        ),
        ([{"id": f"s{i}", "device_id": "w", "action": "x"} for i in range(task_plan.MAX_STEPS + 1)], "最多"),
    ],
)
def test_a_plan_that_does_not_make_sense_is_sent_back_with_the_reason(steps, expect, monkeypatch):
    out = _run(_plan(steps), _Devices(), monkeypatch)
    assert out["success"] is False and expect in out["error"], out


def test_the_tool_is_offered_to_the_agent():
    names = {t["function"]["name"] for t in agent_tools.devices_tools_for_agent()}
    assert "devices__plan" in names


# ── 顺序与并发 ──────────────────────────────────────────────────────────────────


def test_dependencies_order_the_steps_different_devices_run_together_and_one_device_runs_one_at_a_time(monkeypatch):
    devices = _Devices()
    out = _run(
        _plan(
            [
                {"id": "lights", "device_id": "home-hub", "action": "turn_on"},
                {"id": "ac", "device_id": "phone", "action": "open_app", "params": {"app": "空调"}},
                {"id": "warm", "device_id": "home-hub", "action": "set_temp", "depends_on": ["lights"]},
                {"id": "music", "device_id": "home-hub", "action": "play"},
                {"id": "tell", "device_id": "watch", "action": "notify", "depends_on": ["ac", "warm"]},
            ]
        ),
        devices,
        monkeypatch,
    )
    assert out["success"] is True, out
    assert [s["status"] for s in out["steps"]] == ["success"] * 5
    lights, ac, warm, music, tell = (devices.span(a) for a in ("turn_on", "open_app", "set_temp", "play", "notify"))
    assert lights[0] < ac[1] and ac[0] < lights[1], "不同设备、没有依赖的两步同时做"
    assert music[0] >= lights[1] - 0.01 or lights[0] >= music[1] - 0.01, "同一台设备一次只做一件"
    assert warm[0] >= lights[1] - 0.01, "依赖的那一步做完才开始"
    assert tell[0] >= max(ac[1], warm[1]) - 0.01, "两个依赖都做完才开始"


def test_a_failed_step_comes_back_with_its_reason_and_what_depends_on_it_is_not_done(monkeypatch):
    out = _run(
        _plan(
            [
                {"id": "unlock", "device_id": "phone", "action": "unlock"},
                {"id": "pay", "device_id": "phone", "action": "pay", "depends_on": ["unlock"]},
                {"id": "lights", "device_id": "home-hub", "action": "turn_on"},
            ]
        ),
        _Devices(fail={"unlock"}),
        monkeypatch,
    )
    by = {s["id"]: s for s in out["steps"]}
    assert out["success"] is False and out["summary"] == "1/3 步成功"
    assert by["unlock"]["status"] == "failed" and "屏幕锁着" in by["unlock"]["error"]
    assert by["pay"]["status"] == "skipped" and "unlock" in by["pay"]["error"]
    assert by["lights"]["status"] == "success", "不相关的那一步照做"
    assert "next" in out, "告诉模型下一步可以怎么办,由它决定"


def test_a_goal_step_is_delegated_with_what_the_earlier_steps_found(monkeypatch):
    from core import phone_bridge

    seen = {}

    async def fake_delegate(device_id, goal, *, constraints=None, timeout=0, session_id="", steps=None):
        seen.update(device_id=device_id, goal=goal, constraints=constraints)
        return {"success": True, "summary": "已叫车"}

    monkeypatch.setattr(phone_bridge, "delegate", fake_delegate)
    out = _run(
        _plan(
            [
                {"id": "where", "device_id": "pc", "action": "get_calendar"},
                {
                    "id": "taxi",
                    "device_id": "phone",
                    "goal": "叫车去日程里的地点",
                    "constraints": ["不要付款"],
                    "depends_on": ["where"],
                },
            ]
        ),
        _Devices(),
        monkeypatch,
    )
    assert out["success"] is True, out
    assert seen["device_id"] == "phone" and seen["goal"] == "叫车去日程里的地点"
    assert seen["constraints"][0] == "不要付款"
    assert "get_calendar" in seen["constraints"][1], "前一步的结果跟着交过去"


def test_the_plan_is_on_disk_and_in_the_task_graph(monkeypatch):
    from core.task_graph_runtime import _is_projection_only, get_task_graph_runtime

    out = _run(_plan([{"id": "a", "device_id": "watch", "action": "notify"}]), _Devices(), monkeypatch)
    state = task_plan.plan_state(out["plan_id"])
    assert state and state["finished_at"] and state["steps"][0]["status"] == "success"
    looked = asyncio.run(agent_tools.dispatch_devices_tool("plan", {"plan_id": out["plan_id"]}))
    assert looked["finished"] is True and looked["steps"][0]["status"] == "success", "只给 plan_id 能查到它此刻怎么样"
    assert asyncio.run(agent_tools.dispatch_devices_tool("plan", {"plan_id": "plan_nope"}))["success"] is False
    nodes = [n for n in get_task_graph_runtime().all_nodes() if (n.metadata or {}).get("plan_id") == out["plan_id"]]
    assert nodes and nodes[0].tool_name == "devices__plan"
    assert _is_projection_only(nodes[0]), "只为观测记的节点,重启续跑不拿它去重派(计划自己续跑)"


# ── 重启后接着做 ───────────────────────────────────────────────────────────────


def test_after_a_restart_only_the_unfinished_steps_whose_inputs_are_ready_run(tmp_path, monkeypatch):
    plan, _ = task_plan.parse_plan(
        _plan(
            [
                {"id": "a", "device_id": "phone", "action": "open_app"},
                {"id": "b", "device_id": "phone", "action": "send_message", "depends_on": ["a"]},
                {"id": "c", "device_id": "watch", "action": "notify", "depends_on": ["a"]},
                {"id": "d", "device_id": "watch", "action": "haptic", "depends_on": ["b"]},
            ]
        ),
        session_id="sess-resume",
    )
    plan["steps"][0]["status"] = "success"
    plan["steps"][1]["status"] = "running"  # 崩溃那一刻正在发消息
    task_plan._save(plan)

    devices = _Devices()
    notes = []

    async def fake_record(**kw):
        notes.append(kw)

    import core.session_memory_facade as smf

    monkeypatch.setattr(agent_tools, "_invoke", devices.invoke)
    monkeypatch.setattr(task_plan, "_online", lambda d: True)
    monkeypatch.setattr(smf, "record_session_turn", fake_record)

    async def scenario():
        out = await task_plan.resume_unfinished_plans()
        assert out["resumed_plans"] == [plan["plan_id"]]
        await asyncio.gather(*list(task_plan._tasks))

    asyncio.run(scenario())
    state = task_plan.plan_state(plan["plan_id"])
    by = {s["id"]: s for s in state["steps"]}
    assert (
        by["b"]["status"] == "unknown" and "没有自动重做" in by["b"]["error"]
    ), "崩溃时在做的那一步不重做,免得重复发消息"
    assert by["c"]["status"] == "success", "依赖都做完了的接着做"
    assert by["d"]["status"] == "skipped", "依赖结果不明的不做"
    assert [a for _d, a, _s, _e in devices.log] == ["notify"], "做完的、结果不明的都没再动手"
    assert notes and notes[0]["conversation_session_id"] == "sess-resume", "结果记进发起计划的会话,智能体下一轮看得到"
    assert "2/4 步成功" in notes[0]["content"]


def test_a_step_still_waiting_in_a_devices_queue_is_not_marked_as_being_done(monkeypatch):
    """排着队的那一步还没动过设备:崩溃后要接着做,不能记成「正在做」(那样重启后会被当成结果不明、永远不做)。"""
    gate = {}

    async def blocking_invoke(args, session_id):
        gate.setdefault(args["action"], asyncio.Event())
        await gate[args["action"]].wait()
        return {"success": True}

    monkeypatch.setattr(agent_tools, "_invoke", blocking_invoke)

    async def scenario():
        run = asyncio.create_task(
            agent_tools.dispatch_devices_tool(
                "plan",
                _plan(
                    [
                        {"id": "first", "device_id": "phone", "action": "a"},
                        {"id": "second", "device_id": "phone", "action": "b"},
                    ]
                ),
            )
        )
        for _ in range(50):
            await asyncio.sleep(0.02)
            if "a" in gate:
                break
        data = task_plan._load_all()["active"]
        [plan] = data.values()
        statuses = {s["id"]: s["status"] for s in plan["steps"]}
        gate["a"].set()
        for _ in range(50):
            await asyncio.sleep(0.02)
            if "b" in gate:
                break
        gate["b"].set()
        out = await run
        return statuses, out

    statuses, out = asyncio.run(scenario())
    assert statuses == {"first": "running", "second": "pending"}, statuses
    assert out["success"] is True


def test_steps_queued_behind_a_busy_device_do_not_use_up_the_dispatch_limit(monkeypatch):
    """同时下发的名额轮到了才占:排在一台忙设备后面的几步不占名额,别的设备上的步骤照样马上做。"""
    monkeypatch.setenv("GALAXY_MULTI_DEVICE_DISPATCH_LIMIT", "1")
    started = []
    gate = {}

    async def invoke(args, session_id):
        started.append(args["device_id"] + ":" + args["action"])
        if args["device_id"] == "phone":
            gate.setdefault(args["action"], asyncio.Event())
            await gate[args["action"]].wait()
        return {"success": True}

    monkeypatch.setattr(agent_tools, "_invoke", invoke)

    async def scenario():
        run = asyncio.create_task(
            agent_tools.dispatch_devices_tool(
                "plan",
                _plan(
                    [
                        {"id": "p1", "device_id": "phone", "action": "a"},
                        {"id": "p2", "device_id": "phone", "action": "b"},
                        {"id": "w1", "device_id": "watch", "action": "notify"},
                    ]
                ),
            )
        )
        for _ in range(50):
            await asyncio.sleep(0.02)
            if "a" in gate:
                break
        gate["a"].set()
        for _ in range(50):
            await asyncio.sleep(0.02)
            if "b" in gate:
                break
        seen = list(started)
        gate["b"].set()
        return seen, await run

    seen, out = asyncio.run(scenario())
    assert out["success"] is True, out
    assert seen.index("watch:notify") < seen.index("phone:b"), f"手表那步被排在手机后面的步骤挡住了:{seen}"


# ── 每台设备一个队列 ─────────────────────────────────────────────────────────────


def test_the_same_device_does_one_thing_at_a_time_and_different_devices_do_not_wait():
    spans = {}

    def job(name):
        async def run():
            s = time.monotonic()
            await asyncio.sleep(0.15)
            spans[name] = (s, time.monotonic())
            return {"success": True}

        return run

    async def scenario():
        await asyncio.gather(
            device_queue.run_on_device("phone", job("p1")),
            device_queue.run_on_device("phone", job("p2")),
            device_queue.run_on_device("watch", job("w1")),
        )

    asyncio.run(scenario())
    (p1s, p1e), (p2s, p2e), (w1s, w1e) = spans["p1"], spans["p2"], spans["w1"]
    assert p2s >= p1e - 0.01 or p1s >= p2e - 0.01, "同一台手机不同时做两件事"
    assert w1s < max(p1e, p2e) and w1e > min(p1s, p2s), "手表不用等手机"


def test_a_device_with_too_much_queued_says_so():
    async def scenario():
        gate = asyncio.Event()

        async def slow():
            await gate.wait()
            return {"success": True}

        pending = [
            asyncio.create_task(device_queue.run_on_device("phone", slow)) for _ in range(device_queue.MAX_WAITING + 2)
        ]
        await asyncio.sleep(0.2)
        refused = [t.result() for t in pending if t.done()]
        gate.set()
        await asyncio.gather(*pending)
        return refused

    refused = asyncio.run(scenario())
    assert refused and all(r["success"] is False and "排着" in r["error"] for r in refused)


# ── 真实入口:手表按计划先后收到两条命令 ─────────────────────────────────────────


def test_a_plan_drives_a_real_watch_step_by_step(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        assert _eventually(lambda: _online(watch_id))

        async def plan():
            return await agent_tools.dispatch_devices_tool(
                "plan",
                _plan(
                    [
                        {"id": "tell", "device_id": watch_id, "action": "notify", "params": {"text": "快到家了"}},
                        {"id": "check", "device_id": watch_id, "action": "get_status", "depends_on": ["tell"]},
                    ]
                ),
                session_id="sess-watch",
            )

        pending = gateway.portal.start_task_soon(plan)
        first = _recv(ws, timeout=10.0)
        assert first.get("type") == "command" and first.get("command") == "notify", first
        ws.send_json(_watch_command_result_frame(watch_id, first["command_id"], True, {"shown": True}))
        second = _recv(ws, timeout=10.0)
        assert second.get("type") == "command" and second.get("command") == "get_status", "依赖的那一步做完才发第二条"
        ws.send_json(_watch_command_result_frame(watch_id, second["command_id"], True, {"battery": 80}))
        out = pending.result(timeout=15)
    assert out["success"] is True, json.dumps(out, ensure_ascii=False)
    assert [s["status"] for s in out["steps"]] == ["success", "success"]
