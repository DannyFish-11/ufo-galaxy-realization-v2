"""等人点头、等设备做完的时间不算进这一轮给机器的时限(``core/human_wait.py``)。

第 18 轮真跑:一轮任务的执行时限默认 60 秒,手表上问「要不要做」给人 90 秒 —— 第 60 秒整轮就被掐掉,人在第
70 秒点「批准」时已经没人在等;交给手机的一整段事(默认 180 秒)也在第 60 秒被报成「任务执行超时」。
等的那一方各有自己的期限(确认超时、设备队列里每件事的期限),这一轮的时限只管机器自己花的时间。
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect

import pytest

from core.human_wait import run_within, waiting_for_human, waiting_on_device


def _run(coro):
    return asyncio.run(coro)


def test_waiting_for_a_person_does_not_use_up_the_turn():
    async def asks_then_answers():
        async with waiting_for_human():
            await asyncio.sleep(0.3)
        return "批准了"

    assert _run(run_within(asks_then_answers(), 0.1)) == "批准了"


def test_waiting_on_a_device_does_not_use_up_the_turn():
    async def device_works():
        async with waiting_on_device():
            await asyncio.sleep(0.3)
        return "做完了"

    assert _run(run_within(device_works(), 0.1)) == "做完了"


def test_the_machines_own_time_is_still_limited():
    async def busy():
        await asyncio.sleep(0.4)

    with pytest.raises(asyncio.TimeoutError):
        _run(run_within(busy(), 0.1))


def test_time_after_the_answer_counts_again():
    async def answered_then_busy():
        async with waiting_for_human():
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.4)

    with pytest.raises(asyncio.TimeoutError):
        _run(run_within(answered_then_busy(), 0.15))


def test_a_wait_inside_a_nested_budget_pauses_both():
    """一次工具调用(外层)里排进设备队列(里层):里层等人,外层也不计时。"""

    async def inner():
        async with waiting_for_human():
            await asyncio.sleep(0.3)
        return "ok"

    async def outer():
        return await run_within(inner(), 5.0)

    assert _run(run_within(outer(), 0.1)) == "ok"


def test_outside_a_turn_the_waits_do_nothing():
    async def plain():
        async with waiting_for_human():
            pass
        async with waiting_on_device():
            pass
        return 1

    assert _run(plain()) == 1


def test_cancelling_the_turn_cancels_the_work():
    seen = []

    async def work():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            seen.append("cancelled")
            raise

    async def main():
        t = asyncio.ensure_future(run_within(work(), 10))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    _run(main())
    assert seen == ["cancelled"]


# ── 设备队列:在交事的那一方的上下文里做,等人的那一段不算进这件事的期限 ─────────────────


_WHO = contextvars.ContextVar("who", default="nobody")


def test_a_queued_device_job_runs_in_the_callers_context_and_may_wait_for_a_person():
    from core.device_queue import reset_queues, run_on_device

    reset_queues()

    async def job():
        async with waiting_for_human():
            await asyncio.sleep(0.3)
        return {"success": True, "who": _WHO.get()}

    async def main():
        # 第一个调用方建了队列(工位在它的上下文里起);第二个调用方的会话号要在自己的那件事里看得到
        _WHO.set("first")
        await run_on_device("d1", lambda: _quick(), timeout=1)
        _WHO.set("second")
        return await run_on_device("d1", job, timeout=0.1)

    async def _quick():
        return {"success": True}

    out = _run(main())
    reset_queues()
    assert out == {"success": True, "who": "second"}, out


def test_a_queued_device_job_that_overruns_is_reported():
    from core.device_queue import reset_queues, run_on_device

    reset_queues()

    async def stuck():
        await asyncio.sleep(1)
        return {"success": True}

    out = _run(run_on_device("d2", stuck, timeout=0.1))
    reset_queues()
    assert out["success"] is False and "没做完" in out["error"], out


# ── 用到它的地方 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module, needle",
    [
        ("core.agent.execution_planner", "run_within(self._dispatch("),
        ("core.openclawd", "run_within(self._dispatch_tool_call("),
        ("core.interaction.pending_decision_registry", "async with waiting_for_human():"),
        ("core.approval_gate", "async with waiting_for_human():"),
        ("core.device_boundaries", "async with waiting_on_device():"),
    ],
)
def test_the_turn_budgets_and_the_waits_use_it(module, needle):
    import importlib

    src = inspect.getsource(importlib.import_module(module))
    assert needle in src, f"{module} 该用 core/human_wait.py:{needle}"
