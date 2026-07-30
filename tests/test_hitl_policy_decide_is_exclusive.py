"""``HITLPolicy.decide`` 的并发独占性测试。

被修的真实缺陷
--------------
``decide()`` 此前把"查到待审批"和"摘走待审批"分成两次持锁:先 ``get``、释放锁、走完
整段裁决(构造 HITLDecision、写 ``req.decision``)、再取锁 ``pop``。中间那段空隙里,
另一个线程可以 ``get`` 到**同一个**非 None 的 ``req``,于是同一条人工审批被裁决两次:

- ``_history`` 落两条记录(审计轨迹里同一次审批出现两遍);
- ``_emit_event`` 发两次事件;
- ``req.decision`` 取决于哪个线程最后写 —— 若两次裁决方向相反(面板点了通过、接口同时
  调了拒绝,或者用户双击了确认按钮),最终生效的是哪个是**不确定的**。

这是"人工确认"这道闸门本身的完整性问题:一条高危操作的审批结果不能取决于线程调度。

修复:``pop`` 与查询在同一次持锁内完成,摘到 ``req`` 即等于独占地领走这条审批;
后到的线程拿到 None,如实返回"没有这条待审批"。

复现说明
--------
这个窗口很窄:CPython 默认 5ms 的 GIL 切换间隔下,一个线程通常能在一个时间片内跑完
``get``→``pop``,所以按默认设置压测**测不出来**(实测 200 轮 0 次)。把切换间隔压到
1e-6 并提到 4 线程竞争后稳定复现(实测修复前 400 轮命中 12 次、修复后 0 次)。
"下压切换间隔" 不是"制造一个不存在的问题",它只是把真实机器上由 IO、GC、更多线程和
更慢的锁竞争自然造成的调度切换,压缩到测试能观测的时间尺度里。
"""

from __future__ import annotations

import logging
import sys
import threading

import pytest

from core.policy.hitl_policy import HITLMode, HITLPolicy

#: 竞争线程数与压测轮数(够稳定复现,又不至于让用例变慢)
_THREADS = 4
_ROUNDS = 200


@pytest.fixture
def force_thread_switching():
    """把 GIL 切换间隔压到极小,让窄窗口在测试里可观测;结束后原样恢复。"""
    original = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(original)


@pytest.fixture
def quiet_logs():
    """裁决竞争会刷出大量 "unknown request_id" 警告(那正是预期行为),压掉噪声。"""
    logger = logging.getLogger("core.policy.hitl_policy")
    original = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(original)


def _pending_request_id(policy: HITLPolicy) -> str:
    policy.evaluate(action="rm -rf /", session_id="s1")
    pending = policy.pending_requests()
    assert pending, "前提:MANUAL 模式下应产生一条待审批"
    return pending[0].request_id


def _decide_concurrently(policy: HITLPolicy, request_id: str, n: int) -> list:
    """让 n 个线程在同一时刻裁决同一条审批,返回各自的返回值。"""
    barrier = threading.Barrier(n)
    results: list = []
    lock = threading.Lock()

    def _worker(approve: bool) -> None:
        barrier.wait()
        outcome = policy.decide(request_id, approve, decided_by=f"t{approve}")
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_worker, args=(bool(i % 2),)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


class TestOnlyOneCallerCanDecideARequest:
    def test_single_winner_under_contention(self, force_thread_switching, quiet_logs):
        """N 个线程同时裁决同一条审批 —— 只能有一个成功,history 只能落一条。

        断言的是**每一轮**都成立,而不是"大多数轮成立":审计轨迹里出现重复审批,一次
        就已经是错的。
        """
        for round_no in range(_ROUNDS):
            policy = HITLPolicy(mode=HITLMode.MANUAL)
            request_id = _pending_request_id(policy)

            results = _decide_concurrently(policy, request_id, _THREADS)

            winners = [r for r in results if r is not None]
            assert len(winners) == 1, f"第 {round_no} 轮:{len(winners)} 个线程都裁决成功了"
            assert len(policy._history) == 1, f"第 {round_no} 轮:history 落了 {len(policy._history)} 条"

    def test_the_winner_is_the_decision_that_takes_effect(self, force_thread_switching, quiet_logs):
        """胜出线程写进 req.decision 的结果,必须与它返回的裁决一致 —— 不能被落败线程
        覆盖成相反方向。"""
        for _ in range(_ROUNDS):
            policy = HITLPolicy(mode=HITLMode.MANUAL)
            request_id = _pending_request_id(policy)

            results = _decide_concurrently(policy, request_id, _THREADS)
            winner = next(r for r in results if r is not None)

            assert policy._history[0] is winner
            assert policy._history[0].approved == winner.approved

    def test_request_is_removed_from_pending(self):
        policy = HITLPolicy(mode=HITLMode.MANUAL)
        request_id = _pending_request_id(policy)

        assert policy.decide(request_id, True) is not None
        assert all(r.request_id != request_id for r in policy.pending_requests())

    def test_deciding_twice_sequentially_returns_none_the_second_time(self, quiet_logs):
        """顺序调用也必须只认第一次 —— 用户双击确认按钮就是这个场景。"""
        policy = HITLPolicy(mode=HITLMode.MANUAL)
        request_id = _pending_request_id(policy)

        assert policy.decide(request_id, True, decided_by="first") is not None
        assert policy.decide(request_id, False, decided_by="second") is None
        assert len(policy._history) == 1
        assert policy._history[0].approved is True, "第二次(相反方向的)裁决不能覆盖第一次"

    def test_unknown_request_id_is_rejected(self, quiet_logs):
        policy = HITLPolicy(mode=HITLMode.MANUAL)
        assert policy.decide("hitl_does_not_exist", True) is None
