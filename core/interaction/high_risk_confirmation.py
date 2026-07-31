"""高风险工具的人类确认 —— 把「需要用户确认」从一堵墙变成一道门。

## 排查出来的问题

``ToolPermissionChecker`` 会对 DANGEROUS / CRITICAL 级工具返回
``requires_confirmation=True``,两处调用方(``CanonicalDispatcher._check_permission``
与 ``OpenClawd._dispatch_tool_call`` 的内联兜底)据此返回::

    {"success": False, "needs_confirmation": True,
     "error": "操作 [xxx] 需要用户确认（风险等级: critical）"}

**然后就没有然后了。** 全仓没有任何"授予确认"的机制:没有 confirm、没有
grant、没有 approve。实测 ``press_keys`` / ``file_delete`` / ``system_command``
/ ``execute`` 全部命中这条分支,也就是说**智能体永远无法执行任何危险操作** ——
它收到一句"需要用户确认",却没有任何办法去取得这个确认。

更糟的是失败形态:模型拿到这句话,要么放弃,要么反复重试撞同一堵墙,
而重试会被无进展检测早停成"stuck" —— 真正的原因(缺一条确认通路)
被伪装成了另一个问题。

## 这个模块做什么

只做**一件事**:问一下人,把回答折成"批准 / 不批准"。

复用既有的 canonical HITL 通路(``request_human_decision`` → ``decision_request``
→ 手表通知 / DecisionScreen → ``human_input`` → registry resolve),
**不另起炉灶**。手表那端已经有决策通知、选项按钮、语音回复和"等距三拍"
的专属振动模式了。

## 一律 fail closed

这是整个模块唯一重要的性质。**只有人明确点了"批准"才算批准**,其余
一切情况(超时、取消、没有可问的设备、点了拒绝、只说了句含糊的话、
底层抛异常)统统判为不批准。

三个具体的坑,每一个都有对应用例钉死:

1. ``request_human_decision`` 超时行为由 ``derive_default_on_timeout`` 推导,
   某些 urgency 下会推成 ``PROCEED`` —— 那意味着**没人应答等于放行**。
   所以这里**显式钉死** ``on_timeout=CANCEL`` 且不给 ``default_option``。
2. 手表支持自由语音回复。对一个破坏性操作来说,"嗯"、"行吧"这类含糊
   应答**不构成授权** —— 不去猜,一律判不批准,并说明原因。
3. 一台可问的设备都没有时,**立刻**判不批准,而不是干等一个注定超时的
   决策 —— 否则每次危险调用都要白白阻塞一整个超时周期。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

#: 选项 id。手表侧按这两个字符串回传 ``selected_option``。
APPROVE_ID = "approve"
DENY_ID = "deny"

#: ``DecisionStatus.RESOLVED`` 的线上值 —— "人真的应答了"。
#: 用字面量而不是 import 枚举:本模块的判定部分刻意不依赖注册表实现,
#: 有专门用例校验这个字面量与枚举一致,漂移会红。
RESOLVED_STATUS = "resolved"

#: 默认等人多久。可用 ``GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S`` 覆盖。
DEFAULT_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class ConfirmationOutcome:
    """确认结果。``approved`` 为 True 时才允许继续执行。"""

    approved: bool
    reason: str
    decision_id: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "decision_id": self.decision_id,
            "source": self.source,
        }


def _timeout_s() -> float:
    raw = os.environ.get("GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        return max(5.0, min(3600.0, float(raw)))
    except ValueError:
        logger.warning("GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S=%r 不是数字,用默认值", raw)
        return DEFAULT_TIMEOUT_S


def interpret_decision(outcome: Any) -> ConfirmationOutcome:
    """把 ``DecisionOutcome`` 折成"批准 / 不批准"。

    刻意做成**纯函数**(不碰网关、不碰协程),这样 fail-closed 的每一条
    规则都能在单测里被真跑一遍,而不是靠人工审阅。

    判据有**两条,缺一不可**:状态是"人真的应答了"(``RESOLVED``),
    且 ``selected_option`` 严格等于 :data:`APPROVE_ID`。

    为什么不能只看 ``selected_option``:超时会落到 ``default_option`` 上,
    取消也可能带着残留字段,那些情况下 ``selected_option`` 一样可能是
    ``"approve"``,但**没有任何人点过它**。只看选项就会把"没人应答"读成
    "批准"。这个洞是本模块的穷举用例先抓出来的,不是事后想到的。

    也**不能**用 ``DecisionOutcome.should_proceed`` —— 它对
    ``TIMEOUT_PROCEED`` / ``TIMEOUT_DEFAULT`` 都返回 True,拿它当判据等于
    超时即自动执行破坏性操作。
    """
    if outcome is None:
        return ConfirmationOutcome(False, "决策通路没有返回结果")

    decision_id = str(getattr(outcome, "decision_id", "") or "")
    source = str(getattr(outcome, "source", "") or "")

    if bool(getattr(outcome, "timed_out", False)):
        return ConfirmationOutcome(False, "等待确认超时,没有人应答", decision_id, source)

    raw_status = getattr(outcome, "status", None)
    # DecisionStatus 是 str 枚举,取 .value 才能跟字面量稳妥比较。
    status = str(getattr(raw_status, "value", raw_status) or "")
    selected = getattr(outcome, "selected_option", None)

    if selected == APPROVE_ID:
        if status != RESOLVED_STATUS:
            return ConfirmationOutcome(
                False,
                f"选项是批准,但决策状态是 {status!r} 而非 {RESOLVED_STATUS!r} —— 没有人真的点过它",
                decision_id,
                source,
            )
        return ConfirmationOutcome(True, "用户已明确批准", decision_id, source)
    if selected == DENY_ID:
        return ConfirmationOutcome(False, "用户明确拒绝", decision_id, source)

    voice = str(getattr(outcome, "voice_input", "") or "").strip()
    if voice:
        # 不去猜"嗯"、"行吧"算不算同意。破坏性操作上的含糊应答不构成授权。
        return ConfirmationOutcome(
            False,
            f"只收到自由语音回复「{voice[:40]}」,未点选明确的批准选项 —— 高风险操作不接受含糊授权",
            decision_id,
            source,
        )

    return ConfirmationOutcome(False, f"未收到明确批准(status={getattr(outcome, 'status', '?')})", decision_id, source)


def build_options() -> List[dict]:
    """决策选项。批准放在后面 —— 手表上误触第一个按钮的代价不该是执行破坏性操作。"""
    return [
        {"id": DENY_ID, "label": "不要"},
        {"id": APPROVE_ID, "label": "批准"},
    ]


async def confirm_high_risk_tool(
    *,
    tool_name: str,
    risk_level: str = "unknown",
    session_id: str = "",
    device_id: str = "",
    timeout_s: Optional[float] = None,
) -> ConfirmationOutcome:
    """问一下人:这个高风险操作要不要执行。

    任何一步出问题都返回**不批准**,绝不因为"问不到人"就放行。
    """
    try:
        from core.interaction.pending_decision_registry import (
            OnTimeout,
            _discover_target_devices,
            request_human_decision,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("高风险确认:HITL 通路不可用(%s)—— 判不批准", exc)
        return ConfirmationOutcome(False, f"人类确认通路不可用: {exc}")

    # 先看有没有可问的设备。一台都没有就立刻判不批准 —— 否则每次危险调用
    # 都要白等一整个超时周期,而结果注定是超时拒绝。
    try:
        targets = await _discover_target_devices()
    except Exception as exc:  # noqa: BLE001
        logger.warning("高风险确认:设备发现失败(%s)—— 判不批准", exc)
        return ConfirmationOutcome(False, f"无法发现可询问的设备: {exc}")

    if not targets:
        logger.warning("高风险确认:没有已连接的手表/手机可询问,%s 判不批准", tool_name)
        return ConfirmationOutcome(
            False,
            "没有已连接的设备可以询问 —— 高风险操作在无人可问时一律不执行",
        )

    wait_s = timeout_s if timeout_s is not None else _timeout_s()
    try:
        outcome = await request_human_decision(
            title=f"要执行 {tool_name} 吗？",
            summary=f"这是一个 {risk_level} 级操作，需要你点头才会执行。",
            options=build_options(),
            # 关键:**不给默认选项**、**钉死超时即取消**。
            # 不这么写的话,超时策略会由 urgency 推导,某些取值下会推成
            # PROCEED —— 那等于"没人应答就放行",是最坏的失败模式。
            default_option=None,
            on_timeout=OnTimeout.CANCEL,
            urgency="high",
            timeout_s=wait_s,
            devices=targets,
            session_id=session_id,
            runtime_session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("高风险确认:询问过程异常(%s)—— 判不批准", exc)
        return ConfirmationOutcome(False, f"询问过程异常: {exc}")

    result = interpret_decision(outcome)
    logger.info(
        "[AUDIT] 高风险确认 | 工具=%s 风险=%s 结果=%s 理由=%s decision_id=%s session=%s device=%s",
        tool_name,
        risk_level,
        "批准" if result.approved else "不批准",
        result.reason,
        result.decision_id,
        session_id,
        device_id,
    )
    return result
