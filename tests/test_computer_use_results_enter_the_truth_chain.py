"""Computer Use 的结果进真相链:模型说「做完了」只是自报,裁决来自独立核对 + 规范执法函数。

所有者 2026-10-13 选 A。原先闭环里模型回 ``done`` 就算成功,屏幕上到底成了没有谁也没核对过。现在:

* 核对员只拿到任务和一张**新取的**屏幕,看不到规划过程与模型的自报;
* 四值裁决由 ``classify_execution_evidence`` 给;核对说没做完 → ``quarantine``(没收口);
* 没收口的与 ``task_result`` 同一条规矩:后台把没做完的部分再做一次、再核对一次,仍不行进隔离队列;
* 运维的三个结案动作落在这个队列上:重开 = 再试一次、确认 = 认可、驳回 = 知悉。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.computer_use_verdict as verdict
from core.truth_chain_recovery import (
    STATE_ACCEPTED,
    STATE_DISMISSED,
    STATE_ISOLATED,
    STATE_RECOVERED,
    TruthChainRecovery,
    get_truth_chain_recovery,
    register_rerunner,
)

DONE = {"success": True, "stop_reason": "done", "message": "已经打开记事本", "steps": [{"action": "click"}]}


def _screen(b64: str = "c2NyZWVu"):
    async def perceive():
        return b64

    return perceive


def _says(answer):
    seen: List[Tuple[str, str]] = []

    async def ask(instruction: str, screen: str):
        seen.append((instruction, screen))
        return answer

    ask.seen = seen  # type: ignore[attr-defined]
    return ask


@pytest.fixture(autouse=True)
def own_queue(tmp_path):
    """每个用例一个干净的隔离队列(队列落盘,不隔开的话上一个用例留下的条目会被读回来)。"""
    recovery = get_truth_chain_recovery()
    recovery.reset()
    recovery._explicit_store_path = tmp_path / "isolated_results.json"
    yield recovery
    recovery.reset()
    recovery._explicit_store_path = None


@pytest.fixture()
def nobody_at_the_computer(monkeypatch):
    monkeypatch.setattr(verdict, "_someone_is_using_the_computer", lambda: False)


def _settle(result: Dict[str, Any], *, perceive=None, ask=None, schedule: bool = False) -> Dict[str, Any]:
    async def run():
        return await verdict.settle("打开记事本", result, perceive=perceive, ask=ask, schedule=schedule)

    return asyncio.run(run())


# ── 裁决 ──────────────────────────────────────────────────────────────────────


def test_a_confirmed_screen_is_trusted():
    out = _settle(DONE, perceive=_screen(), ask=_says({"done": True, "reason": "记事本窗口在前台"}))
    assert out["claimed_done"] is True
    assert out["verdict"] == "trusted" and out["success"] is True
    assert out["verdict_reason"] == "记事本窗口在前台"


def test_the_checker_sees_only_the_task_and_a_fresh_screen():
    ask = _says({"done": True})
    _settle(DONE, perceive=_screen("ZnJlc2g="), ask=ask)
    assert ask.seen == [("打开记事本", "ZnJlc2g=")]  # 没有模型的自报、没有步骤


def test_the_check_prompt_does_not_take_the_claim_on_trust():
    assert "不要相信" in verdict._CHECK_SYSTEM and "当前" in verdict._CHECK_SYSTEM


@pytest.mark.parametrize(
    "perceive,ask,why",
    [
        (_screen(""), _says({"done": True}), "没有新鲜的屏幕"),
        (_screen(), _says(None), "没有能看图的模型"),
        (_screen(), _says({"done": None, "reason": "被别的窗口挡住"}), "被别的窗口挡住"),
    ],
)
def test_what_cannot_be_checked_is_provisional_and_says_so(perceive, ask, why):
    out = _settle(DONE, perceive=perceive, ask=ask)
    assert out["verdict"] == "provisional" and out["success"] is True
    assert "没法独立核对" in out["message"] and why in out["message"]
    assert not get_truth_chain_recovery().isolated()


def test_a_checker_that_raises_or_hangs_is_unverifiable_not_a_failure(monkeypatch):
    async def boom(instruction, screen):
        raise RuntimeError("router down")

    assert _settle(DONE, perceive=_screen(), ask=boom)["verdict"] == "provisional"

    async def hangs(instruction, screen):
        await asyncio.sleep(5)

    monkeypatch.setattr(verdict, "CHECK_TIMEOUT_S", 0.05)
    out = _settle(DONE, perceive=_screen(), ask=hangs)
    assert out["verdict"] == "provisional" and "秒没回" in out["verdict_reason"]


@pytest.mark.parametrize("stop_reason", ["fail", "max_steps", "loop_detected", "no_screen", "dry_run"])
def test_what_the_model_never_claimed_done_is_left_alone(stop_reason):
    result = {"success": False, "stop_reason": stop_reason, "message": "没做成"}
    assert _settle(result, perceive=_screen(), ask=_says({"done": True})) == result
    assert not get_truth_chain_recovery().isolated()


def test_the_verdict_comes_from_the_canonical_enforcement_function(monkeypatch):
    import core.execution_evidence_model as model

    calls = []
    real = model.classify_execution_evidence

    def spy(*a, **kw):
        calls.append((a, kw))
        return real(*a, **kw)

    monkeypatch.setattr(model, "classify_execution_evidence", spy)
    assert verdict.classify(verdict.CHECK_VERIFIED) == "trusted"
    assert verdict.classify(verdict.CHECK_NOT_DONE) == "quarantine"
    assert verdict.classify(verdict.CHECK_UNVERIFIABLE) == "provisional"
    assert len(calls) == 3


# ── 没收口:后台再做一次,仍不行进隔离队列 ───────────────────────────────────────


def _not_done_then(closes: bool, monkeypatch, delay: float = 0.0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    recovery = get_truth_chain_recovery()
    monkeypatch.setattr(recovery, "delay_s", delay)
    calls: List[Tuple[Dict[str, Any], bool]] = []

    async def rerun(message, by_human):
        calls.append((message, by_human))
        return closes, "补做完了" if closes else "还是没有记事本窗口"

    monkeypatch.setattr(verdict, "rerun_once", rerun)

    async def run():
        out = await verdict.settle(
            "打开记事本", DONE, perceive=_screen(), ask=_says({"done": False, "reason": "桌面上没有记事本"})
        )
        assert recovery.summary()["pending_retry"] == 1
        settled = await recovery.run_pending_rerun(out["task_id"])
        return out, settled

    out, settled = asyncio.run(run())
    assert calls == [({"instruction": "打开记事本", "reason": "桌面上没有记事本"}, False)]
    return out, settled


def test_not_done_is_quarantined_and_redone_in_the_background(nobody_at_the_computer, monkeypatch):
    out, settled = _not_done_then(True, monkeypatch)
    assert out["verdict"] == "quarantine" and out["success"] is False
    assert "核对没通过" in out["message"] and "后台再做一次" in out["follow_up"]
    assert settled["state"] == STATE_RECOVERED and settled["kind"] == "computer_use"
    assert not get_truth_chain_recovery().isolated()


def test_still_not_done_after_the_redo_goes_to_the_isolated_queue(nobody_at_the_computer, monkeypatch):
    out, settled = _not_done_then(False, monkeypatch)
    assert settled["state"] == STATE_ISOLATED
    rows = get_truth_chain_recovery().isolated()
    assert [(r["key"], r["kind"], r["attempts"]) for r in rows] == [(out["task_id"], "computer_use", 2)]
    assert rows[0]["first_incomplete_reason"] == "桌面上没有记事本"
    assert rows[0]["incomplete_reason"] == "还是没有记事本窗口"
    assert rows[0]["message_retained"] is True


def test_the_background_redo_is_armed_on_the_loop(nobody_at_the_computer, monkeypatch):
    recovery = get_truth_chain_recovery()
    monkeypatch.setattr(recovery, "delay_s", 0.01)

    async def rerun(message, by_human):
        return True, "补做完了"

    monkeypatch.setattr(verdict, "rerun_once", rerun)

    async def run():
        out = await verdict.settle("打开记事本", DONE, perceive=_screen(), ask=_says({"done": False}))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if recovery.recent_recovered():
                break
        return out

    out = asyncio.run(run())
    assert [r["key"] for r in recovery.recent_recovered()] == [out["task_id"]]


def test_someone_at_the_computer_means_no_background_hands(monkeypatch):
    monkeypatch.setattr(verdict, "_someone_is_using_the_computer", lambda: True)
    out = _settle(DONE, perceive=_screen(), ask=_says({"done": False, "reason": "没打开"}), schedule=True)
    assert "人正在用电脑" in out["follow_up"]
    recovery = get_truth_chain_recovery()
    assert recovery.summary()["pending_retry"] == 0
    assert [r["key"] for r in recovery.isolated()] == [out["task_id"]]


def test_the_background_rerunner_does_not_touch_the_keyboard_while_someone_is_there(monkeypatch):
    monkeypatch.setattr(verdict, "_someone_is_using_the_computer", lambda: True)
    ran = []

    async def loop(instruction, **kw):
        ran.append(instruction)
        return {"stop_reason": "done"}

    monkeypatch.setattr("core.computer_use_loop.run_computer_use_task", loop)
    closed, why = asyncio.run(verdict.rerun_once({"instruction": "打开记事本", "reason": "没打开"}))
    assert (closed, ran) == (False, []) and "人正在用电脑" in why

    async def verified(instruction, **kw):
        return verdict.CHECK_VERIFIED, "看到了"

    monkeypatch.setattr(verdict, "independent_check", verified)
    closed, why = asyncio.run(verdict.rerun_once({"instruction": "打开记事本", "reason": "没打开"}, True))
    assert closed is True and len(ran) == 1
    assert ran[0].startswith("打开记事本") and "只做还没完成的部分" in ran[0]


def test_the_redo_runs_the_loop_without_a_second_nested_verdict(monkeypatch, nobody_at_the_computer):
    kwargs = {}

    async def loop(instruction, **kw):
        kwargs.update(kw)
        return {"stop_reason": "fail", "message": "找不到"}

    monkeypatch.setattr("core.computer_use_loop.run_computer_use_task", loop)
    closed, why = asyncio.run(verdict.rerun_once({"instruction": "打开记事本"}))
    assert closed is False and kwargs == {"verify": False} and "fail" in why


def test_the_loop_entry_settles_what_it_runs(monkeypatch):
    import core.computer_use_loop as cul

    async def run(self, instruction, max_steps=None, dry_run=False):
        return dict(DONE)

    seen = []

    async def settle(instruction, result):
        seen.append(instruction)
        return {**result, "verdict": "trusted"}

    monkeypatch.setattr(cul.ComputerUseLoop, "run", run)
    monkeypatch.setattr(verdict, "settle", settle)
    assert asyncio.run(cul.run_computer_use_task("打开记事本"))["verdict"] == "trusted"
    assert "verdict" not in asyncio.run(cul.run_computer_use_task("打开记事本", verify=False))
    assert "verdict" not in asyncio.run(cul.run_computer_use_task("打开记事本", dry_run=True))
    assert seen == ["打开记事本"]


def test_the_arbiters_vision_level_checks_but_never_redoes_in_the_background(monkeypatch):
    """仲裁器视觉级只是调用方任务里的一步:核对照做,没通过照实回失败,不排后台重做(会和调用方撞车)。"""
    import core.computer_use_loop as cul
    from core.windows_execution_arbiter import _make_default_vlm_executor

    monkeypatch.setattr(cul, "computer_use_enabled", lambda: True)

    async def loop(instruction, **kw):
        assert kw == {"verify": False}
        return dict(DONE)

    scheduled = []

    async def settle(instruction, result, *, schedule=True, **kw):
        scheduled.append(schedule)
        return {**result, "success": False, "verdict": "quarantine", "message": "核对没通过"}

    monkeypatch.setattr(cul, "run_computer_use_task", loop)
    monkeypatch.setattr(verdict, "settle", settle)
    out = asyncio.run(_make_default_vlm_executor()("this", "点保存", None))
    assert out["success"] is False and out["verdict"] == "quarantine" and scheduled == [False]


def test_the_sync_wait_covers_the_check(monkeypatch):
    from core.windows_execution_arbiter import _SYNC_DISPATCH_HEADROOM, _sync_dispatch_budget_s

    monkeypatch.setenv("GALAXY_CU_MAX_STEPS", "1")
    monkeypatch.setenv("GALAXY_CU_SETTLE_S", "0")
    assert _sync_dispatch_budget_s() == pytest.approx((60.0 + verdict.CHECK_TIMEOUT_S) * _SYNC_DISPATCH_HEADROOM)


# ── 隔离队列:人的三个动作 ─────────────────────────────────────────────────────


def _isolated(recovery: TruthChainRecovery, task_id: str = "cu_t1") -> str:
    recovery.isolate(
        task_id,
        "computer_use",
        {"task_id": task_id, "result_status": "claimed_done", "incomplete_reason": "没打开"},
        {"instruction": "打开记事本", "reason": "没打开"},
        "没打开",
    )
    return task_id


def test_retry_by_a_human_runs_even_while_someone_is_at_the_computer(monkeypatch):
    recovery = get_truth_chain_recovery()
    key = _isolated(recovery)
    seen = []

    async def rerun(message, by_human):
        seen.append(by_human)
        return True, "这次看到了"

    register_rerunner("computer_use", rerun)
    try:
        row = recovery.retry_isolated(key)  # 不在事件循环里:就地跑完
    finally:
        verdict.register()
    assert seen == [True] and row["state"] == STATE_RECOVERED
    assert recovery.find_by_task_id(key) is None


def test_retry_on_the_loop_answers_retrying_and_settles_in_the_background(monkeypatch):
    recovery = get_truth_chain_recovery()
    key = _isolated(recovery)

    async def run():
        release = asyncio.Event()

        async def rerun(message, by_human):
            await release.wait()
            return False, "还是没有"

        register_rerunner("computer_use", rerun)
        first = recovery.retry_isolated(key)
        again = recovery.retry_isolated(key)  # 正在重做时再点一次:不叠第二个
        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not (recovery.get(key) or {}).get("retrying"):
                break
        return first, again

    try:
        first, again = asyncio.run(run())
    finally:
        verdict.register()
    assert first["state"] == "retrying" and again["state"] == "retrying"
    row = recovery.get(key)
    assert row["state"] == STATE_ISOLATED and row["attempts"] == 2 and row["incomplete_reason"] == "还是没有"
    assert "retrying" not in row


def test_accept_and_dismiss_keep_the_record_and_leave_the_open_list():
    recovery = get_truth_chain_recovery()
    a, d = _isolated(recovery, "cu_a"), _isolated(recovery, "cu_d")
    assert recovery.accept(a)["state"] == STATE_ACCEPTED
    assert recovery.dismiss(d)["state"] == STATE_DISMISSED
    assert recovery.isolated() == []
    assert {r["key"]: r["state"] for r in recovery.isolated(include_dismissed=True)} == {
        "cu_a": STATE_ACCEPTED,
        "cu_d": STATE_DISMISSED,
    }
    assert recovery.summary()["accepted"] == 1 and recovery.summary()["dismissed"] == 1
    assert recovery.find_by_task_id("cu_a") is None  # 已认可的不再是「没收口」
    assert recovery.accept("nope") is None


def test_the_accept_endpoint():
    from core.routes import result_recovery
    from tests.test_truth_chain_recovery import _AUTH_HEADERS

    key = _isolated(get_truth_chain_recovery(), "cu_api")
    app = FastAPI()
    app.include_router(result_recovery.create_router())
    with TestClient(app, headers=_AUTH_HEADERS) as client:
        item = client.get("/api/v1/results/isolated").json()["items"][0]
        assert (item["key"], item["kind"]) == (key, "computer_use") and "message" not in item
        assert client.post(f"/api/v1/results/isolated/{key}/accept").json()["state"] == STATE_ACCEPTED
        assert client.post("/api/v1/results/isolated/none/accept").status_code == 404


def test_the_accept_endpoint_needs_a_token(monkeypatch):
    from core.routes import result_recovery

    monkeypatch.setenv("GALAXY_API_TOKEN", "sekrit")
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "1")
    app = FastAPI()
    app.include_router(result_recovery.create_router())
    with TestClient(app) as client:
        assert client.post("/api/v1/results/isolated/x/accept").status_code in (401, 403)


def test_a_rerunner_registers_itself_after_a_restart():
    import core.truth_chain_recovery as tcr

    tcr._RERUNNERS.pop("computer_use", None)
    assert tcr._rerunner("computer_use") is verdict.rerun_once


# ── 运维的结案动作 = 队列上的动作 ─────────────────────────────────────────────


def _closure(kind: str, task_id: str) -> Dict[str, Any]:
    from core.pr4_operator_action_governance import execute_governed_operator_action

    return execute_governed_operator_action(
        action_kind=kind, action_id=f"act_{kind}_{task_id}", operator_user_id="admin", task_id=task_id
    )


def test_finalize_is_accept_and_reject_is_dismiss():
    recovery = get_truth_chain_recovery()
    _isolated(recovery, "cu_fin")
    _isolated(recovery, "cu_rej")
    fin = _closure("finalize_closure", "cu_fin")
    rej = _closure("reject_closure", "cu_rej")
    assert fin["outcome"] == "success" and "closure_finalized:accepted" in fin["downstream_effects"]
    assert rej["outcome"] == "success" and "closure_rejected:dismissed" in rej["downstream_effects"]
    assert recovery.get("cu_fin")["state"] == STATE_ACCEPTED
    assert recovery.get("cu_rej")["state"] == STATE_DISMISSED


def test_reopen_is_retry():
    recovery = get_truth_chain_recovery()
    _isolated(recovery, "cu_reo")

    async def rerun(message, by_human):
        return True, "补做完了"

    register_rerunner("computer_use", rerun)
    try:
        out = _closure("reopen_closure", "cu_reo")
    finally:
        verdict.register()
    assert out["outcome"] == "success" and "closure_reopened:retry:recovered" in out["downstream_effects"]


def test_a_closure_on_something_not_in_the_queue_is_a_failure_not_a_success():
    out = _closure("finalize_closure", "cu_never_seen")
    assert out["outcome"] == "failed" and "没收口的结果" in out["error"]


# ── 面板 ──────────────────────────────────────────────────────────────────────


def test_the_panel_offers_the_three_closures_and_shows_a_redo_in_progress():
    from pathlib import Path

    panel = Path(__file__).resolve().parents[1] / "electron" / "renderer" / "panel"
    cards = (panel / "src" / "ui" / "isolated_results.ts").read_text(encoding="utf-8")
    transport = (panel / "src" / "transport.ts").read_text(encoding="utf-8")
    main = (panel / "src" / "main.ts").read_text(encoding="utf-8")
    for label in ("'再试一次'", "'认可'", "'知道了'", "computer_use", "r.retrying"):
        assert label in cards, label
    assert "how: 'dismiss' | 'accept'" in transport and "'retrying'" in transport
    assert "closeIsolated(key, 'accept')" in main and "closeIsolated(key, 'dismiss')" in main
    built = "".join(p.read_text(encoding="utf-8") for p in (panel / "dist" / "assets").glob("index-*.js"))
    assert "认可" in built, "改了面板源码没重新 npm run build(dist/ 是提交进仓库的产物)"
