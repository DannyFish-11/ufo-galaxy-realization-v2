"""等别人的时间不算进这一轮的执行时限。

一轮任务有执行时限(``ExecutionPlan.timeout``,默认 60 秒;对话主循环里每次工具调用另有一个预算),这是给机器的:
模型想、工具跑。可这一轮里有两种等,等的不是这台机器:

* **等人点头**(高风险确认、设备动作要不要做、``ask_human``)—— 默认给人 90 秒(``GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S``);
* **等设备做完**(``devices__invoke`` / ``devices__delegate`` / ``devices__plan`` 的每一步)—— 每件事在那台设备的队列里
  有它自己的期限(委派整段目标默认 180 秒、最多 600 秒)。

时限叠在一起,第 60 秒整轮就被掐掉:手表上那条确认还挂着,人在第 70 秒点了「批准」,已经没有人在等这个答案了,
人听到的却是「任务执行超时」;交给手机的一整段事还在做,这一轮已经报超时(第 18 轮真跑查到)。

这里把两件事分开算:

* 等别人的那一段(:func:`waiting_for_human` / :func:`waiting_on_device` 包住的 await)不消耗这一轮的执行时限 ——
  等的那一方有它自己的期限,到了照常判没批准 / 没做完;
* 其余时间照旧计时,超了照旧掐(:func:`run_within`)。

靠一个 ``ContextVar`` 把这一轮的计时传给它里面起的任务;:func:`run_within` 套 :func:`run_within` 时(一次工具调用里
又排进设备队列)里外两层都扣掉等的时间。不在任何一轮里时两个上下文管理器什么都不做。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Optional, TypeVar

T = TypeVar("T")


@dataclass
class _TurnClock:
    started: float
    #: 外面那一层的计时(:func:`run_within` 套 :func:`run_within`)
    parent: Optional["_TurnClock"] = None
    #: 等别人已经用掉的秒数(等完的那几段)
    away_s: float = 0.0
    #: 正在等的有几处(并行问几台设备、几台设备同时在做时不止一处)
    waiting: int = 0
    #: 这一次「有人在等」开始的时刻
    waiting_since: float = 0.0
    #: 等完了(没有一处在等了):叫醒 :func:`run_within`,剩下的机器时间当场接着算
    resumed: asyncio.Event = field(default_factory=asyncio.Event)

    def spent(self, now: float) -> float:
        """这一轮花在机器上的时间(扣掉等别人的)。"""
        away = self.away_s + (now - self.waiting_since if self.waiting else 0.0)
        return now - self.started - away

    def chain(self) -> list:
        out, c = [], self
        while c is not None:
            out.append(c)
            c = c.parent
        return out


_CLOCK: ContextVar[Optional[_TurnClock]] = ContextVar("galaxy_turn_clock", default=None)


@contextlib.asynccontextmanager
async def _waiting_elsewhere() -> AsyncIterator[None]:
    clock = _CLOCK.get()
    clocks = clock.chain() if clock is not None else []
    now = time.monotonic()
    for c in clocks:
        if c.waiting == 0:
            c.waiting_since = now
        c.waiting += 1
    try:
        yield
    finally:
        done = time.monotonic()
        for c in clocks:
            c.waiting -= 1
            if c.waiting == 0:
                c.away_s += done - c.waiting_since
                c.resumed.set()


def waiting_for_human():
    """包住「等人回答」的那一段 await:这段时间不算进这一轮的执行时限(人有自己的确认超时)。"""
    return _waiting_elsewhere()


def waiting_on_device():
    """包住「等设备把事做完」的那一段 await:这段时间不算进这一轮的执行时限(设备队列里每件事有自己的期限)。"""
    return _waiting_elsewhere()


async def run_within(aw: Awaitable[T], timeout: float) -> T:
    """像 ``asyncio.wait_for(aw, timeout)``,只是等别人的时间不计时。超时抛 ``asyncio.TimeoutError``,并取消 ``aw``。"""
    clock = _TurnClock(started=time.monotonic(), parent=_CLOCK.get())
    token = _CLOCK.set(clock)
    try:
        task: "asyncio.Future[T]" = asyncio.ensure_future(aw)  # 在设了计时之后起:任务里看得到这一轮的计时
    finally:
        _CLOCK.reset(token)
    try:
        while True:
            left = timeout - clock.spent(time.monotonic())
            if left <= 0 and not clock.waiting:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                raise asyncio.TimeoutError()
            if not clock.waiting:
                done, _ = await asyncio.wait({task}, timeout=max(0.05, left))
                if done:
                    return task.result()
                continue
            # 正在等别人时不会超时:等到事做完,或者等完了(剩下的机器时间接着算)
            clock.resumed.clear()
            resumed = asyncio.ensure_future(clock.resumed.wait())
            try:
                done, _ = await asyncio.wait({task, resumed}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                resumed.cancel()
            if task in done:
                return task.result()
    except asyncio.CancelledError:
        task.cancel()
        raise


__all__ = ["run_within", "waiting_for_human", "waiting_on_device"]
