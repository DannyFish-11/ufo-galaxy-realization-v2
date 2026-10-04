"""动手之前先记意图、动手之后再记结果；被叫停 / 重启时「结果不明」不是「失败」。

借自 AFK-surf/Comma 的运行时：副作用先落盘再执行；写入结果不明时返回 indeterminate
且**不授予重放的权力**。这里钉三件事：

1. **先记后动**：动作执行的那一刻，意图已经在盘上；
2. **叫停 / 取消**：正在飞的那一步记成 ``unknown_after_cancel``，随叫停的结果一起交还；
3. **重启**：只有意图没有结果的，补记 ``unknown_after_restart`` 并报出来，**绝不重放**。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import pytest

from core.action_journal import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_UNKNOWN_CANCEL,
    OUTCOME_UNKNOWN_RESTART,
    ActionJournal,
    get_action_journal,
    journaled,
    reset_action_journal,
)
from core.computer_use_loop import ComputerUseLoop
from core.desktop_presence_runtime import DesktopPresenceRuntime


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "journal.jsonl")


@pytest.fixture
def singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    reset_action_journal()
    yield get_action_journal()
    reset_action_journal()


def _records(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh.read().splitlines()]


# ── 1. 先记后动 ────────────────────────────────────────────────────────────


def test_the_intent_is_on_disk_before_the_action_runs(path):
    j = ActionJournal(path)
    seen = {}
    entry = j.begin("computer_use", "click", {"x": 3, "y": 4}, "rs-1")
    seen["on_disk_at_dispatch"] = [r["ev"] for r in _records(path)]
    j.end(entry, OUTCOME_OK)
    assert seen["on_disk_at_dispatch"] == ["begin"], "动手的那一刻，意图必须已经在盘上"
    assert [r["ev"] for r in _records(path)] == ["begin", "end"]


def test_outcomes_ok_and_failed_are_recorded(path):
    j = ActionJournal(path)
    a = j.begin("computer_use", "click", {}, "rs-1")
    j.end(a, OUTCOME_OK)
    b = j.begin("computer_use", "click", {}, "rs-1")
    j.end(b, OUTCOME_FAILED, "node unreachable")
    ends = [r for r in _records(path) if r["ev"] == "end"]
    assert [e["outcome"] for e in ends] == [OUTCOME_OK, OUTCOME_FAILED]
    assert ends[1]["error"] == "node unreachable"
    assert j.unknown_for("rs-1") == [], "成功和失败都不是「结果不明」"


def test_ending_twice_records_once(path):
    j = ActionJournal(path)
    e = j.begin("computer_use", "click", {}, "rs-1")
    j.end(e, OUTCOME_OK)
    j.end(e, OUTCOME_FAILED)
    assert len([r for r in _records(path) if r["ev"] == "end"]) == 1


def test_typed_text_and_secrets_never_reach_the_journal(path):
    j = ActionJournal(path)
    e = j.begin("computer_use", "type", {"text": "my-password-123", "password": "hunter2", "x": 1}, "rs-1")
    j.end(e, OUTCOME_OK)
    blob = open(path, encoding="utf-8").read()
    assert "my-password-123" not in blob and "hunter2" not in blob
    assert _records(path)[0]["params"]["text"] == {"len": 15}, "只留长度"
    assert _records(path)[0]["params"]["x"] == 1


# ── 2. 叫停 / 取消：正在飞的那一步结果不明 ────────────────────────────────


async def test_a_cancelled_action_is_unknown_not_failed_and_the_cancel_still_propagates(singleton):
    started = asyncio.Event()

    async def act():
        with journaled("computer_use", "click", {"x": 320, "y": 180}, runtime_session_id="rs-7"):
            started.set()
            await asyncio.sleep(3600)

    task = asyncio.create_task(act())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (unknown,) = singleton.unknown_for("rs-7")
    assert unknown["outcome"] == OUTCOME_UNKNOWN_CANCEL
    assert unknown["summary"] == "click(x=320, y=180)"
    assert singleton.status()["in_flight"] == 0


async def test_an_exception_is_recorded_as_failed_and_reraised(singleton):
    with pytest.raises(RuntimeError):
        with journaled("computer_use", "click", {}, runtime_session_id="rs-8"):
            raise RuntimeError("boom")
    assert singleton.unknown_for("rs-8") == []
    ends = [r for r in _records(singleton.status()["path"]) if r["ev"] == "end"]
    assert ends[-1]["outcome"] == OUTCOME_FAILED and "boom" in ends[-1]["error"]


async def test_stopping_the_request_hands_back_the_step_that_was_in_flight(singleton):
    """整条通路：请求在派发一次点击的途中被叫停 → 调用方拿到 stopped 的结果，并且里面
    写着「那一次点击不知道执行了没有」。"""
    rt = DesktopPresenceRuntime()
    started = asyncio.Event()

    async def _dispatch(*_a, **_k):
        with journaled("computer_use", "click", {"x": 10, "y": 20}):  # 会话 id 取自当前请求
            started.set()
            await asyncio.sleep(3600)

    rt._dispatch = _dispatch
    caller = asyncio.create_task(rt.handle_request("点一下", source="chat"))
    await asyncio.wait_for(started.wait(), 5)
    await rt.stop_current_activity(reason="panel")
    result = await asyncio.wait_for(caller, 5)

    assert result["stopped"] is True
    (unknown,) = result["unknown_actions"]
    assert unknown["outcome"] == OUTCOME_UNKNOWN_CANCEL
    assert unknown["summary"] == "click(x=10, y=20)"
    assert unknown["runtime_session_id"] == result["runtime_session_id"], "不是这一次请求里的步骤"


async def test_a_stop_with_nothing_in_flight_reports_no_unknown_actions(singleton):
    rt = DesktopPresenceRuntime()
    started = asyncio.Event()

    async def _dispatch(*_a, **_k):
        started.set()
        await asyncio.sleep(3600)

    rt._dispatch = _dispatch
    caller = asyncio.create_task(rt.handle_request("想想", source="chat"))
    await asyncio.wait_for(started.wait(), 5)
    await rt.stop_current_activity(reason="panel")
    assert (await asyncio.wait_for(caller, 5))["unknown_actions"] == []


# ── 3. 重启：只有意图没有结果 → 结果不明，绝不重放 ───────────────────────


def test_restart_reports_an_intent_without_an_outcome_and_never_replays_it(path, caplog):
    first = ActionJournal(path)
    done = first.begin("computer_use", "click", {"x": 1, "y": 1}, "rs-1")
    first.end(done, OUTCOME_OK)
    first.begin("computer_use", "click", {"x": 99, "y": 77}, "rs-1")  # 崩在这一步：没有 end

    with caplog.at_level(logging.WARNING, logger="Galaxy.ActionJournal"):
        second = ActionJournal(path)
    (rec,) = second.recovered
    assert rec["outcome"] == OUTCOME_UNKNOWN_RESTART
    assert rec["summary"] == "click(x=99, y=77)"
    assert "结果不明" in caplog.text and "不会自动重放" in caplog.text
    assert second.status()["in_flight"] == 0, "补记之后没有「还在飞」的残留"

    third = ActionJournal(path)  # 再重启一次：补记过的不再重复报
    assert third.recovered == []
    assert [r["summary"] for r in third.recent_unknown()] == ["click(x=99, y=77)"]


def test_a_half_written_line_is_ignored_not_believed(path):
    j = ActionJournal(path)
    j.end(j.begin("computer_use", "click", {}, "rs-1"), OUTCOME_OK)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"v":1,"ev":"begin","id":"deadbeef","t":1.0,"sid":"rs-1","sou')  # 崩在写的途中
    assert ActionJournal(path).recovered == [], "半行不是事实，不能当成一次未了结的操作"


def test_recent_unknown_forgets_what_is_too_old_to_be_useful(path):
    j = ActionJournal(path)
    e = j.begin("computer_use", "click", {}, "rs-1")
    j.end(e, OUTCOME_UNKNOWN_CANCEL)
    assert len(j.recent_unknown(window_s=60)) == 1
    assert j.recent_unknown(window_s=-1) == [], "过了窗口，屏幕早已不是当时的样子，报了只会误导"


def test_the_replay_reads_only_the_tail_of_a_huge_file(path, monkeypatch):
    import core.action_journal as mod

    monkeypatch.setattr(mod, "_MAX_LINES", 10)
    j = ActionJournal(path)
    j.begin("computer_use", "click", {"x": -1}, "rs-0")  # 很早以前的一条没了结的 —— 在读取窗口之外
    for i in range(12):
        j.end(j.begin("computer_use", "click", {"x": i}, "rs-1"), OUTCOME_OK)
    assert len(open(path, encoding="utf-8").read().splitlines()) == 25
    assert ActionJournal(path).recovered == [], "窗口之外的旧账不翻；窗口内成对的也不会被误报"


# ── 4. 降级必须留痕 ────────────────────────────────────────────────────────


def test_an_unwritable_journal_degrades_loudly_and_never_blocks_the_action(tmp_path, caplog):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    j = ActionJournal(str(blocker / "journal.jsonl"))  # 父路径是个文件：写不了
    with caplog.at_level(logging.WARNING, logger="Galaxy.ActionJournal"):
        e = j.begin("computer_use", "click", {}, "rs-1")
        j.end(e, OUTCOME_UNKNOWN_CANCEL)
        j.end(j.begin("computer_use", "click", {}, "rs-1"), OUTCOME_OK)
    assert j.status()["degraded"] is True and j.status()["degraded_reason"]
    assert caplog.text.count("降级为只在内存里记") == 1, "降级只说一次"
    assert len(j.unknown_for("rs-1")) == 1, "写不进盘，进程内的「结果不明」照样要报"


# ── 5. 接进电脑操作循环 ────────────────────────────────────────────────────


def _loop(script, act, tmp_path, monkeypatch):
    from tests.test_computer_use_loop import _ScriptedRouter

    monkeypatch.setenv("GALAXY_CU_SETTLE_S", "0")
    monkeypatch.setenv("GALAXY_CU_MEMORY", "0")
    monkeypatch.delenv("GALAXY_COMPUTER_USE", raising=False)

    async def perceive():
        return "FAKE_B64"

    return ComputerUseLoop(router=_ScriptedRouter(script=script), perceive_fn=perceive, act_fn=act)


def test_the_loop_journals_every_dispatched_action(singleton, tmp_path, monkeypatch):
    seen = {}

    async def act(action, params, node_id):
        # 动手的这一刻，意图已经在盘上。
        seen.setdefault("at_dispatch", []).append([r["ev"] for r in _records(singleton.status()["path"])])
        return {"success": True}

    loop = _loop(
        [{"action": "click", "x": 5, "y": 6}, {"action": "type", "text": "secret-text"}, {"action": "done"}],
        act,
        tmp_path,
        monkeypatch,
    )
    asyncio.run(loop.run("干点事"))
    recs = _records(singleton.status()["path"])
    assert [(r["ev"], r.get("action") or r.get("outcome")) for r in recs] == [
        ("begin", "click"),
        ("end", "ok"),
        ("begin", "type"),
        ("end", "ok"),
    ]
    assert seen["at_dispatch"][0] == ["begin"], "先记后动"
    assert "secret-text" not in open(singleton.status()["path"], encoding="utf-8").read()


def test_a_failed_action_is_recorded_as_failed(singleton, tmp_path, monkeypatch):
    async def act(action, params, node_id):
        return {"success": False, "error": "node down"}

    loop = _loop([{"action": "click", "x": 1, "y": 1}, {"action": "done"}], act, tmp_path, monkeypatch)
    asyncio.run(loop.run("点"))
    ends = [r for r in _records(singleton.status()["path"]) if r["ev"] == "end"]
    assert ends[0]["outcome"] == OUTCOME_FAILED and ends[0]["error"] == "node down"


def test_cancelling_the_loop_mid_action_leaves_that_step_unknown(singleton, tmp_path, monkeypatch):
    async def go():
        started = asyncio.Event()

        async def act(action, params, node_id):
            started.set()
            await asyncio.sleep(3600)

        loop = _loop([{"action": "click", "x": 8, "y": 9}, {"action": "done"}], act, tmp_path, monkeypatch)
        task = asyncio.create_task(loop.run("点"))
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    (unknown,) = singleton.recent_unknown()
    assert unknown["outcome"] == OUTCOME_UNKNOWN_CANCEL and unknown["action"] == "click"


# ── 6. 混合执行：对所有目标记账，只对本机报「在动手」 ─────────────────────


@pytest.mark.parametrize(("device_id", "acting_expected"), [("local", True), ("phone-3", False)])
async def test_hybrid_execution_journals_every_target_but_claims_to_operate_only_here(
    singleton, device_id, acting_expected
):
    from core.desktop_presence_runtime import RuntimeSession
    from core.hybrid_executor import HybridExecutionArbiter
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session

    s = RuntimeSession("chat")
    seen = {}

    async def body(*_a, **_k):
        seen["acting"] = s.acting
        return "done"

    arbiter = HybridExecutionArbiter.__new__(HybridExecutionArbiter)
    arbiter._execute_body = body
    token = bind_runtime_session(s)
    try:
        assert await arbiter.execute(device_id, "wechat", "send") == "done"
    finally:
        unbind_runtime_session(token)

    assert seen["acting"] is acting_expected
    recs = _records(singleton.status()["path"])
    assert recs[0]["ev"] == "begin" and recs[0]["params"]["device_id"] == device_id
    assert recs[-1]["outcome"] == OUTCOME_OK


# ── 7. 面板那一侧能读到 ────────────────────────────────────────────────────


def test_the_done_frame_carries_the_unknown_actions():
    from core.presence_stop import stop_fields

    result = {"stopped": True, "unknown_actions": [{"summary": "click(x=1, y=2)"}]}
    assert stop_fields(result) == {"stopped": True, "unknown_actions": [{"summary": "click(x=1, y=2)"}]}
    assert stop_fields({}) == {"stopped": False, "unknown_actions": []}


def test_the_journal_file_lives_under_the_data_dir(singleton, tmp_path):
    assert os.path.dirname(singleton.status()["path"]) == str(tmp_path)


def test_the_panel_can_ask_for_unresolved_actions(singleton):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes.panel import create_router

    singleton.end(
        singleton.begin("computer_use", "type", {"text": "secret-text", "x": 1}, "rs-1"), OUTCOME_UNKNOWN_CANCEL
    )
    singleton.end(singleton.begin("computer_use", "click", {"x": 2, "y": 3}, "rs-1"), OUTCOME_OK)
    app = FastAPI()
    app.include_router(create_router())
    resp = TestClient(app).get("/api/v1/presence/unresolved-actions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True and body["journal_degraded"] is False
    assert [a["outcome"] for a in body["actions"]] == [OUTCOME_UNKNOWN_CANCEL]
    assert "secret-text" not in resp.text, "人输入过的文字不该出现在这里"
    assert set(body["actions"][0]) == {"summary", "outcome", "source", "t_end"}, "只给面板要说的那几项"
