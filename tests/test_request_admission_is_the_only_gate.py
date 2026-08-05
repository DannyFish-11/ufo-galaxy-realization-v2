#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_request_admission_is_the_only_gate.py

钉住请求层准入：**有上限、有配额、抢占真的让对方停下来**，而且只有一道。

背景
====
请求层此前没有任何全局并发上限。三套东西装着，跑的是最弱的那套：

* ``SessionExecutionLane`` —— 只保证同一会话串行。N 个会话 = N 条并发流水线，
  每条都在跑 LLM 与工具执行。**这是唯一在跑的。**
* ``ConcurrencyManager`` —— 有全局上限，但 ``acquire_slot`` /
  ``run_with_concurrency`` / ``run_with_lock`` 全仓零调用方。
  ``CONCURRENCY_GLOBAL_MAX`` 读进去，作用在一个没人用的限流器上。
* ``GlobalArbiter`` —— 优先级 / 配额 / 抢占俱全，从不可达。

抢占那一半尤其要钉
==================
``GlobalArbiter.admit()`` 的抢占**只是记账**：把受害者从 ``_running`` 里删掉就完了，
受害者那个协程照跑不误。单靠仲裁器，抢占的净效果是把并发上限**悄悄突破一个** ——
而且没有任何可观测症状。所以「抢占生效」的判据只能是**被抢占方真的收到了信号**，
不能是「仲裁器说它抢了」。
"""

from __future__ import annotations

import asyncio

import pytest

from core.orchestration.global_arbiter import (
    ArbiterNoSlotError,
    ArbiterQuotaError,
    get_global_arbiter,
    reset_global_arbiter,
)
from core.request_admission import (
    admission_snapshot,
    admit_request,
    origin_is_preemptable,
    priority_for_origin,
)


@pytest.fixture(autouse=True)
def _fresh_arbiter():
    reset_global_arbiter()
    yield
    reset_global_arbiter()


async def _hold(task_id: str, origin: str, registry: dict, ready: asyncio.Event):
    """占住一个槽位直到被取消，并把自己的抢占信号登记出来。"""
    async with admit_request(task_id, origin=origin) as signal:
        registry[task_id] = signal
        ready.set()
        await asyncio.sleep(30)


async def _fill(n: int, origin_of, registry: dict) -> list:
    tasks = []
    for i in range(n):
        ready = asyncio.Event()
        tasks.append(asyncio.create_task(_hold(f"t{i}", origin_of(i), registry, ready)))
        await asyncio.wait_for(ready.wait(), timeout=5)
    return tasks


async def _drain(tasks):
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# 一、来源决定优先级与可抢占性
# ---------------------------------------------------------------------------


def test_user_requests_are_never_preemptable():
    """把用户正在等的请求中途杀掉是不可解释的 —— 他看到的是「它突然不说话了」。"""
    for origin in ("chat", "desktop", "api", "voice", ""):
        assert origin_is_preemptable(origin) is False, f"{origin!r} 被判成可抢占"
        assert priority_for_origin(origin) > priority_for_origin("ambient")


def test_ambient_is_preemptable_and_lower_priority():
    """自发注意力不是用户在等的东西，可以让路 —— 而且在排序上也先让路。"""
    assert origin_is_preemptable("ambient") is True
    assert priority_for_origin("ambient") < priority_for_origin("chat")


# ---------------------------------------------------------------------------
# 二、配额与上限真的挡得住
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_origin_quota_rejects_with_ar_002():
    registry: dict = {}
    quota = get_global_arbiter().stats()["per_origin_quota"]
    tasks = await _fill(quota, lambda i: "desktop", registry)
    try:
        with pytest.raises(ArbiterQuotaError) as excinfo:
            async with admit_request("overflow", origin="desktop"):
                pass
        assert excinfo.value.code == "AR_002"
    finally:
        await _drain(tasks)


@pytest.mark.asyncio
async def test_global_limit_rejects_with_ar_003():
    """占满全局上限之后再来一个**不可抢占**的来源，必须是 AR_003。

    刻意让占位的全是不可抢占来源 —— 否则新请求会走抢占分支被放行，这条就测不到
    上限本身。
    """
    registry: dict = {}
    stats = get_global_arbiter().stats()
    limit, quota = stats["global_limit"], stats["per_origin_quota"]
    tasks = await _fill(limit, lambda i: f"origin{i // quota}", registry)
    assert admission_snapshot()["running_count"] == limit
    try:
        with pytest.raises(ArbiterNoSlotError) as excinfo:
            async with admit_request("overflow", origin="another"):
                pass
        assert excinfo.value.code == "AR_003"
    finally:
        await _drain(tasks)


@pytest.mark.asyncio
async def test_slots_are_released_on_exit():
    """出了作用域必须还回槽位 —— 漏还的症状是「跑着跑着就再也进不来了」。"""
    async with admit_request("t", origin="chat"):
        assert admission_snapshot()["running_count"] == 1
    assert admission_snapshot()["running_count"] == 0


@pytest.mark.asyncio
async def test_slot_is_released_even_when_the_body_raises():
    with pytest.raises(RuntimeError):
        async with admit_request("t", origin="chat"):
            raise RuntimeError("boom")
    assert admission_snapshot()["running_count"] == 0


# ---------------------------------------------------------------------------
# 三、抢占**真的让对方停下来**（不是只在账上划一笔）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preemption_actually_signals_the_victim():
    """判据是被抢占方收到了信号，不是仲裁器声称它抢了。

    仲裁器自己只会把受害者从 ``_running`` 删掉；不补取消通道的话，受害者照跑不误，
    抢占的净效果只是把并发上限悄悄突破一个。
    """
    registry: dict = {}
    stats = get_global_arbiter().stats()
    limit, quota = stats["global_limit"], stats["per_origin_quota"]
    # 前 quota 个是 ambient（可被抢），其余用不可抢占来源占满
    tasks = await _fill(limit, lambda i: "ambient" if i < quota else f"origin{i // quota}", registry)
    try:
        async with admit_request("user-urgent", origin="chat"):
            signalled = [tid for tid, sig in registry.items() if sig.is_set()]
            assert signalled, (
                "用户请求靠抢占进来了，但没有任何在飞任务收到取消信号 —— "
                "抢占只做了记账那一半，被抢的那个还在跑，上限被悄悄突破了一个。"
            )
            victims = [tid for tid in signalled if registry[tid] is not None]
            assert all(int(tid[1:]) < quota for tid in victims), f"被抢的不是 ambient：{victims}"
    finally:
        await _drain(tasks)


@pytest.mark.asyncio
async def test_a_non_preemptable_holder_is_never_signalled():
    """全是不可抢占来源时，新请求应当被拒，而不是去抢一个不该抢的。"""
    registry: dict = {}
    stats = get_global_arbiter().stats()
    limit, quota = stats["global_limit"], stats["per_origin_quota"]
    tasks = await _fill(limit, lambda i: f"origin{i // quota}", registry)
    try:
        with pytest.raises(ArbiterNoSlotError):
            async with admit_request("user-urgent", origin="chat"):
                pass
        assert not [tid for tid, sig in registry.items() if sig.is_set()], "抢了不可抢占的任务"
    finally:
        await _drain(tasks)


# ---------------------------------------------------------------------------
# 四、只有一道闸
# ---------------------------------------------------------------------------


def test_concurrency_manager_is_not_a_second_admission_authority():
    """``ConcurrencyLimiter`` 不许也被接进请求路径。

    两个准入权威 = 同一份资源两个计数器。两个计数器迟早不一致（一边被绕过、或
    release 失败），症状是「明明没满却拒绝」或「明明满了还放行」，而两边各自看都对。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "acquire_slot" not in called, "请求路径上出现了第二个容量权威（ConcurrencyLimiter）"
    assert "run_with_concurrency" not in called


def test_admission_wraps_the_lane_not_the_other_way_round():
    """准入必须在会话车道**外面**。

    反过来的话，一个注定要被拒绝的请求得先排队等到自己那条会话的锁才会被告知拒绝
    —— 而拒绝恰恰是为了不排那个队。
    """
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    )

    def _is(node, name, attr=False):
        for item in getattr(node, "items", []):
            call = item.context_expr
            if not isinstance(call, ast.Call):
                continue
            got = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            if got == name:
                return True
        return False

    admissions = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncWith) and _is(n, "admit_request")]
    assert admissions, "请求路径上找不到 admit_request —— 准入没接"
    admission = admissions[0]
    lanes = [n for n in ast.walk(admission) if isinstance(n, ast.AsyncWith) and _is(n, "acquire")]
    assert lanes, "会话车道不在准入内层 —— 顺序反了，被拒的请求会先排队再被拒"


# ---------------------------------------------------------------------------
# 五、抢占信号有**真实消费方**（不是装了没人看）
# ---------------------------------------------------------------------------


def test_runtime_session_reports_preemption():
    """``RuntimeSession.is_preempted()`` 必须真的反映信号状态。"""
    from core.desktop_presence_runtime import RuntimeSession

    session = RuntimeSession(source="test")
    assert session.is_preempted() is False, "没挂信号时不该报被抢占"

    signal = asyncio.Event()
    session.preemption_signal = signal
    assert session.is_preempted() is False
    signal.set()
    assert session.is_preempted() is True


def test_the_lane_wait_actually_consults_the_preemption_signal():
    """等会话车道之后必须查一次抢占。

    这是本次请求**开工前的最后一道**，也是唯一一个等待时长不可控的点：同会话的上一个
    请求可能还在跑 LLM，而抢占恰恰会发生在这段等待里。不查的话，槽位已经被顶走了却
    照常开工 —— 并发上限被突破一个，且没有任何可观测症状。

    钉的是 ``is_preempted`` 这个**调用**，不是源码文本 —— 解释它的注释里也写着这个词。
    """
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    )
    lane_blocks = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncWith)
        and any(
            isinstance(i.context_expr, ast.Call)
            and isinstance(i.context_expr.func, ast.Attribute)
            and i.context_expr.func.attr == "acquire"
            and getattr(i.context_expr.func.value, "id", "") == "lane_manager"
            for i in n.items
        )
    ]
    assert lane_blocks, "找不到会话车道块"
    called = {
        node.func.attr
        for block in lane_blocks
        for node in ast.walk(block)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "is_preempted" in called, (
        "拿到会话车道之后没有查抢占信号 —— 槽位已被顶走却照常开工，" "并发上限被悄悄突破一个，而且没有任何可观测症状。"
    )
