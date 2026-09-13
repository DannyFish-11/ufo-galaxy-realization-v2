"""core/coordination_preflight.py — 问任何设备之前,本地已经知道的那些事
=========================================================================

这是跨设备协商的**相位 0 与相位 1**:全部输入本地可得,**一个网络包都不发**。

为什么要有这一层
----------------
协商的代价是一次往返。在发出去之前,有一大类结论其实本地就能下:

  · 这件事根本没到"动手"的程度(``decision_gate`` 已经算过了);
  · 这台设备被拉黑了(``peer_trust`` 的 blocked 是硬拒绝);
  · 这台设备**当不了执行面**(``CapabilityTier.command_only`` 是明文政策);
  · 这次动作需要人点头(风险分级 × 对端信任)。

把这些前移,换来的不只是快。一个"注定不会回"的设备如果进了候选池,每次协商都要
为它白等一整个超时周期 —— 而智能灯泡永远不会回。**IoT 设备应该在这里被挡下,
而不是在超时里被挡下。**

两张表打架,由这里判
--------------------
``core/device_policy.py`` 把 ``IOT`` 放进 ``PHYSICAL_DEVICE_TYPES``,于是
``requires_agent_deploy("IOT")`` 返回 True —— 按这条,一个智能灯泡也要先给它部署
一个 Agent。而 ``canonical_capability_scheduling_basis`` 的政策写着 command_only
设备 **MUST NOT be selected as an execution surface**。

同一台设备,一张表说"先给它装 Agent",另一张说"它根本不能当执行面"。

**这里以 CapabilityTier 为准**,理由不是投票,是粒度:``requires_agent_deploy`` 只看
**设备类型**(一个字符串),``CapabilityTier`` 看的是**这台设备此刻的运行时姿态**
(join_runtime / 自治标志 / 协调角色)。同为 IOT,一个跑 Linux 的网关和一个灯泡差得
远,类型那一层分不出来,tier 分得出来。

类型级的判定不是没用 —— 它回答"这一类硬件按惯例要不要预部署"。但它**不能否决**
运行时的观测结果。所以顺序是:先按 tier 定能不能执行,能执行的再谈要不要预部署。

一律 fail-closed
----------------
判不出来就是不行。``unknown`` tier 按 command_only 处理(那本来就是它的文档语义),
拿不到信任记录按 ``ask`` 处理(需要人确认),没有候选就直接停 —— 不去"挑一个最像的"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "EXECUTION_CAPABLE_TIERS",
    "STOP_BELOW_EXECUTE",
    "STOP_NO_CANDIDATE",
    "DeviceFacts",
    "PreflightVerdict",
    "may_be_execution_surface",
    "evaluate",
]

#: 能被选为执行面的 tier。其余(command_only / unknown / 任何没见过的值)一律不行。
#: 这不是本模块的发明,是 ``canonical_capability_scheduling_basis`` 的明文政策
#: ``COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_V1`` / ``CAPABILITY_TIER_DRIVES_SURFACE_V1``。
EXECUTION_CAPABLE_TIERS = frozenset({"full_runtime", "partial_runtime"})

STOP_BELOW_EXECUTE = "below_execute"
STOP_NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class DeviceFacts:
    """一台候选设备,本地已知的那几件事。

    刻意只收**本地可得**的字段:这一层的全部意义就是不发网络包。设备"此刻忙不忙"、
    "就位没有"都不在这里 —— 那要问它本人,是相位 2 的事。
    """

    device_id: str
    capability_tier: str = "unknown"
    device_type: str = ""
    #: ``peer_trust.PeerTrustBook.check()`` 的结论:allowed / denied / require_approval。
    trust_result: str = "require_approval"


@dataclass(frozen=True)
class PreflightVerdict:
    """相位 0+1 的结论。冻结:判定不该在后续相位里被改写。"""

    proceed: bool
    candidates: List[str] = field(default_factory=list)
    needs_human: bool = False
    reason: str = ""
    #: device_id → 被排除的原因。**每一台被排除的都要有理由** ——
    #: 一个静默消失的候选设备,排障时无从查起。
    excluded: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proceed": self.proceed,
            "candidates": list(self.candidates),
            "needs_human": self.needs_human,
            "reason": self.reason,
            "excluded": dict(self.excluded),
        }


def may_be_execution_surface(capability_tier: str) -> bool:
    """这个 tier 能不能被选为执行面。

    不看 device_type。见模块 docstring 里"两张表打架"那一节:类型只知道这是什么硬件,
    tier 知道这台机器此刻是什么姿态,而后者才是"能不能跑东西"的依据。
    """
    return str(capability_tier or "").strip().lower() in EXECUTION_CAPABLE_TIERS


def evaluate(
    *,
    action_level: str,
    devices: Sequence[DeviceFacts],
    risk_level: str = "",
    high_risk_levels: Optional[Sequence[str]] = None,
) -> PreflightVerdict:
    """相位 0 + 相位 1。纯函数,零网络。

    ``action_level`` 取自 ``core.continuum.decision_gate``(observe / hint / assist /
    execute)。只有 ``execute`` 才继续 —— 其余三档都不是"动手",为它们发起一轮跨设备
    协商是纯浪费。

    ``risk_level`` 取自 ``core.governance.tool_governor`` 的风险分级。
    """
    # ── 相位 0:该不该做 ──────────────────────────────────────────────────
    if str(action_level or "").strip().lower() != "execute":
        return PreflightVerdict(
            proceed=False,
            reason=STOP_BELOW_EXECUTE,
        )

    # ── 相位 1:谁有资格参与 ──────────────────────────────────────────────
    high_risk = {str(x).strip().lower() for x in (high_risk_levels or ("dangerous", "critical"))}
    risk = str(risk_level or "").strip().lower()

    candidates: List[str] = []
    excluded: Dict[str, str] = {}
    any_needs_approval = False

    for dev in devices or ():
        did = (dev.device_id or "").strip()
        if not did:
            continue

        trust = str(dev.trust_result or "").strip().lower()
        if trust == "denied":
            # blocked 是硬拒绝:不看意图、不看 tier、不看风险。
            excluded[did] = "peer_trust_blocked"
            continue

        if not may_be_execution_surface(dev.capability_tier):
            # 这里就是 IoT 被挡下的地方 —— 在发出任何网络包之前,而不是在一个
            # 注定不会有人回的超时里。
            excluded[did] = f"tier_cannot_execute:{dev.capability_tier or 'unknown'}"
            continue

        if trust != "allowed":
            # require_approval(以及任何认不出来的值)→ 这台设备能参与,但这次要人点头。
            any_needs_approval = True
        candidates.append(did)

    if not candidates:
        return PreflightVerdict(
            proceed=False,
            reason=STOP_NO_CANDIDATE,
            excluded=excluded,
        )

    needs_human = any_needs_approval or (risk in high_risk)
    return PreflightVerdict(
        proceed=True,
        candidates=candidates,
        needs_human=needs_human,
        reason="high_risk_action" if (risk in high_risk) else ("trust_requires_approval" if any_needs_approval else ""),
        excluded=excluded,
    )
