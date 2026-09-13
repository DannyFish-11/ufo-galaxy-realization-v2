"""core/coordination_consensus.py — 动手之前,先就「该谁做」达成一致
=====================================================================

这不是 Raft
-----------
Raft 解的是「多副本对同一份状态达成一致」。这里解的是**动手之前的编排协商**:
一件事该不该做、落在哪台设备上、对方答不答应、以及什么时候必须停下来问人。

五个相位,每一相都能提前退出,退出就是终态
------------------------------------------

  相位 0  该不该做        ``coordination_preflight``(纯本地,零网络)
  相位 1  谁有资格参与     同上 —— 信任 / 能力分层 / 风险 × 信任
  相位 2  提议 / 承诺      **本模块**:发提议,收承诺,判有效期
  相位 3  问人            ``interaction.high_risk_confirmation``(既有,fail-closed)
  相位 4  落定 + 记账      选定执行面,通知落选方,交给调用方派发

单设备快路径
------------
候选池里只有本机时,**相位 2 整个跳过**。本机的就位状态本地就能读,不需要发一条
消息问自己,更不需要等一个超时。

这不只是性能。一个"哪怕单机也要走一遍协商"的设计会让本地模式变慢、变脆,然后
所有人开始想办法绕过共识层 —— 绕过去之后,敏感动作的人确认也一起被绕过去了。

承诺有有效期,而且过期就作废
----------------------------
设备说"我能做"时看到的那一屏,几秒之后可能已经不在了。这和截图节流(333ms 之后
那张图就不一定算数了)、控件树复定位是同一类问题:**一个在时刻 T 成立的判断,
不能无限期当成在 T+n 也成立。**

所以 ``pick_execution_surface`` 在选之前先按 ``now_ms`` 滤一遍。过期的承诺不是
"勉强能用",是**不算数**。

一律 fail-closed
----------------
超时不等于同意(沿用 ``high_risk_confirmation`` 已经钉死的原则);拒绝原因认不出来
按"不接"处理;协商层自己抛异常时唯一安全的默认是什么都不做。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.coordination_preflight import DeviceFacts, PreflightVerdict, evaluate as preflight_evaluate

logger = logging.getLogger("Galaxy.CoordinationConsensus")

__all__ = [
    "DeclineReason",
    "Commitment",
    "ConsensusOutcome",
    "LOCAL_DEVICE_ALIASES",
    "is_single_local_candidate",
    "usable_commitments",
    "pick_execution_surface",
    "decide",
]

#: 表示"就在本机"的 device_id。与 ``core.routes.ui_act`` 的那份保持一致:
#: 仲裁器全程用 ``device_id="local"`` 操作本机。
LOCAL_DEVICE_ALIASES = frozenset({"", "local", "localhost", "self", "this"})


class DeclineReason(str, Enum):
    """设备为什么不接。**封闭集合** —— 不许自由文本。

    借 SIP/Q.850 的纪律。原因必须机器可读,因为中心要据此换策略:

      · ``busy``            → 换一台;
      · ``not_ready``       → 等一会儿再问同一台;
      · ``policy_declined`` → 这台设备自己判定不该做,换台也没用,别重试;
      · ``no_permission``   → 去问人;
      · ``unsupported``     → 它做不了这类事,以后别再问它。

    自由文本让中心只能把它记进日志,然后对所有失败一视同仁。
    """

    BUSY = "busy"
    NOT_READY = "not_ready"
    POLICY_DECLINED = "policy_declined"
    NO_PERMISSION = "no_permission"
    UNSUPPORTED = "unsupported"
    #: 没在期限内回话。**不是设备说的**,是中心替它记下的 —— 沉默不是同意。
    NO_RESPONSE = "no_response"


@dataclass(frozen=True)
class Commitment:
    """一台设备对一次提议的回答。"""

    device_id: str
    accepted: bool = False
    valid_until_ms: int = 0
    decline_reason: str = ""
    best_level: str = ""

    def is_usable(self, now_ms: int) -> bool:
        """现在还算不算数。

        三个条件缺一不可:接了、有有效期、还没过期。``valid_until_ms == 0`` 判为
        **不可用** —— 一条没有有效期的承诺等于让中心去赌,而这个模块的立场是不赌。
        """
        return bool(self.accepted) and self.valid_until_ms > 0 and now_ms < self.valid_until_ms


@dataclass(frozen=True)
class ConsensusOutcome:
    """这次协商的结论。"""

    proceed: bool
    selected: str = ""
    needs_human: bool = False
    reason: str = ""
    #: 走到哪一相位为止。排障时第一个要看的东西。
    stopped_at: str = ""
    candidates: List[str] = field(default_factory=list)
    excluded: Dict[str, str] = field(default_factory=dict)
    fast_path: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proceed": self.proceed,
            "selected": self.selected,
            "needs_human": self.needs_human,
            "reason": self.reason,
            "stopped_at": self.stopped_at,
            "candidates": list(self.candidates),
            "excluded": dict(self.excluded),
            "fast_path": self.fast_path,
        }


def is_single_local_candidate(candidates: Sequence[str]) -> bool:
    """候选池是不是"只有本机一台"。是的话相位 2 可以整个跳过。"""
    ids = [c for c in (candidates or ()) if (c or "").strip()]
    if len(ids) != 1:
        return False
    return ids[0].strip().lower() in LOCAL_DEVICE_ALIASES


def usable_commitments(commitments: Sequence[Commitment], now_ms: int) -> List[Commitment]:
    """还算数的那些承诺。过期的、拒绝的、没有有效期的,一律不算。"""
    return [c for c in (commitments or ()) if c.is_usable(now_ms)]


def pick_execution_surface(
    commitments: Sequence[Commitment],
    now_ms: int,
    *,
    score: Optional[Callable[[Commitment], float]] = None,
) -> Optional[Commitment]:
    """从还算数的承诺里选一台。

    ``score`` 由调用方注入(``device_pool_manager`` 打负载分、
    ``cross_device_responsiveness_contract`` 打响应性分)。**本模块不自己造一套打分** ——
    仓里已经有两处在做这件事,再写第三份必然会漂。

    不给 score 时按承诺到达顺序取第一条:确定性的、可解释的,而不是"随便挑一个"。
    分不出高下时由调用方决定要不要升到相位 3 问人。
    """
    usable = usable_commitments(commitments, now_ms)
    if not usable:
        return None
    if score is None:
        return usable[0]
    return max(usable, key=score)


def decide(
    *,
    action_level: str,
    devices: Sequence[DeviceFacts],
    risk_level: str = "",
    collect: Optional[Callable[[List[str]], List[Commitment]]] = None,
    now_ms: Optional[int] = None,
    score: Optional[Callable[[Commitment], float]] = None,
) -> ConsensusOutcome:
    """跑完相位 0 → 1 →(必要时)2,给出"该谁做"。

    ``collect(candidate_ids) -> [Commitment]`` 是相位 2 的传输钩子:发提议、收承诺。
    注入它而不是在这里直接发 NATS,因为传输在本仓的测试环境里跑不起来,而**判定
    逻辑必须可测** —— 这层的全部价值就在判定。

    相位 3(问人)与相位 4(派发)**不在这里做**:问人有既有的 canonical 通路
    (``high_risk_confirmation``,fail-closed,已接到手表),派发有 ``CommandRouter``。
    本函数只负责把"要不要问人"和"选了谁"算出来交给它们 —— 再写一遍就是第二份实现。
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)

    # ── 相位 0 + 1 ────────────────────────────────────────────────────────
    pre: PreflightVerdict = preflight_evaluate(action_level=action_level, devices=devices, risk_level=risk_level)
    if not pre.proceed:
        return ConsensusOutcome(
            proceed=False,
            reason=pre.reason,
            stopped_at="preflight",
            excluded=pre.excluded,
        )

    # ── 单设备快路径:不给本地任务加一轮网络往返 ──────────────────────────
    if is_single_local_candidate(pre.candidates):
        return ConsensusOutcome(
            proceed=True,
            selected=pre.candidates[0],
            needs_human=pre.needs_human,
            reason=pre.reason,
            stopped_at="fast_path",
            candidates=list(pre.candidates),
            excluded=pre.excluded,
            fast_path=True,
        )

    # ── 相位 2:提议 / 承诺 ───────────────────────────────────────────────
    if collect is None:
        # 没有传输钩子却有多个候选 —— 这是接线错误,不是"就按第一台算"。
        # 静默挑一台会让这个错误永远查不出来。
        return ConsensusOutcome(
            proceed=False,
            reason="no_transport_for_proposal",
            stopped_at="phase2",
            candidates=list(pre.candidates),
            excluded=pre.excluded,
        )

    try:
        commitments = list(collect(list(pre.candidates)))
    except Exception as exc:  # noqa: BLE001
        # 协商层自己出错时,唯一安全的默认是什么都不做。
        logger.warning("协商收集承诺失败: %s", exc)
        return ConsensusOutcome(
            proceed=False,
            reason="collect_failed",
            stopped_at="phase2",
            candidates=list(pre.candidates),
            excluded=pre.excluded,
        )

    chosen = pick_execution_surface(commitments, now, score=score)
    if chosen is None:
        declines = {
            c.device_id: (c.decline_reason or DeclineReason.NO_RESPONSE.value)
            for c in commitments
            if not c.is_usable(now)
        }
        return ConsensusOutcome(
            proceed=False,
            reason="no_usable_commitment",
            stopped_at="phase2",
            candidates=list(pre.candidates),
            excluded={**pre.excluded, **declines},
        )

    return ConsensusOutcome(
        proceed=True,
        selected=chosen.device_id,
        needs_human=pre.needs_human,
        reason=pre.reason,
        stopped_at="committed",
        candidates=list(pre.candidates),
        excluded=pre.excluded,
    )
