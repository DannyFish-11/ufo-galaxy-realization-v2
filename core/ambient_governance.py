"""core/ambient_governance.py — 常驻注意力循环的治理：额度、期限、留痕、唤醒规则
=========================================================================

借自 AFK-surf/Comma 对「后台循环」的约束。Comma 的循环是智能体自己写的、常驻的、没人盯着的程序，
它给这类东西立了几条规矩 —— 同一个处境，我们的 :mod:`core.ambient_attention_loop` 也是：它在用户没开口
的时候自己看、自己听、自己判断要不要开口或派活，而且**默认开**。

========================  ====================================  ==========================================
Comma 的规矩               这里对应的东西                         此前的实况
========================  ====================================  ==========================================
活跃循环有配额             每小时自发开口 / 自发委托各有额度       只有「冷却 20 秒」：一拍一拍卡间隔，不管总量。
                                                               屏幕在放视频时，一小时能派出上百轮完整认知
事件有上限、有体积上限     失败留痕最多 32 条；决策文字有字数上限   决策文字是模型自由输出，没有上限
超过确认期限就判失败        决策 / 转写 / 委托各有期限，到点叫停      **没有期限**：一次委托卡住，整条循环就此无声
并说清楚、不静默重试        并如实写下原因；不自动重试              地死掉 —— ``running`` 仍是 True，什么迹象都没有
只有显式 notify 才唤醒      只有 SPEAK 会出声 / 进对话；其余一概    （本来就是这个设计，这里把它写成测试钉住）
会话                      不出声、不进对话、不动三态
========================  ====================================  ==========================================

**不重造已有的东西。** 「同时跑几个、按来源配额、抢占」是 :mod:`core.request_admission` /
``GlobalArbiter`` 的事（并发轴），自发委托走 ``handle_request`` 正门时已经受它管。本模块管的是它
**管不到**的两条轴：**时间轴上的总量**（每小时多少次）与**每一步的期限**。两边不共用计数器，
也就不会出现「一边说满了一边说没满」。

额度不是静默的闸
----------------
超额时 SPEAK / DELEGATE 降级为 SILENT，但降级一定带着理由写进决策（面板「它在想什么」那一行、工作记忆、
:meth:`AmbientGovernor.status`）：「本小时自发开口已用完（12/12），到 14:32 才恢复」。一个悄悄把
陪伴型的自发在场闷成哑巴的闸，比没有闸更糟 —— 所以额度有配置键，且降级写得出来。

期限靠叫停，不靠放弃
--------------------
委托到期时取消的是**这一次委托本身**（经 ``@stoppable`` 的同一条取消通道），不是整条循环；
已经发出去的那一步是否落地不知道 —— 记账（:mod:`core.action_journal`）会把它标成「不确定」，
面板打开时会提示。这里**不**自动重试：说「没做完」，不说「失败了再来一遍」，更不说「成功」。

额度键在面板里改了**当场生效**（每次取用都重新读环境）；计数在内存里，进程重启就清零 ——
它防的是「一直开着时的失控」，不是崩溃循环。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional

from core.ambient_types import AmbientAction, AmbientDecision

logger = logging.getLogger("Galaxy.Ambient")

# ── 额度（每滚动一小时）──
DEFAULT_SPEAK_PER_HOUR = 12  # 克制是美德：平均五分钟一句已经算健谈
DEFAULT_DELEGATE_PER_HOUR = 6  # 每一次委托都是一轮完整认知，是最贵的一种自发动作
WINDOW_S = 3600.0

# ── 期限（秒）──
DECIDE_DEADLINE_S = 90.0  # 一拍决策：一次模型调用（含一次纯文本重试）
LISTEN_DEADLINE_S = 45.0  # 听：线程池里的转写；超时只是这一拍不带声音内容
DELEGATE_DEADLINE_S = 900.0  # 委托：15 分钟没回应就判没做完（与 Comma 的确认期同数）

# ── 留痕与体积 ──
INCIDENT_MAX = 32  # 最多留 32 条未了结的事（Comma：32 条待确认事件）
COALESCE_S = 600.0  # 同一类事连续发生，十分钟内并成一条（计数 +1），不让一个坏掉的决策脑把留痕刷满
RATIONALE_MAX = 1000  # 决策文字的字数上限 —— 默认决策脑 max_tokens=200 本来就够不到，
UTTERANCE_MAX = 1000  # 这是给自定义决策脑 / 解析失控兜的底
TASK_MAX = 4000
_TRUNCATED = "…（过长，已截断）"

_KIND_OF = {AmbientAction.SPEAK: "speak", AmbientAction.DELEGATE: "delegate"}
_LABEL = {"speak": "开口", "delegate": "委托"}

OUTCOME_OK = "ok"
OUTCOME_FAILED = "failed"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_BUSY = "busy"


#: 说过的坏值。额度是**每次取用都重新读**的（见 AmbientGovernor.limits），同一个坏值不能每拍刷一条。
_WARNED: set = set()


def _int_env(name: str, default: int) -> int:
    """非法 / 非正的值回到默认，并**说一句**（同一个坏值只说一次）—— 配置写错了不许静默当成没写。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(float(raw.strip()))
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        if (name, raw) not in _WARNED:
            _WARNED.add((name, raw))
            logger.warning("%s=%r 不是正整数，按默认值 %d 处理（想放开就填一个大数）", name, raw, default)
        return default
    return value


@dataclass(frozen=True)
class AmbientLimits:
    speak_per_hour: int = DEFAULT_SPEAK_PER_HOUR
    delegate_per_hour: int = DEFAULT_DELEGATE_PER_HOUR
    decide_deadline_s: float = DECIDE_DEADLINE_S
    listen_deadline_s: float = LISTEN_DEADLINE_S
    delegate_deadline_s: float = DELEGATE_DEADLINE_S

    @classmethod
    def from_env(cls) -> "AmbientLimits":
        return cls(
            speak_per_hour=_int_env("GALAXY_AMBIENT_SPEAK_PER_HOUR", DEFAULT_SPEAK_PER_HOUR),
            delegate_per_hour=_int_env("GALAXY_AMBIENT_DELEGATE_PER_HOUR", DEFAULT_DELEGATE_PER_HOUR),
        )

    def limit_of(self, kind: str) -> int:
        return self.speak_per_hour if kind == "speak" else self.delegate_per_hour


@dataclass
class Incident:
    """一件没有顺利了结的事。只存类型与固定模板的说明 —— 不存异常原文（那可能带路径 / 内部细节，
    而这份东西会经接口交给面板）。``task`` 是委托没做完时的任务原文：留着，让人决定重来还是丢掉。"""

    t: float  # 第一次发生（墙钟）
    kind: str  # budget_exhausted | decide_timeout | decide_error | listen_timeout | delegate_timeout | delegate_failed
    action: str  # speak | delegate | decide | listen
    explanation: str
    task: str = ""
    after_s: float = 0.0
    count: int = 1
    t_last: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "t_last": round(self.t_last or self.t, 3),
            "kind": self.kind,
            "action": self.action,
            "explanation": self.explanation,
            "task": self.task,
            "after_s": round(self.after_s, 1),
            "count": self.count,
        }


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(_TRUNCATED))] + _TRUNCATED


def _hhmm(wall_ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(wall_ts))


class AmbientGovernor:
    """一条注意力循环的治理：额度、期限、留痕。时钟可注入，便于确定性地测。"""

    def __init__(
        self,
        limits: Optional[AmbientLimits] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._pinned_limits = limits  # 传了就固定（测试 / 嵌入方）；没传就跟着环境走
        self._clock = clock  # 额度窗口用单调时钟：墙钟被校时 / 夏令时拨动不该放走或多扣额度
        self._wall = wall  # 只用来给人看「到几点恢复」
        self._stamps: Dict[str, Deque[float]] = {"speak": deque(), "delegate": deque()}
        self._suppressed: Dict[str, int] = {"speak": 0, "delegate": 0}
        self._exhausted_noted: Dict[str, bool] = {"speak": False, "delegate": False}
        self._incidents: Deque[Incident] = deque(maxlen=INCIDENT_MAX)
        self.delegate_in_flight = False

    @property
    def limits(self) -> AmbientLimits:
        """额度**每次取用都重新读环境**：在面板「全部设置」里改了就当场生效，不必重启 ——
        设置页保存之后「该生效的必须当场生效」是本仓对设置的硬要求（见
        tests/test_saving_a_setting_really_takes_effect.py）。读两个环境变量的开销可以忽略。"""
        return self._pinned_limits if self._pinned_limits is not None else AmbientLimits.from_env()

    # ── 额度 ──
    def _used(self, kind: str) -> int:
        stamps = self._stamps[kind]
        now = self._clock()
        while stamps and now - stamps[0] >= WINDOW_S:
            stamps.popleft()
        return len(stamps)

    def _resets_at_wall(self, kind: str) -> Optional[float]:
        """额度用满时，最早那一笔滑出窗口的墙钟时刻；没满返回 None。"""
        if self._used(kind) < self.limits.limit_of(kind):
            return None
        oldest = self._stamps[kind][0]
        return self._wall() + max(0.0, oldest + WINDOW_S - self._clock())

    def charge(self, action: AmbientAction) -> None:
        """**动手的那一刻**记一笔（不是决策的那一刻）。

        放在决策时记的话：用户说了「等一下别说话」的那几分钟里，每一拍判出的 SPEAK 都被 hold 闸压下、
        一句没说，额度却被一笔笔扣光 —— hold 一解除就哑一个小时。所以只记真正发生了的。
        """
        kind = _KIND_OF.get(action)
        if kind is not None:
            self._stamps[kind].append(self._clock())

    def gate(self, decision: AmbientDecision) -> AmbientDecision:
        """过一遍体积上限与额度。超额的 SPEAK / DELEGATE 降级为 SILENT，**带着理由**。"""
        decision = self._clip_decision(decision)
        kind = _KIND_OF.get(decision.action)
        if kind is None:
            return decision
        limit = self.limits.limit_of(kind)
        used = self._used(kind)
        if used < limit:
            self._exhausted_noted[kind] = False  # 额度回来了：下一次用满再记一条
            return decision

        self._suppressed[kind] += 1
        resets = self._resets_at_wall(kind)
        until = f"，到 {_hhmm(resets)} 才恢复" if resets is not None else ""
        why = f"本小时自发{_LABEL[kind]}已用完（{used}/{limit}）{until}"
        if not self._exhausted_noted[kind]:
            self._exhausted_noted[kind] = True
            self._note("budget_exhausted", kind, why)
        wanted = (decision.utterance if kind == "speak" else decision.task) or decision.rationale
        return AmbientDecision(
            action=AmbientAction.SILENT,
            # 原本想做什么也写下：事后能看出被压下的是什么，而不是凭空少了一拍。
            rationale=_clip(f"{why}；原拟：{wanted[:60]}", RATIONALE_MAX),
            salient=False,
        )

    @staticmethod
    def _clip_decision(decision: AmbientDecision) -> AmbientDecision:
        rationale = _clip(decision.rationale, RATIONALE_MAX)
        utterance = _clip(decision.utterance, UTTERANCE_MAX)
        task = _clip(decision.task, TASK_MAX)
        if (rationale, utterance, task) == (decision.rationale, decision.utterance, decision.task):
            return decision
        return dataclasses.replace(decision, rationale=rationale, utterance=utterance, task=task)

    # ── 期限 ──
    async def decide(self, decider: Any, obs: Any) -> AmbientDecision:
        """一拍决策，带期限。超时 / 出错都落成 SILENT 并写明原因 —— 决策不可致命。"""
        deadline = self.limits.decide_deadline_s
        try:
            async with asyncio.timeout(deadline) as scope:
                return await decider.decide(obs)
        except TimeoutError:
            if not scope.expired():  # 决策脑自己内部抛出的超时，不是我们的期限
                return self._decide_failed(TimeoutError("decider"))
            why = f"决策脑 {deadline:.0f} 秒没有回应，这一拍放弃，下一拍重新看"
            self._note("decide_timeout", "decide", why, after_s=deadline)
            return AmbientDecision(action=AmbientAction.SILENT, rationale=why)
        except Exception as exc:  # noqa: BLE001 — 决策不可致命
            return self._decide_failed(exc)

    def _decide_failed(self, exc: BaseException) -> AmbientDecision:
        logger.debug("Ambient decide 异常,视为 SILENT: %s", exc)
        self._note("decide_error", "decide", f"决策脑出错（{type(exc).__name__}），这一拍放弃", level=logging.DEBUG)
        return AmbientDecision(action=AmbientAction.SILENT, rationale=f"决策异常: {exc}")

    async def bounded(self, stage: str, aw: Awaitable[Any]) -> bool:
        """给一步不产出值的等待（听）上期限。``True`` = 在期限内跑完；``False`` = 超时，已取消并留痕。

        异常照常往外抛 —— 调用方自己的降级逻辑不被这里吞掉。
        """
        deadline = self.limits.listen_deadline_s
        try:
            async with asyncio.timeout(deadline) as scope:
                await aw
            return True
        except TimeoutError:
            if not scope.expired():
                raise
            self._note(
                f"{stage}_timeout", stage, f"转写 {deadline:.0f} 秒没有回应，这一拍不带声音内容", after_s=deadline
            )
            return False

    async def run_delegate(self, aw: Awaitable[Any], decision: AmbientDecision) -> str:
        """跑一次自发委托，带确认期限。返回 ``ok`` / ``failed`` / ``timeout`` / ``busy``。

        ``aw`` 的约定：成功返回非 ``False``，失败（已被它自己吞掉的异常）返回 ``False`` —— 循环的
        ``_delegate`` 一向把异常吞掉记日志，不返回这一位的话，外面分不出「做完了」和「根本没做成」。
        """
        if self.delegate_in_flight:  # 循环是串行的；有人并发调用时拒绝，不并发地烧第二轮认知
            if asyncio.iscoroutine(aw):
                aw.close()
            return OUTCOME_BUSY
        self.delegate_in_flight = True
        self.charge(AmbientAction.DELEGATE)  # 一旦开工就算一次，做没做成都一样占了资源
        deadline = self.limits.delegate_deadline_s
        try:
            async with asyncio.timeout(deadline) as scope:
                result = await aw
        except TimeoutError:
            if not scope.expired():
                return self._delegate_failed(decision, TimeoutError("delegate"))
            minutes = deadline / 60.0
            self._note(
                "delegate_timeout",
                "delegate",
                f"后台任务 {minutes:.0f} 分钟没有回应，已叫停；已经发出的操作是否落地不确定"
                "（见「结果不明的操作」）；不会自动重试",
                task=decision.task,
                after_s=deadline,
            )
            return OUTCOME_TIMEOUT
        except Exception as exc:  # noqa: BLE001 — 委托失败不影响循环
            return self._delegate_failed(decision, exc)
        finally:
            self.delegate_in_flight = False
        if result is False:
            return self._delegate_failed(decision, None)
        return OUTCOME_OK

    def _delegate_failed(self, decision: AmbientDecision, exc: Optional[BaseException]) -> str:
        kind = f"（{type(exc).__name__}）" if exc is not None else ""
        self._note("delegate_failed", "delegate", f"后台任务没跑完{kind}；不会自动重试", task=decision.task)
        return OUTCOME_FAILED

    # ── 留痕 ──
    def _note(
        self,
        kind: str,
        action: str,
        explanation: str,
        *,
        task: str = "",
        after_s: float = 0.0,
        level: int = logging.WARNING,
    ) -> Incident:
        now = self._wall()
        last = self._incidents[-1] if self._incidents else None
        if last is not None and last.kind == kind and last.action == action and now - last.t_last < COALESCE_S:
            last.count += 1
            last.t_last = now
            last.explanation = explanation
            if task:
                last.task = task
            logger.debug("Ambient 留痕并入上一条（第 %d 次）: %s", last.count, explanation)
            return last
        incident = Incident(
            t=now, kind=kind, action=action, explanation=explanation, task=task, after_s=after_s, t_last=now
        )
        self._incidents.append(incident)
        logger.log(level, "Ambient 治理: %s", explanation)
        return incident

    def incidents(self, *, since: float = 0.0, kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """最近的留痕，新的在前。``since`` 之后**还在发生**的也算（按最近一次发生的时刻）。"""
        rows = [
            i.to_dict()
            for i in reversed(self._incidents)
            if (i.t_last or i.t) > since and (kinds is None or i.kind in kinds)
        ]
        return rows

    def summary(self) -> str:
        """一句话讲清此刻的额度（启动日志用）：人看日志就知道它被允许做多少，不必去翻配置。"""
        lim = self.limits
        return f"每小时自发开口 ≤{lim.speak_per_hour}、委托 ≤{lim.delegate_per_hour}"

    def status(self) -> Dict[str, Any]:
        budget: Dict[str, Any] = {}
        for kind in ("speak", "delegate"):
            resets = self._resets_at_wall(kind)
            budget[kind] = {
                "used": self._used(kind),
                "limit": self.limits.limit_of(kind),
                "resets_at": round(resets, 3) if resets is not None else None,
                "suppressed": self._suppressed[kind],
            }
        return {
            "budget": budget,
            "deadlines_s": {
                "decide": self.limits.decide_deadline_s,
                "listen": self.limits.listen_deadline_s,
                "delegate": self.limits.delegate_deadline_s,
            },
            "delegate_in_flight": self.delegate_in_flight,
            "incidents": self.incidents(),
        }
