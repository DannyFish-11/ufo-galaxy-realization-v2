"""常驻注意力循环的治理：额度、期限、留痕（借自 AFK-surf/Comma 对后台循环的约束）。

这里钉的是 :class:`core.ambient_governance.AmbientGovernor` 自己的行为，时钟可注入，额度窗口的测试
不用真等一小时；期限的测试用几十毫秒的真期限 —— 要的是「到点真的取消了那一次等待」，不是模拟。

**每一条都在问同一件事：失败时说得出来吗。** 超额降级写不写理由、超时留不留痕、留的痕里有没有
把内部细节（异常原文）交出去、一个坏掉的决策脑会不会把留痕刷满而挤掉真正要紧的事。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from core.ambient_governance import (
    COALESCE_S,
    INCIDENT_MAX,
    OUTCOME_BUSY,
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_TIMEOUT,
    RATIONALE_MAX,
    TASK_MAX,
    UTTERANCE_MAX,
    WINDOW_S,
    AmbientGovernor,
    AmbientLimits,
)
from core.ambient_types import AmbientAction, AmbientDecision

WALL0 = 1_700_000_000.0


class Clock:
    """单调钟 + 墙钟共用一个读数：测额度窗口用，不依赖真实时间。"""

    def __init__(self) -> None:
        self.t = 1000.0

    def mono(self) -> float:
        return self.t

    def wall(self) -> float:
        return WALL0 + self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _gov(clock: Clock | None = None, **limits) -> AmbientGovernor:
    clock = clock or Clock()
    return AmbientGovernor(AmbientLimits(**limits), clock=clock.mono, wall=clock.wall)


def _speak(text: str = "你的会议还有五分钟开始") -> AmbientDecision:
    return AmbientDecision(action=AmbientAction.SPEAK, rationale="日历提醒", utterance=text, salient=True)


def _delegate(task: str = "查一下最近的错误日志") -> AmbientDecision:
    return AmbientDecision(action=AmbientAction.DELEGATE, rationale="反复报错", task=task, salient=True)


def _silent() -> AmbientDecision:
    return AmbientDecision(action=AmbientAction.SILENT, rationale="用户在正常操作")


# ── 1. 额度：超额降级，但一定带着理由 ─────────────────────────────────────


def test_an_exhausted_speak_budget_downgrades_to_silent_and_says_why():
    g = _gov(speak_per_hour=2)
    for _ in range(2):
        assert g.gate(_speak()).action == AmbientAction.SPEAK
        g.charge(AmbientAction.SPEAK)

    out = g.gate(_speak("该喝水了"))

    assert out.action == AmbientAction.SILENT and out.salient is False
    assert "已用完（2/2）" in out.rationale and "恢复" in out.rationale
    assert "该喝水了" in out.rationale, "被压下的原本想说什么也要留下，事后才查得出来"


def test_the_budget_is_charged_when_it_acts_not_when_it_is_decided():
    """用户说了「等一下别说话」的那几分钟里，每一拍判出的 SPEAK 都被压下、一句没说 ——
    若在决策时扣额度，hold 一解除就哑一个小时。"""
    g = _gov(speak_per_hour=2)
    for _ in range(50):
        assert g.gate(_speak()).action == AmbientAction.SPEAK  # 只过闸、没有真的开口
    assert g.status()["budget"]["speak"]["used"] == 0


def test_the_window_slides_and_the_budget_comes_back():
    clock = Clock()
    g = _gov(clock, speak_per_hour=1)
    g.charge(AmbientAction.SPEAK)
    assert g.gate(_speak()).action == AmbientAction.SILENT

    clock.advance(WINDOW_S - 1)
    assert g.gate(_speak()).action == AmbientAction.SILENT, "还没滑出窗口"
    clock.advance(2)
    assert g.gate(_speak()).action == AmbientAction.SPEAK
    assert g.status()["budget"]["speak"]["used"] == 0


def test_speak_and_delegate_have_separate_budgets():
    g = _gov(speak_per_hour=1, delegate_per_hour=1)
    g.charge(AmbientAction.SPEAK)
    assert g.gate(_speak()).action == AmbientAction.SILENT
    assert g.gate(_delegate()).action == AmbientAction.DELEGATE, "开口用完不该连累委托"


def test_a_silent_decision_is_never_gated_or_charged():
    g = _gov(speak_per_hour=1, delegate_per_hour=1)
    g.charge(AmbientAction.SPEAK)
    g.charge(AmbientAction.DELEGATE)
    out = g.gate(_silent())
    assert out.action == AmbientAction.SILENT and out.rationale == "用户在正常操作"
    g.charge(AmbientAction.SILENT)  # 不是自发动作：什么都不记
    assert g.status()["budget"]["speak"]["used"] == 1


def test_exhaustion_is_noted_once_per_episode_not_once_per_tick():
    """用满之后每一拍都想开口：留痕只记一条（否则 32 条很快被同一件事刷满），但压下了多少次要数得出来。"""
    clock = Clock()
    g = _gov(clock, speak_per_hour=1)
    g.charge(AmbientAction.SPEAK)
    for _ in range(40):
        g.gate(_speak())
    exhausted = [i for i in g.incidents() if i["kind"] == "budget_exhausted"]
    assert len(exhausted) == 1 and exhausted[0]["action"] == "speak"
    assert g.status()["budget"]["speak"]["suppressed"] == 40

    clock.advance(WINDOW_S + 1)  # 额度回来了
    g.gate(_speak())
    g.charge(AmbientAction.SPEAK)
    g.gate(_speak())  # 再次用满：这是新的一段，再记一条
    clock.advance(COALESCE_S + 1)  # 且不与上一条并成一条
    assert len([i for i in g.incidents() if i["kind"] == "budget_exhausted"]) == 2


def test_resets_at_is_when_the_oldest_charge_leaves_the_window():
    clock = Clock()
    g = _gov(clock, speak_per_hour=2)
    g.charge(AmbientAction.SPEAK)
    clock.advance(100)
    g.charge(AmbientAction.SPEAK)
    clock.advance(10)

    resets_at = g.status()["budget"]["speak"]["resets_at"]
    first_charge_wall = WALL0 + 1000.0
    assert resets_at == pytest.approx(first_charge_wall + WINDOW_S)

    g2 = _gov(speak_per_hour=5)
    g2.charge(AmbientAction.SPEAK)
    assert g2.status()["budget"]["speak"]["resets_at"] is None, "没用满就没有「恢复时刻」"


def test_a_bad_limit_in_the_environment_falls_back_and_says_so(monkeypatch, caplog):
    monkeypatch.setenv("GALAXY_AMBIENT_SPEAK_PER_HOUR", "lots")
    monkeypatch.setenv("GALAXY_AMBIENT_DELEGATE_PER_HOUR", "0")
    with caplog.at_level(logging.WARNING, logger="Galaxy.Ambient"):
        limits = AmbientLimits.from_env()
    assert (limits.speak_per_hour, limits.delegate_per_hour) == (12, 6)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "GALAXY_AMBIENT_SPEAK_PER_HOUR" in said and "GALAXY_AMBIENT_DELEGATE_PER_HOUR" in said


def test_limits_can_be_raised_from_the_environment(monkeypatch):
    monkeypatch.setenv("GALAXY_AMBIENT_SPEAK_PER_HOUR", "100")
    monkeypatch.setenv("GALAXY_AMBIENT_DELEGATE_PER_HOUR", "20")
    limits = AmbientLimits.from_env()
    assert (limits.speak_per_hour, limits.delegate_per_hour) == (100, 20)


# ── 2. 体积：决策文字有上限 ───────────────────────────────────────────────


def test_oversized_decision_text_is_clipped_and_says_so():
    g = _gov()
    big = AmbientDecision(
        action=AmbientAction.DELEGATE,
        rationale="理" * (RATIONALE_MAX * 3),
        utterance="话" * (UTTERANCE_MAX * 3),
        task="活" * (TASK_MAX * 3),
    )
    out = g.gate(big)
    assert len(out.rationale) <= RATIONALE_MAX and len(out.utterance) <= UTTERANCE_MAX and len(out.task) <= TASK_MAX
    assert out.rationale.endswith("已截断）") and out.task.endswith("已截断）")
    assert out.action == AmbientAction.DELEGATE, "只截文字，不改主意"


def test_a_normal_decision_passes_through_untouched():
    g = _gov()
    d = _speak()
    assert g.gate(d) is d


# ── 3. 决策期限 ───────────────────────────────────────────────────────────


class _Hangs:
    async def decide(self, obs):
        await asyncio.sleep(3600)


class _Raises:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def decide(self, obs):
        raise self.exc


async def test_a_decider_that_never_answers_is_cut_off_at_the_deadline():
    g = _gov(decide_deadline_s=0.05)
    out = await asyncio.wait_for(g.decide(_Hangs(), None), 2)
    assert out.action == AmbientAction.SILENT
    assert "没有回应" in out.rationale
    (incident,) = g.incidents()
    assert incident["kind"] == "decide_timeout" and incident["after_s"] > 0, "留痕里要写这一拍等了多久"


async def test_a_decider_exception_is_silent_and_keeps_the_old_wording():
    g = _gov()
    out = await g.decide(_Raises(RuntimeError("boom")), None)
    assert out.action == AmbientAction.SILENT and out.rationale == "决策异常: boom"


async def test_a_timeout_from_inside_the_decider_is_not_mislabelled_as_our_deadline():
    """决策脑自己内部超时了（比如它自己的网络调用），不是我们的期限到了 —— 说错会误导排查。"""
    g = _gov(decide_deadline_s=30)
    out = await g.decide(_Raises(TimeoutError("upstream")), None)
    assert out.action == AmbientAction.SILENT
    (incident,) = g.incidents()
    assert incident["kind"] == "decide_error", incident


async def test_a_good_decision_comes_back_as_is():
    class Ok:
        async def decide(self, obs):
            return _speak("嗨")

    out = await _gov().decide(Ok(), None)
    assert out.action == AmbientAction.SPEAK and out.utterance == "嗨"


# ── 4. 听的期限 ───────────────────────────────────────────────────────────


async def test_a_stuck_transcription_is_cut_off_and_the_tick_carries_on():
    g = _gov(listen_deadline_s=0.05)
    cancelled = asyncio.Event()

    async def stuck():
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    assert await asyncio.wait_for(g.bounded("listen", stuck()), 2) is False
    assert cancelled.is_set(), "到点要真的把那一次等待取消掉，不是放着它继续跑"
    assert [i["kind"] for i in g.incidents()] == ["listen_timeout"]


async def test_bounded_lets_the_callers_own_errors_through():
    g = _gov()

    async def broken():
        raise ValueError("asr down")

    with pytest.raises(ValueError):
        await g.bounded("listen", broken())

    async def inner_timeout():
        raise TimeoutError("not ours")

    with pytest.raises(TimeoutError):
        await g.bounded("listen", inner_timeout())
    assert g.incidents() == [], "不是我们的期限，不记成我们的超时"


async def test_bounded_returns_true_when_it_finishes_in_time():
    async def quick():
        await asyncio.sleep(0)

    assert await _gov().bounded("listen", quick()) is True


# ── 5. 委托期限：到点叫停「这一次委托」，说清楚，不自动重试 ─────────────────


async def test_a_delegate_that_finishes_is_ok_and_counts_against_the_budget():
    g = _gov()

    async def work():
        return True

    assert await g.run_delegate(work(), _delegate()) == OUTCOME_OK
    assert g.status()["budget"]["delegate"]["used"] == 1
    assert g.delegate_in_flight is False and g.incidents() == []


async def test_a_delegate_that_reports_failure_is_recorded_with_its_task():
    g = _gov()

    async def work():
        return False  # _delegate 把异常吞掉后就是返回 False

    assert await g.run_delegate(work(), _delegate("清理磁盘")) == OUTCOME_FAILED
    (incident,) = g.incidents()
    assert incident["kind"] == "delegate_failed" and incident["task"] == "清理磁盘"
    assert "不会自动重试" in incident["explanation"]


async def test_a_delegate_that_raises_is_failed_and_the_flag_is_released():
    g = _gov()

    async def work():
        raise RuntimeError("secret path /home/me/.ssh")

    assert await g.run_delegate(work(), _delegate()) == OUTCOME_FAILED
    assert g.delegate_in_flight is False
    (incident,) = g.incidents()
    assert "RuntimeError" in incident["explanation"]
    assert "secret path" not in str(incident), "异常原文可能带路径 / 内部细节，不能进会交给面板的留痕"


async def test_a_delegate_that_never_returns_is_stopped_at_the_deadline_and_explained():
    g = _gov(delegate_deadline_s=0.05)
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    outcome = await asyncio.wait_for(g.run_delegate(work(), _delegate("整理下载文件夹")), 2)

    assert outcome == OUTCOME_TIMEOUT
    assert cancelled.is_set(), "到点真的把那一次委托取消掉（经 @stoppable 的同一条通道）"
    assert g.delegate_in_flight is False
    (incident,) = g.incidents()
    assert incident["kind"] == "delegate_timeout"
    assert incident["task"] == "整理下载文件夹", "没做完的任务原文留着，让人决定重来还是丢掉"
    assert "不确定" in incident["explanation"] and "不会自动重试" in incident["explanation"]


async def test_a_timeout_raised_inside_the_delegate_is_a_failure_not_our_deadline():
    g = _gov(delegate_deadline_s=30)

    async def work():
        raise TimeoutError("upstream")

    assert await g.run_delegate(work(), _delegate()) == OUTCOME_FAILED
    assert [i["kind"] for i in g.incidents()] == ["delegate_failed"]


async def test_cancelling_the_loop_mid_delegate_still_propagates_and_frees_the_flag():
    """stop() 取消循环任务时，取消要一路传出去 —— 治理层不能把它吞成「超时」。"""
    g = _gov(delegate_deadline_s=30)
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(g.run_delegate(work(), _delegate()))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert g.delegate_in_flight is False and g.incidents() == []


async def test_a_second_delegate_while_one_runs_is_refused_not_run_in_parallel():
    g = _gov(delegate_deadline_s=30)
    release = asyncio.Event()

    async def slow():
        await release.wait()
        return True

    first = asyncio.create_task(g.run_delegate(slow(), _delegate()))
    await asyncio.sleep(0)
    ran = []

    async def second():
        ran.append(1)
        return True

    assert await g.run_delegate(second(), _delegate()) == OUTCOME_BUSY
    assert ran == [], "不并发地烧第二轮完整认知"
    release.set()
    assert await first == OUTCOME_OK
    assert g.status()["budget"]["delegate"]["used"] == 1, "被拒的那次不占额度"


# ── 6. 留痕：有上限、会合并、不外露 ───────────────────────────────────────


def test_a_broken_decider_cannot_flood_the_incident_log():
    """决策脑坏了，每一拍都出同一种错 —— 留痕里只该有一条（计数在涨），
    而不是把真正要紧的「委托超时」挤出那 32 个位置。"""
    g = _gov()
    g._note("delegate_timeout", "delegate", "后台任务 15 分钟没有回应", task="整理下载文件夹")
    for _ in range(500):
        g._note("decide_error", "decide", "决策脑出错（RuntimeError），这一拍放弃")
    kinds = [i["kind"] for i in g.incidents()]
    assert kinds == ["decide_error", "delegate_timeout"], "新的在前，且没有被刷成几百条"
    assert g.incidents()[0]["count"] == 500


def test_the_log_keeps_at_most_32_and_the_oldest_go_first():
    g = _gov()
    for n in range(INCIDENT_MAX + 8):
        # 交替两种，互相不并
        g._note("delegate_failed" if n % 2 else "delegate_timeout", "delegate", f"第 {n} 件", task=f"task-{n}")
    rows = g.incidents()
    assert len(rows) == INCIDENT_MAX
    assert rows[0]["task"] == f"task-{INCIDENT_MAX + 7}" and rows[-1]["task"] == "task-8"


def test_the_same_kind_after_a_long_gap_is_a_new_entry():
    clock = Clock()
    g = _gov(clock)
    g._note("delegate_failed", "delegate", "一")
    clock.advance(COALESCE_S + 1)
    g._note("delegate_failed", "delegate", "二")
    assert [i["count"] for i in g.incidents()] == [1, 1]


def test_incidents_can_be_asked_for_since_a_moment():
    clock = Clock()
    g = _gov(clock)
    g._note("delegate_failed", "delegate", "旧的")
    clock.advance(COALESCE_S * 3)
    g._note("delegate_timeout", "delegate", "新的")
    assert [i["explanation"] for i in g.incidents(since=clock.wall() - 60)] == ["新的"]
    assert [i["explanation"] for i in g.incidents(kinds=["delegate_failed"])] == ["旧的"]


def test_status_has_the_shape_the_panel_and_the_route_rely_on():
    g = _gov(speak_per_hour=3, delegate_per_hour=2)
    s = g.status()
    assert set(s) == {"budget", "deadlines_s", "delegate_in_flight", "incidents"}
    assert set(s["budget"]) == {"speak", "delegate"}
    assert set(s["budget"]["speak"]) == {"used", "limit", "resets_at", "suppressed"}
    assert s["budget"]["speak"]["limit"] == 3 and s["budget"]["delegate"]["limit"] == 2
    assert s["deadlines_s"] == {"decide": 90.0, "listen": 45.0, "delegate": 900.0}
