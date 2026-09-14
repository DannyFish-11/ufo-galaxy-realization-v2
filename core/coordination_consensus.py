"""core/coordination_consensus.py — 在候选中选一个之前,先问问它们
====================================================================

只做相位 2。别的相位都已经有主
------------------------------
上一轮我把相位 0+1 也写了一遍,结果是一份**重复实现** —— CI 的 Reachability 闸抓了
个正着,而真问题不是"不可达"是"冗余"。这次先查清楚:

============  ================================================================
相位 0 该不该做   ``core.continuum.decision_gate``(value − cost → ActionLevel)
相位 1 谁有资格   ``core.unified_dispatch_readiness_gate`` 的**七道闸**
                  (peer trust / 注册 / UDM / 传输存活 / 运行时附着 / 能力 / 跨设备资格)
相位 3 问人       ``core.interaction.high_risk_confirmation``(fail-closed,已接手表)
相位 4 派发       ``CommandRouter`` / ``DeviceRouter``
============  ================================================================

**只有相位 2 是缺的**:中心从自己这边知道的一切都查过了,但从没问过设备本人。
``capability_query`` 查的是中心侧的能力图,不是往设备发一次询问 —— 已核实。

设备知道什么中心不知道的
------------------------
它此刻忙不忙、本地 Agent 就位没有、它自己的 decision_gate 说不说该做。这些中心
查不到,而且**过几百毫秒就变**。

承诺必带有效期,过期就作废
--------------------------
设备说"我能做"时看到的那一屏,几秒之后可能已经不在了。这和截图节流(333ms 之后
那张图就不一定算数)、控件树按坐标复定位是同一类问题:**一个在时刻 T 成立的判断,
不能无限期当成在 T+n 也成立。**

``valid_until_ms == 0`` 判为**不可用** —— 一条没有有效期的承诺等于让中心去赌。

拒绝原因是封闭枚举
------------------
借 SIP/Q.850 的纪律。中心要据此换策略:busy 换一台、not_ready 等一会儿再问同一台、
policy_declined 换台也没用别重试、no_permission 去问人。自由文本只能被记进日志,
然后对所有失败一视同仁。

只在**多个候选**时才问
----------------------
一台候选时没有什么可"达成一致"的 —— 相位 1 的七道闸已经回答了"这一台能不能接"。
为单目标派发加一轮往返,会让最常见的那条路变慢变脆,然后所有人开始想办法绕过
共识层;绕过去之后,该问人的地方也一起被绕过去了。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.CoordinationConsensus")

__all__ = [
    "DeclineReason",
    "NarrowResult",
    "narrow_candidates",
    "Commitment",
    "SurfaceChoice",
    "DEFAULT_COMMITMENT_TTL_MS",
    "consensus_required",
    "usable_commitments",
    "pick_execution_surface",
]

#: 承诺的默认有效期。
#:
#: **这个数是推的,不是量的。** 真实取值取决于 NATS 往返延迟与设备唤醒时间,
#: 而本仓从未在真机上量过这两项。5 秒的取舍:比一次正常往返(百毫秒量级)宽裕得多,
#: 又短到"界面在这期间大改"的概率很低。
#:
#: 设备可以在自己的承诺里给一个更短的值 —— 它比中心更清楚自己的状态会变多快。
#: 真机数据出来之后,这个默认值该被替换,而不是被默默沿用。
DEFAULT_COMMITMENT_TTL_MS = 5_000


class DeclineReason(str, Enum):
    """设备为什么不接。**封闭集合** —— 不许自由文本。"""

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
        """现在还算不算数。接了、有有效期、还没过期 —— 三个缺一不可。"""
        return bool(self.accepted) and self.valid_until_ms > 0 and now_ms < self.valid_until_ms

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "Commitment":
        """从 wire 上的 ``execution_commitment`` 还原。

        ``accepted`` 默认 **False** —— 字段缺失、类型不对、老版本设备不认识这条消息,
        一律按"不接"处理。fail-closed。
        """
        p = payload or {}
        return cls(
            device_id=str(p.get("device_id") or ""),
            accepted=p.get("accepted") is True,
            valid_until_ms=int(p.get("valid_until_ms") or 0),
            decline_reason=str(p.get("decline_reason") or ""),
            best_level=str(p.get("best_level") or ""),
        )


@dataclass(frozen=True)
class SurfaceChoice:
    """选的结果,以及**为什么没选上别的**。"""

    chosen: Optional[Commitment] = None
    declined: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.chosen is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "chosen": self.chosen.device_id if self.chosen else "",
            "best_level": self.chosen.best_level if self.chosen else "",
            "declined": dict(self.declined),
        }


def consensus_required(candidate_count: int) -> bool:
    """要不要走这一轮协商。

    一台候选时没有什么可达成一致的 —— 相位 1 的七道闸已经回答了"这一台能不能接",
    再发一轮提议只是给最常见的那条路平白加一次往返。
    """
    return candidate_count > 1


def usable_commitments(commitments: Sequence[Commitment], now_ms: int) -> List[Commitment]:
    """还算数的那些。过期的、拒绝的、没有有效期的,一律不算。"""
    return [c for c in (commitments or ()) if c.is_usable(now_ms)]


def pick_execution_surface(
    commitments: Sequence[Commitment],
    now_ms: Optional[int] = None,
    *,
    score: Optional[Callable[[Commitment], float]] = None,
) -> SurfaceChoice:
    """从还算数的承诺里选一台,并把没选上的原因一并带出来。

    ``score`` 由调用方注入(``device_pool_manager`` 打负载分、
    ``cross_device_responsiveness_contract`` 打响应性分)。**本模块不自己造一套打分** ——
    仓里已经有两处在做这件事,再写第三份必然会漂。

    不给 score 时按承诺到达顺序取第一条:确定性、可解释,而不是"随便挑一个"。
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    usable = usable_commitments(commitments, now)
    declined = {
        c.device_id: (c.decline_reason or DeclineReason.NO_RESPONSE.value)
        for c in (commitments or ())
        if not c.is_usable(now)
    }
    if not usable:
        return SurfaceChoice(chosen=None, declined=declined)
    chosen = usable[0] if score is None else max(usable, key=score)
    return SurfaceChoice(chosen=chosen, declined=declined)


@dataclass(frozen=True)
class NarrowResult:
    """按承诺把候选收敛成什么。

    三种结局必须分得开,因为调用方对它们的反应完全不同:

      · ``narrowed``  收敛到一台 —— 派给它;
      · ``unchanged`` 这一轮没给出结论(没到多候选、没有收集器、承诺里的 id 不认识)
                      —— 按原候选走,**不阻断派发**;
      · ``all_declined`` 全部谢绝 —— 这是**有信息的失败**,比盲目派给第一台强:
                      那一台刚刚亲口说了它接不了。
    """

    device_ids: List[str]
    outcome: str
    declined: Dict[str, str] = field(default_factory=dict)
    note: str = ""


def narrow_candidates(
    candidate_ids: Sequence[str],
    commitments: Optional[Sequence[Commitment]],
    now_ms: Optional[int] = None,
    *,
    score: Optional[Callable[[Commitment], float]] = None,
) -> NarrowResult:
    """候选 + 承诺 → 该派给谁。纯函数。

    放在这里而不是 ``DeviceRouter`` 上:这是协商的判定,不是路由的管道。
    (顺带,复杂度闸也在拦 device_router 继续长胖 —— 而它说得对。)
    """
    ids = [str(i) for i in (candidate_ids or []) if str(i).strip()]
    if not consensus_required(len(ids)):
        return NarrowResult(ids, "unchanged", note="单候选:七道闸已经回答过这一台能不能接")
    if commitments is None:
        return NarrowResult(ids, "unchanged", note="没有承诺(收集器缺失或失败):不阻断派发")

    choice = pick_execution_surface(commitments, now_ms, score=score)
    if not choice.ok:
        # **没人听见** ≠ **所有人拒绝**。
        #
        # 全场清一色 no_response,最可能的解释不是"这些设备都说它做不了",而是
        # 这批设备根本不认识 execution_proposal(旧版本固件),或者网格断了。
        # 把它当成全员谢绝,结果是候选清空、派发直接消失 —— 一个尚未铺开的协商
        # 机制会把整条跨设备派发弄瘫,而现象只是"命令没反应"。
        #
        # 至少有一台**明确**说了不接,才算得到了回答:那时空候选是有信息的失败。
        reasons = set(choice.declined.values())
        if reasons <= {DeclineReason.NO_RESPONSE.value}:
            return NarrowResult(ids, "unchanged", declined=choice.declined, note="全场沉默:按没问过处理,不阻断派发")
        return NarrowResult([], "all_declined", declined=choice.declined, note="全部谢绝或超时")

    chosen = choice.chosen.device_id if choice.chosen else ""
    if chosen not in ids:
        # 承诺里的 id 不在候选里 —— 退回原候选,而不是返回空(那会被当成全员谢绝)。
        return NarrowResult(ids, "unchanged", declined=choice.declined, note=f"承诺的 {chosen!r} 不在候选里")
    return NarrowResult([chosen], "narrowed", declined=choice.declined)


def _default_collector() -> Optional[Callable[..., Any]]:
    """没人显式注入时用的收集器 —— 真的发提议、真的等承诺。

    **默认是开的。** 一个"接好了但要人另外打开"的机制,等于没接:它的成本(多一层
    代码要维护)照付,收益一分拿不到,而且没有任何现象会提醒你它从没运行过。

    ``GALAXY_CONSENSUS_ROUND=0`` 关掉它 —— 留给"这一轮明确不想要"的部署,而不是留给
    "还没想好"。关掉之后行为与接入之前逐字相同。

    传输层拿不到(库缺失、网关没起)时返回 ``None``,上层按"没有收集器"原样放行。
    """
    if os.getenv("GALAXY_CONSENSUS_ROUND", "1").strip() in ("0", "false", "off", "no"):
        return None
    try:
        from core.coordination_commitment_collector import make_commitment_collector  # noqa: PLC0415

        return make_commitment_collector()
    except Exception as exc:  # noqa: BLE001 — 收集器造不出来不该阻断派发
        logger.debug("默认收集器不可用,按没有收集器处理: %s", exc)
        return None


async def narrow_devices(
    devices: Sequence[Any],
    command: str,
    ctx: Optional[Dict[str, Any]] = None,
    *,
    score: Optional[Callable[[Commitment], float]] = None,
) -> List[Any]:
    """把设备对象列表按承诺收敛。给 ``DeviceRouter`` 用的那层壳。

    整个编排放在这里而不是路由器上,是因为它属于协商:发一轮提议、按封闭枚举读回答、
    据此收敛。路由器只负责把候选交进来、把结果拿回去。

    **拿不到收集器时原样返回**,不阻断派发:这一步是对既有选择的*精化*,不是新增的
    必过闸。做成必过闸会让"协商通道还没接好"直接等于"跨设备派发不可用" —— 那种耦合
    一旦出现,下一步就是有人去绕过整个共识层,连该问人的地方一起绕掉。

    ``ctx["_commitment_collector"]`` 是一个 ``async (ids, command) -> 承诺序列`` 的可调用
    对象,由接上 AIP 传输的那一层注入。收集器抛异常按"没收到承诺"处理并记 warning:
    协商链路坏了是运维问题,不该表现成派发功能消失。
    """
    ids = [str(getattr(d, "device_id", "") or "") for d in (devices or [])]
    if not consensus_required(len(ids)):
        return list(devices or [])

    collector = (ctx or {}).get("_commitment_collector") or _default_collector()
    commitments: Optional[List[Commitment]] = None
    if collector is not None:
        try:
            raw = await collector(ids, command)
            commitments = [c if isinstance(c, Commitment) else Commitment.from_payload(c) for c in (raw or [])]
        except Exception as exc:  # noqa: BLE001 — 协商链路故障不该阻断派发
            logger.warning("收集承诺失败,按原候选派发: %s", exc)

    result = narrow_candidates(ids, commitments, score=score)
    if result.outcome == "unchanged":
        return list(devices or [])
    if result.outcome == "all_declined":
        logger.warning("没有可用承诺,%d 个候选全部谢绝: %s", len(ids), result.declined)
        return []
    keep = set(result.device_ids)
    logger.info("协商收敛到 %s(谢绝: %s)", result.device_ids, result.declined or "无")
    return [d for d in (devices or []) if str(getattr(d, "device_id", "") or "") in keep]
