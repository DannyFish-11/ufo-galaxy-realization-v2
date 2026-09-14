"""core/coordination_commitment_collector.py — 把提议真的发出去,把承诺真的收回来
==============================================================================

``core.coordination_consensus`` 是判定:给一堆承诺,选谁。本模块是它的**传输侧** ——
没有这一层,``narrow_devices`` 永远拿不到收集器,那一轮协商就只是"写好了但从不发生"。

和 HITL 那套的区别:先到先得 vs 收齐再说
----------------------------------------
``pending_decision_registry`` 求的是**一个**答案,第一条回复就赢(SIP 分叉语义,
其余分支随后被 CANCEL)。这里求的是**每一台**的表态:三台候选就要三份回答,才谈得上
"在它们之间选"。所以不能复用那个登记处 —— 它的 ``resolve`` 一被调用整轮就结束了。

沉默不是同意
------------
到期还没回话的设备,由中心替它记一条 ``no_response`` 的**拒绝**,而不是当它默许。
理由和 ``Commitment.accepted`` 默认 False 是同一条:老版本设备不认识
``execution_proposal``,它的沉默只说明它没听懂,不说明它能做。

超时到了就走,不等齐
-------------------
等齐所有回答会让**最慢的那台**决定整轮的延迟,而慢往往正是因为它忙 —— 也就是最
不该派给它的那台。到期就用手上有的答案作数;都没回来,上层的 ``all_declined``
会接住,那是个有信息的失败。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from core.coordination_consensus import DEFAULT_COMMITMENT_TTL_MS, Commitment, DeclineReason

logger = logging.getLogger("Galaxy.CommitmentCollector")

__all__ = [
    "CommitmentRound",
    "CommitmentRegistry",
    "get_commitment_registry",
    "collect_commitments",
    "make_commitment_collector",
    "reset_silence_backoff",
    "SILENCE_BACKOFF_S",
]

EmitCallback = Callable[[str, Dict[str, Any]], Awaitable[Any]]

#: 等承诺等多久。**这个数是推的,不是量的** —— 本仓从未在真机上量过 NATS 往返与
#: 设备唤醒。取 1.2 秒的取舍:比一次正常往返宽裕,又短到不会让用户觉得"按了没反应"。
#: 它必须明显小于 ``DEFAULT_COMMITMENT_TTL_MS``(5s):收上来的承诺得还剩点有效期可用,
#: 否则等于收了一堆刚到手就过期的废纸。
DEFAULT_COLLECT_TIMEOUT_S = 1.2

#: 全场沉默之后,多久内不再发提议。
#:
#: 一整批设备都不回话,几乎只有一个解释:这批固件还不认识 ``execution_proposal``。
#: 那就不该每次派发都为它们再付一次 1.2 秒 —— 用户看到的是"每条跨设备命令都卡一下",
#: 而卡出来的信息量是零。记下来,退避一分钟再试;期间新固件上线,最多晚一分钟被发现。
SILENCE_BACKOFF_S = 60.0

#: 上一次"发了提议但一个都没回"的时刻。0 表示没发生过(或退避已过期)。
_silent_since: float = 0.0


def _in_silence_backoff(now: float) -> bool:
    return _silent_since > 0 and (now - _silent_since) < SILENCE_BACKOFF_S


def reset_silence_backoff() -> None:
    """清掉退避。测试用;运维上想立刻重试一轮也可以调。"""
    global _silent_since
    _silent_since = 0.0


@dataclass
class CommitmentRound:
    """一轮提议的在途状态。"""

    proposal_id: str
    expected: List[str]
    replies: Dict[str, Commitment] = field(default_factory=dict)
    _done: asyncio.Event = field(default_factory=asyncio.Event)

    def accept_reply(self, commitment: Commitment) -> bool:
        """记一条回复。**只收这一轮问过的设备** —— 没问过的不算数。"""
        if commitment.device_id not in self.expected:
            logger.debug("轮 %s 收到没问过的设备 %s 的承诺,丢弃", self.proposal_id, commitment.device_id)
            return False
        if commitment.device_id in self.replies:
            return False  # 重复回复:先到的作数,后到的不覆盖
        self.replies[commitment.device_id] = commitment
        if len(self.replies) >= len(self.expected):
            self._done.set()
        return True

    async def wait(self, timeout_s: float) -> None:
        """等齐,或者等到点。到点不是错误,是正常出口。"""
        try:
            await asyncio.wait_for(self._done.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            pass

    def settle(self) -> List[Commitment]:
        """连没回话的一起给出答案:沉默 → ``no_response`` 的拒绝。"""
        return [
            self.replies.get(did)
            or Commitment(device_id=did, accepted=False, decline_reason=DeclineReason.NO_RESPONSE.value)
            for did in self.expected
        ]


class CommitmentRegistry:
    """在途的提议轮次。入站的 ``execution_commitment`` 靠它找到该唤醒谁。"""

    def __init__(self) -> None:
        self._rounds: Dict[str, CommitmentRound] = {}

    def open(self, expected: Sequence[str], proposal_id: str = "") -> CommitmentRound:
        pid = proposal_id or f"prop-{uuid.uuid4().hex[:12]}"
        rnd = CommitmentRound(proposal_id=pid, expected=[str(d) for d in expected])
        self._rounds[pid] = rnd
        return rnd

    def close(self, proposal_id: str) -> None:
        self._rounds.pop(proposal_id, None)

    def resolve(self, proposal_id: str, payload: Dict[str, Any]) -> bool:
        """入站回调:一条 ``execution_commitment`` 到了。

        轮次不存在(已超时收摊、或 id 是伪造的)时返回 False 而不是抛 —— 迟到的回复
        是常态,不是故障。
        """
        rnd = self._rounds.get(str(proposal_id or ""))
        if rnd is None:
            return False
        return rnd.accept_reply(Commitment.from_payload(payload))

    @property
    def open_rounds(self) -> List[str]:
        return list(self._rounds)


_registry: Optional[CommitmentRegistry] = None


def get_commitment_registry() -> CommitmentRegistry:
    global _registry
    if _registry is None:
        _registry = CommitmentRegistry()
    return _registry


async def _default_emit(device_id: str, message: Dict[str, Any]) -> Any:
    """默认传输:走网关连接管理器,和 HITL 的提问走同一条路。

    **把返回值带出来。** 这条路上的 ``send_to_device`` 有两种约定:
    ``UnifiedConnectionManager`` 发不出去时返回 ``False`` 并只记一条 warning(不抛),
    而 ``GatewayWSManager`` 成功时返回 ``None``。只 ``await`` 不看返回值,就会把
    "设备根本不可达"当成"已送达",然后白等一个超时 —— 实测正是如此(1.7s)。
    """
    from core import upper_ports  # noqa: PLC0415

    connection_manager = upper_ports.resolve("gateway.websocket_handler.connection_manager")
    return await connection_manager.send_to_device(device_id, message)


def _proposal_message(proposal_id: str, command: str, ttl_ms: int) -> Dict[str, Any]:
    return {
        "type": "execution_proposal",
        "payload": {
            "proposal_id": proposal_id,
            "command": command,
            "ttl_ms": ttl_ms,
            "source": "openclawd",
            "timestamp": time.time(),
        },
    }


async def collect_commitments(
    device_ids: Sequence[str],
    command: str,
    *,
    emit: Optional[EmitCallback] = None,
    timeout_s: float = DEFAULT_COLLECT_TIMEOUT_S,
    ttl_ms: int = DEFAULT_COMMITMENT_TTL_MS,
) -> List[Commitment]:
    """向候选发一轮 ``execution_proposal``,收回它们的 ``execution_commitment``。

    **发不出去的设备当场记为拒绝**,而不是让它白占一个等待名额:连接已经断了的设备,
    等它 1.2 秒没有任何意义,只会把这轮的延迟顶到超时上限。
    """
    global _silent_since

    ids = [str(d) for d in (device_ids or []) if str(d).strip()]
    if not ids:
        return []
    if _in_silence_backoff(time.time()):
        logger.debug("仍在沉默退避期内,跳过这一轮提议")
        return []

    registry = get_commitment_registry()
    rnd = registry.open(ids)
    _emit = emit or _default_emit
    message = _proposal_message(rnd.proposal_id, command, ttl_ms)

    for did in ids:
        try:
            sent = await _emit(did, message)
            if sent is False:  # 显式的 False 才算失败;None 是"成功但没有返回值"的约定
                raise ConnectionError("connection manager reported the device as unreachable")
        except Exception as exc:  # noqa: BLE001 — 一台发不出去不该拖垮整轮
            # 发不出去记 **no_response**,不是 not_ready:not_ready 是设备说的话,
            # 而这里设备根本没听见。这个区分在上层是有后果的 —— 全场 no_response
            # 会被当成"没问过"放行,全场 not_ready 会被当成"都拒绝"清空候选。
            logger.debug("提议发往 %s 失败,记为无回应: %s", did, exc)
            rnd.accept_reply(Commitment(device_id=did, accepted=False, decline_reason=DeclineReason.NO_RESPONSE.value))

    try:
        await rnd.wait(timeout_s)
        settled = rnd.settle()
        # 一条回复都没收到 → 记下沉默,下一分钟内不再发。注意这里看的是 ``replies``
        # 而不是 settle() 的结果:settle 会给沉默的设备补上 no_response,从它看不出
        # "有没有人回过话"。
        _silent_since = time.time() if not rnd.replies else 0.0
        return settled
    finally:
        registry.close(rnd.proposal_id)


def make_commitment_collector(
    *,
    emit: Optional[EmitCallback] = None,
    timeout_s: float = DEFAULT_COLLECT_TIMEOUT_S,
) -> Callable[[Sequence[str], str], Awaitable[List[Commitment]]]:
    """造一个能塞进 ``ctx["_commitment_collector"]`` 的收集器。

    ``narrow_devices`` 只认这个形状:``async (ids, command) -> 承诺序列``。
    做成工厂而不是直接把 ``collect_commitments`` 塞进去,是为了让超时和传输可注入 ——
    测试要能不起网关就跑,真机调优要能改超时而不改调用点。
    """

    async def _collect(ids: Sequence[str], command: str) -> List[Commitment]:
        return await collect_commitments(ids, command, emit=emit, timeout_s=timeout_s)

    return _collect
