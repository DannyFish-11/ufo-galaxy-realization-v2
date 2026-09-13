"""core/interaction/decision_withdrawal.py — 分叉之后,把没人要的那几支收回来
===============================================================================

问题
----
``request_human_decision`` 会把同一条 ``decision_request`` **并行分叉**给所有连着的
手表与手机(见 ``_discover_target_devices``)。服务端这边处理了重复回答 ——
``PendingDecisionRegistry.resolve`` 的注释写着 "First reply wins; later replies for
the same id are no-ops"。

**但没有任何东西告诉其余设备把通知撤下来。**

于是:手表和手机上各弹一条。你在手表上答完,**手机上那条还挂着**。点它是 no-op,
可手机本地的 ``ReplyReceiver`` 会把通知消掉 —— 从用户视角看"答成功了",实际什么
都没发生。更糟的是你可能在手机上给了个**不同**的答案,然后以为它生效了。

而且记录自己都不知道分叉去了哪儿:``register(..., devices=devices or [])`` 在
``devices=None``(最常见的情况)时存的是空列表,真正的目标是之后 ``_discover_target_devices``
算出来的,从没写回记录。

借鉴
----
这是 SIP 在 1999 年就解掉的问题(RFC 3261 §16.7):代理把 INVITE **分叉**到一个
AOR 注册的全部 contact,某一支回了 200 OK 之后,代理立刻向**其余每一支**发 CANCEL,
那些终端就停止振铃。没有这一步,挂掉电话之后别的分机还在响。

这里逐字照搬那个语义,只是把 CANCEL 换成 ``decision_withdraw``。

原因必须是封闭枚举
------------------
同样借 SIP/Q.850 的纪律:拒绝与撤回**永远带一个机器可读的原因**,而且原因取自一个
**封闭集合**,不是自由文本。理由很实际 —— 设备要据此决定怎么呈现:

  · "别人已经答了" → 静默收起,不打扰;
  · "超时了" → 可以留一条"这次没赶上"的痕迹;
  · "任务被取消了" → 同样静默收起,但语义不同,排障时要分得开。

自由文本做不到这件事:设备只能把它当字符串显示,或者去猜。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterable, List

__all__ = [
    "WithdrawReason",
    "DECISION_WITHDRAW_TYPE",
    "branches_to_withdraw",
    "build_withdraw_message",
    "reason_for_status",
]

#: wire 类型名。三仓 SSOT:``galaxy_gateway/protocol/aip_v3.py`` 是权威,
#: ``core/schemas/aip_v3.py`` 与 Kotlin ``MsgType`` 跟随。
DECISION_WITHDRAW_TYPE = "decision_withdraw"


class WithdrawReason(str, Enum):
    """为什么这一支被收回。**封闭集合** —— 不许传自由文本。"""

    #: 另一台设备已经答了。最常见的一支,对应 SIP 里被 CANCEL 的那些分支。
    ANSWERED_ELSEWHERE = "answered_elsewhere"

    #: 没人在超时之前应答。注意:超时**不等于**同意(见 high_risk_confirmation)。
    TIMED_OUT = "timed_out"

    #: 提问方自己撤销了(任务被取消、进程要关)。
    CANCELLED = "cancelled"

    #: 被一条更新的决策取代。
    SUPERSEDED = "superseded"


def reason_for_status(status: str) -> WithdrawReason:
    """把 ``DecisionOutcome.status`` 折成撤回原因。

    未知状态一律折成 [WithdrawReason.CANCELLED] —— 保守收起,而不是让通知留在那儿。
    留着的代价是用户对着一条已经没有意义的通知做决定;收错了的代价只是少一条通知。
    """
    s = (status or "").strip().lower()
    if s in ("resolved", "answered"):
        return WithdrawReason.ANSWERED_ELSEWHERE
    if s in ("timeout", "timed_out", "timeout_cancel", "timeout_default"):
        return WithdrawReason.TIMED_OUT
    if s in ("superseded",):
        return WithdrawReason.SUPERSEDED
    return WithdrawReason.CANCELLED


def branches_to_withdraw(targets: Iterable[str], answered_by: str = "") -> List[str]:
    """该向哪些设备发撤回。

    答了的那一台**不在其中** —— 它自己就是那个答案,它的界面已经翻篇了,再收一条
    "撤回"只会让它显示一条莫名其妙的东西。这也是 SIP 的做法:CANCEL 发给**其余**分支,
    不发给回了 200 的那一支。

    去重并保序(便于排障时按发出顺序读日志);空 device_id 丢掉。
    """
    answered = (answered_by or "").strip()
    seen: set[str] = set()
    out: List[str] = []
    for raw in targets or ():
        did = (raw or "").strip()
        if not did or did == answered or did in seen:
            continue
        seen.add(did)
        out.append(did)
    return out


def build_withdraw_message(decision_id: str, reason: WithdrawReason) -> Dict[str, Any]:
    """一条 ``decision_withdraw`` 的 wire 形状。

    刻意**只带 decision_id 和 reason**:设备要做的只是"把这条收起来",不需要知道
    别人答了什么。把答案一起广播出去等于把一次私人决定发给每一台设备。
    """
    return {
        "type": DECISION_WITHDRAW_TYPE,
        "payload": {
            "decision_id": decision_id,
            "reason": reason.value,
        },
    }
