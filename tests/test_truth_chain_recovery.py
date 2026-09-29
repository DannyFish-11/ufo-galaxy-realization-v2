"""真相链没收口：后台补跑一次，仍不行就隔离（所有者决定，2026-09-28）。

这组测试钉住四件事：
1. 补跑**只重跑失败的步骤**，成功过的步骤不做第二遍；
2. 补跑收口 → 从账本撤掉；不收口 → 进隔离队列、落盘、重启可读，接口不外露原始消息；
3. 排期不阻塞：同步调用方走守护线程，事件循环里走 ``call_later``，到点确实会跑；
4. 处理器回退路径上 1–3 步失败时，等待方照样马上拿到结果（以前异常会把它挡住直到超时）。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.task_result_canonical_truth_chain as ttc
from core.truth_chain_recovery import STATE_DISMISSED, STATE_ISOLATED, TruthChainRecovery

_MSG: Dict[str, Any] = {"type": "task_result", "task_id": "t-rec", "device_id": "dev-rec", "status": "completed"}


def _boom(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("transient")


class _Counter:
    def __init__(self, result: Any = None) -> None:
        self.calls = 0
        self.result = result

    def __call__(self, *_a: Any, **_k: Any) -> Any:
        self.calls += 1
        return self.result


@pytest.fixture
def recovery(tmp_path: Path) -> TruthChainRecovery:
    r = TruthChainRecovery(store_path=tmp_path / "isolated_results.json", delay_s=3600)
    yield r
    r.reset()


@pytest.fixture(autouse=True)
def _clean_ledger():
    ttc.get_incomplete_result_ledger().clear()
    yield
    ttc.get_incomplete_result_ledger().clear()


def _incomplete_step4_outcome() -> ttc.TruthChainOutcome:
    """1–3 步成功、第 4 步抛异常 —— 软失败，不抛，只进账本。"""
    ingress = MagicMock()
    ingress.notify.side_effect = RuntimeError("transient")
    with (
        patch.object(ttc, "_get_canonical_completion_ingress", lambda: ingress),
        patch("core.truth_chain_recovery.get_truth_chain_recovery", side_effect=AssertionError("not here")),
    ):
        return ttc.run_task_result_truth_chain(dict(_MSG))


# --------------------------------------------------------------------------- 补跑只跑失败的步骤


def test_rerun_only_touches_failed_steps() -> None:
    outcome = ttc.TruthChainOutcome(
        task_id="t-only",
        result_status="completed",
        truth_ingress_status=ttc.StepStatus.COMPLETED,
        reconcile_status=ttc.StepStatus.COMPLETED,
        authority_update_status=ttc.StepStatus.COMPLETED,
        completion_linkage_status=ttc.StepStatus.FAILED_EXCEPTION,
    )
    ingest, reconcile = _Counter(), _Counter()
    ingress = MagicMock()
    ingress.notify.return_value = True
    with (
        patch.object(ttc, "_ingest_participant_truth", ingest),
        patch.object(ttc, "_reconcile_inbound_message", reconcile),
        patch.object(ttc, "_get_canonical_completion_ingress", lambda: ingress),
    ):
        retried = ttc.rerun_failed_steps(outcome, dict(_MSG, task_id="t-only"))
    assert ingest.calls == 0 and reconcile.calls == 0, "成功过的步骤不能再跑一遍"
    assert ingress.notify.call_count == 1
    assert retried.is_truth_chain_complete
    assert outcome.completion_linkage_status == ttc.StepStatus.FAILED_EXCEPTION, "原 outcome 不动"


def test_failed_steps_reads_typed_status_only() -> None:
    o = ttc.TruthChainOutcome(
        truth_ingress_status=ttc.StepStatus.SKIPPED_MODULE_UNAVAILABLE,
        reconcile_status=ttc.StepStatus.COMPLETED_NO_MATCH,
        authority_update_status=ttc.StepStatus.SKIPPED_NO_TASK_ID,
        completion_linkage_status=ttc.StepStatus.FAILED_EXCEPTION,
    )
    assert ttc.failed_steps(o) == ["truth_ingress", "completion_linkage"]


# --------------------------------------------------------------------------- 收口 / 隔离


def test_recovered_retry_leaves_ledger_and_queue(recovery: TruthChainRecovery) -> None:
    outcome = _incomplete_step4_outcome()
    assert ttc.get_incomplete_result_ledger().get("t-rec") is not None
    key = recovery.schedule(outcome, dict(_MSG))
    assert recovery.summary()["pending_retry"] == 1

    ingress = MagicMock()
    ingress.notify.return_value = True
    with patch.object(ttc, "_get_canonical_completion_ingress", lambda: ingress):
        settled = recovery.run_pending(key)

    assert settled["state"] == "recovered"
    assert settled["retried_steps"] == ["completion_linkage"]
    assert ttc.get_incomplete_result_ledger().get("t-rec") is None, "补齐了就不该再算没收口"
    assert recovery.isolated() == []
    assert recovery.recent_recovered()[0]["task_id"] == "t-rec"


def test_still_failing_goes_to_isolation_and_survives_restart(recovery: TruthChainRecovery, tmp_path: Path) -> None:
    with (
        patch.object(ttc, "_ingest_participant_truth", _boom),
        patch("core.truth_chain_recovery.get_truth_chain_recovery", lambda: recovery),
    ):
        with pytest.raises(ttc.TruthChainStepError):
            ttc.run_task_result_truth_chain(dict(_MSG))
        assert recovery.summary()["pending_retry"] == 1, "抛错之前就该排上补跑"
        settled = recovery.run_pending("t-rec")

    assert settled["state"] == STATE_ISOLATED
    assert settled["failed_steps"] == ["truth_ingress"]
    assert settled["raised_steps"] == ["truth_ingress"] and settled["retry_raised"] is False
    assert "transient" not in json.dumps(settled, ensure_ascii=False), "异常原文不进记录（会经接口外露），只进日志"
    assert settled["attempts"] == 2

    rows = recovery.isolated()
    assert [r["task_id"] for r in rows] == ["t-rec"]
    assert rows[0]["message_retained"] is True
    assert "message" not in rows[0], "接口不外露原始结果消息"

    on_disk = json.loads((tmp_path / "isolated_results.json").read_text(encoding="utf-8"))
    assert on_disk["entries"][0]["message"]["task_id"] == "t-rec", "补跑要用的原始消息只留在本机存储里"

    reborn = TruthChainRecovery(store_path=tmp_path / "isolated_results.json")
    assert [r["task_id"] for r in reborn.isolated()] == ["t-rec"], "重启后隔离项还在"


def test_manual_retry_and_dismiss(recovery: TruthChainRecovery) -> None:
    with patch.object(ttc, "_ingest_participant_truth", _boom):
        outcome = ttc.TruthChainOutcome(task_id="t-rec", result_status="completed")
        outcome.truth_ingress_status = ttc.StepStatus.FAILED_EXCEPTION
        outcome.reconcile_status = ttc.StepStatus.COMPLETED
        outcome.authority_update_status = ttc.StepStatus.COMPLETED
        outcome.completion_linkage_status = ttc.StepStatus.COMPLETED
        recovery.schedule(outcome, dict(_MSG))
        recovery.run_pending("t-rec")
        still = recovery.retry_isolated("t-rec")
    assert still["state"] == STATE_ISOLATED and still["attempts"] == 3

    ok = _Counter(result=MagicMock(was_reconciled=True))
    with patch.object(ttc, "_ingest_participant_truth", ok):
        fixed = recovery.retry_isolated("t-rec")
    assert fixed["state"] == "recovered" and ok.calls == 1
    assert recovery.isolated(include_dismissed=True) == []
    assert recovery.retry_isolated("t-rec") is None

    recovery.schedule(outcome, dict(_MSG, task_id="t-2"))
    outcome2 = ttc.TruthChainOutcome(task_id="t-2", truth_ingress_status=ttc.StepStatus.FAILED_EXCEPTION)
    recovery.schedule(outcome2, dict(_MSG, task_id="t-2"))
    with patch.object(ttc, "_ingest_participant_truth", _boom):
        recovery.run_pending("t-2")
    assert recovery.dismiss("t-2")["state"] == STATE_DISMISSED
    assert recovery.isolated() == []
    assert [r["task_id"] for r in recovery.isolated(include_dismissed=True)] == ["t-2"]
    assert recovery.dismiss("nope") is None


def test_oversized_message_is_isolated_but_not_retainable(recovery: TruthChainRecovery) -> None:
    outcome = ttc.TruthChainOutcome(task_id="t-big", truth_ingress_status=ttc.StepStatus.FAILED_EXCEPTION)
    big = dict(_MSG, task_id="t-big", result={"blob": "x" * (70 * 1024)})
    recovery.schedule(outcome, big)
    with patch.object(ttc, "_ingest_participant_truth", _boom):
        recovery.run_pending("t-big")
    assert recovery.get("t-big")["message_retained"] is False
    assert recovery.retry_isolated("t-big")["retry_refused"] == "message_not_retained"


# --------------------------------------------------------------------------- 排期不阻塞、到点会跑


def _wait_until(pred: Any, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_sync_caller_gets_a_daemon_timer_that_fires(tmp_path: Path) -> None:
    r = TruthChainRecovery(store_path=tmp_path / "i.json", delay_s=0.05)
    try:
        outcome = ttc.TruthChainOutcome(task_id="t-timer", truth_ingress_status=ttc.StepStatus.FAILED_EXCEPTION)
        with patch.object(ttc, "_ingest_participant_truth", _boom):
            r.schedule(outcome, dict(_MSG, task_id="t-timer"))
            assert _wait_until(lambda: r.get("t-timer") is not None)
        assert r.summary()["pending_retry"] == 0
    finally:
        r.reset()


def test_event_loop_caller_is_retried_on_the_loop(tmp_path: Path) -> None:
    r = TruthChainRecovery(store_path=tmp_path / "i.json", delay_s=0.01)
    ran_on: List[Any] = []

    def _record_loop(*_a: Any, **_k: Any) -> Any:
        ran_on.append(asyncio.get_running_loop())
        raise RuntimeError("still down")

    async def _main() -> Any:
        outcome = ttc.TruthChainOutcome(task_id="t-loop", truth_ingress_status=ttc.StepStatus.FAILED_EXCEPTION)
        r.schedule(outcome, dict(_MSG, task_id="t-loop"))
        await asyncio.sleep(0.1)
        return asyncio.get_running_loop()

    try:
        with patch.object(ttc, "_ingest_participant_truth", _record_loop):
            loop = asyncio.run(_main())
        assert ran_on == [loop], "补跑应在原事件循环线程上执行"
        assert r.get("t-loop")["state"] == STATE_ISOLATED
    finally:
        r.reset()


def test_same_task_is_not_double_scheduled(recovery: TruthChainRecovery) -> None:
    o = ttc.TruthChainOutcome(task_id="t-dup", truth_ingress_status=ttc.StepStatus.FAILED_EXCEPTION)
    recovery.schedule(o, dict(_MSG, task_id="t-dup"))
    recovery.schedule(o, dict(_MSG, task_id="t-dup"))
    assert recovery.summary()["pending_retry"] == 1
    assert len(recovery._timers) == 1


def test_reset_cancels_pending_timers(tmp_path: Path) -> None:
    r = TruthChainRecovery(store_path=tmp_path / "i.json", delay_s=0.05)
    r.schedule(ttc.TruthChainOutcome(task_id="t-x"), dict(_MSG, task_id="t-x"))
    r.reset()
    time.sleep(0.15)
    assert r.summary()["pending_retry"] == 0 and r.isolated() == []


# --------------------------------------------------------------------------- 处理器：回答不被挡住


def test_task_result_fallback_path_still_answers_when_truth_chain_raises(recovery: TruthChainRecovery) -> None:
    import galaxy_gateway.android.handlers.task_lifecycle as tl

    loop = asyncio.new_event_loop()
    try:
        bridge = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        future = loop.create_future()
        bridge._pending_responses = {"t-ans": future}
        msg = {"type": "task_result", "task_id": "t-ans", "device_id": "dev-ans", "status": "completed"}
        with (
            patch.object(ttc, "_ingest_participant_truth", _boom),
            patch("core.truth_chain_recovery.get_truth_chain_recovery", lambda: recovery),
            patch.object(tl, "store_task_result", None),
            patch.object(tl, "_evaluate_continuity_legality", None),
            patch("core.unified_result_ingress.ingest_result_async", side_effect=ImportError("force legacy path")),
            patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
            patch("core.durable_result_idempotency.record_result_idempotency", return_value=None),
        ):
            loop.run_until_complete(tl.handle_task_result(bridge, None, msg))
        assert future.done() and future.result()["task_id"] == "t-ans", "用户该马上拿到回答"
        assert recovery.summary()["pending_retry"] == 1, "没收口的那部分已排上后台补跑"
    finally:
        recovery.reset()
        loop.close()


# --------------------------------------------------------------------------- 接口


def test_isolated_results_api(recovery: TruthChainRecovery) -> None:
    from core.routes import result_recovery

    o = ttc.TruthChainOutcome(task_id="t-api", truth_ingress_status=ttc.StepStatus.FAILED_EXCEPTION)
    recovery.schedule(o, dict(_MSG, task_id="t-api"))
    with patch.object(ttc, "_ingest_participant_truth", _boom):
        recovery.run_pending("t-api")

    app = FastAPI()
    app.include_router(result_recovery.create_router())
    with patch("core.truth_chain_recovery.get_truth_chain_recovery", lambda: recovery):
        client = TestClient(app)
        body = client.get("/api/v1/results/isolated").json()
        assert body["summary"]["isolated"] == 1
        assert body["items"][0]["task_id"] == "t-api" and "message" not in body["items"][0]
        assert client.get("/api/v1/results/isolated/t-api").json()["failed_steps"] == ["truth_ingress"]
        assert client.get("/api/v1/results/isolated/none").status_code == 404
        with patch.object(ttc, "_ingest_participant_truth", _Counter(result=MagicMock(was_reconciled=True))):
            assert client.post("/api/v1/results/isolated/t-api/retry").json()["state"] == "recovered"
        assert client.post("/api/v1/results/isolated/t-api/dismiss").status_code == 404


def test_isolated_results_route_is_mounted_on_the_real_api(recovery: TruthChainRecovery) -> None:
    from core.routes import observability

    app = FastAPI()
    app.include_router(observability.create_router())
    with patch("core.truth_chain_recovery.get_truth_chain_recovery", lambda: recovery):
        client = TestClient(app)
        assert client.get("/api/v1/results/isolated").json()["items"] == []
        assert client.post("/api/v1/results/isolated/none/retry").status_code == 404
