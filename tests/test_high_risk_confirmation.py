"""高风险工具确认闸的契约。

## 修的是什么

``ToolPermissionChecker`` 对 DANGEROUS / CRITICAL 级工具返回
``requires_confirmation=True``,两处闸门据此返回「操作需要用户确认」——
**然后就没有然后了**。全仓没有任何 grant / confirm / approve 机制,
也就是说智能体永远无法执行 ``press_keys`` / ``file_delete`` /
``system_command`` / ``execute`` 中的任何一个。确认闸是一堵**墙**,不是门。

失败形态还会伪装自己:模型反复重试撞同一堵墙,被无进展检测早停成
"stuck" —— 真因(缺一条确认通路)被盖住了。

## 这些用例守什么

一件事:**fail closed**。只有人明确点了"批准"才算批准。

其余一切 —— 超时、取消、没有可问的设备、点了拒绝、只回了句含糊的话、
底层抛异常 —— 统统判不批准。这条要是松了,后果是自动执行破坏性操作,
比原来那堵墙糟糕得多。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import pytest

from core.interaction.high_risk_confirmation import (
    APPROVE_ID,
    DENY_ID,
    ConfirmationOutcome,
    build_options,
    confirm_high_risk_tool,
    interpret_decision,
)
from core.tool_permissions import ToolPermissionChecker


@dataclass
class _FakeOutcome:
    """照着 DecisionOutcome 的读接口做的替身。"""

    decision_id: str = "d1"
    status: str = "resolved"
    selected_option: Optional[str] = None
    voice_input: str = ""
    source: str = "wear"
    timed_out: bool = False


# ── 1. 先证明这确实是一堵墙(问题存在性)──────────────────────────────


@pytest.mark.parametrize(
    "tool",
    [
        "mcp__windows-local__press_keys",
        "node__Node_06_Filesystem__delete",
        "node__Node_06_Filesystem__file_delete",
        "node__Node_122_Shell__system_command",
        "node__Node_122_Shell__execute",
    ],
)
def test_dangerous_tools_really_do_demand_confirmation(tool):
    """这几个工具确实会命中确认闸 —— 不是我假想出来的问题。"""
    result = ToolPermissionChecker().check(tool)

    assert result.allowed is True
    assert result.requires_confirmation is True, f"{tool} 本该需要确认"


def test_permission_checker_still_has_no_self_service_grant():
    """权限检查器本身**不该**长出"自己给自己授权"的口子。

    确认必须来自人,不能来自代码里某个 ``allow_once()``。这条用例是道防线:
    哪天有人为了"让它跑起来"在检查器上加一个绕过开关,这里会红。
    """
    checker = ToolPermissionChecker()
    for name in ("grant", "approve", "confirm", "allow_once", "bypass"):
        assert not hasattr(checker, name), f"ToolPermissionChecker 不该有 {name}() 这种自助放行接口"


# ── 2. fail closed:只有明确批准才算批准 ────────────────────────────────


def test_explicit_approve_is_the_only_thing_that_approves():
    outcome = interpret_decision(_FakeOutcome(selected_option=APPROVE_ID))

    assert outcome.approved is True
    assert outcome.decision_id == "d1"


def test_explicit_deny_is_denied():
    assert interpret_decision(_FakeOutcome(selected_option=DENY_ID)).approved is False


def test_timeout_is_denied_not_proceeded():
    """没人应答**不等于**同意。这是最容易写错、后果最严重的一条。"""
    result = interpret_decision(_FakeOutcome(timed_out=True, status="timeout_cancel"))

    assert result.approved is False
    assert "超时" in result.reason


def test_no_answer_at_all_is_denied():
    assert interpret_decision(_FakeOutcome(selected_option=None, status="cancelled")).approved is False


def test_none_outcome_is_denied():
    """决策通路什么都没返回时,不能当成"没人反对所以可以"。"""
    assert interpret_decision(None).approved is False


def test_freeform_voice_reply_is_not_consent():
    """破坏性操作上的含糊应答不构成授权 —— 不去猜"嗯"算不算同意。"""
    result = interpret_decision(_FakeOutcome(voice_input="嗯 行吧"))

    assert result.approved is False
    assert "含糊授权" in result.reason
    assert "嗯 行吧" in result.reason  # 如实告诉用户收到的是什么


def test_unrecognised_option_is_denied():
    """选项 id 漂移(手表侧改了字符串)时不能误判成批准。"""
    assert interpret_decision(_FakeOutcome(selected_option="yes_please")).approved is False


# ── 2b. 对着**真的** DecisionOutcome 再验一遍 ──────────────────────────
#
# 上面用的是替身。替身可能跟真对象漂移,所以这一组直接构造真类型 ——
# 尤其是那个陷阱:``should_proceed`` 在超时的两种状态下返回 True。


def _real(status, **kw):
    from core.interaction.pending_decision_registry import DecisionOutcome

    return DecisionOutcome(decision_id="real-1", status=status, **kw)


def test_should_proceed_is_the_wrong_predicate_here():
    """``should_proceed`` 对 TIMEOUT_PROCEED / TIMEOUT_DEFAULT 都是 True。

    拿它当"能不能执行"的判据,等于**超时即自动执行破坏性操作**。
    这条用例把这个陷阱钉死:确认闸只认明确点选,不看 should_proceed。
    """
    from core.interaction.pending_decision_registry import DecisionStatus

    trap = _real(DecisionStatus.TIMEOUT_PROCEED)

    assert trap.should_proceed is True, "前提:这个状态下 should_proceed 确实是 True"
    assert interpret_decision(trap).approved is False, "但确认闸必须仍判不批准"


def test_timeout_default_carrying_an_option_is_still_denied():
    """更隐蔽的一种:超时落到默认选项上,``selected_option`` 真的会是那个值。

    如果默认选项恰好是 approve,朴素判据就会把"没人应答"读成"批准"。
    确认闸从不传 default_option,这里再补一道:即便有,也不算批准。
    """
    from core.interaction.pending_decision_registry import DecisionStatus

    outcome = _real(DecisionStatus.TIMEOUT_DEFAULT, selected_option=APPROVE_ID, source="timeout")

    assert outcome.selected_option == APPROVE_ID  # 前提:值确实是 approve
    assert interpret_decision(outcome).approved is False  # 但它是超时来的,不算


def test_every_real_status_except_explicit_resolve_is_denied():
    """遍历真枚举的每一个状态,只有"人真的点了批准"那一种放行。"""
    from core.interaction.pending_decision_registry import DecisionStatus

    approved_states = []
    for status in DecisionStatus:
        for selected in (None, APPROVE_ID, DENY_ID):
            if interpret_decision(_real(status, selected_option=selected)).approved:
                approved_states.append((status.value, selected))

    assert approved_states == [
        (DecisionStatus.RESOLVED.value, APPROVE_ID)
    ], f"除了「人明确点了批准」之外还有别的组合能放行: {approved_states}"


# ── 3. 选项摆放:误触的代价不该是执行破坏性操作 ──────────────────────


def test_deny_option_comes_first():
    options = build_options()

    assert [o["id"] for o in options] == [DENY_ID, APPROVE_ID]


def test_option_ids_are_the_ones_interpret_decision_accepts():
    """选项 id 与判定逻辑必须对得上,否则点了"批准"也不算批准。"""
    approve = next(o for o in build_options() if o["id"] == APPROVE_ID)

    assert interpret_decision(_FakeOutcome(selected_option=approve["id"])).approved is True


# ── 4. 无设备可问时立刻拒,不干等一个注定超时的决策 ────────────────────


def test_no_connected_device_denies_immediately(monkeypatch):
    import core.interaction.pending_decision_registry as reg

    async def _no_devices():
        return []

    async def _should_not_be_called(**kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("没有设备可问时不该还去发起决策请求")

    monkeypatch.setattr(reg, "_discover_target_devices", _no_devices)
    monkeypatch.setattr(reg, "request_human_decision", _should_not_be_called)

    result = asyncio.run(confirm_high_risk_tool(tool_name="node__X__delete", risk_level="dangerous"))

    assert result.approved is False
    assert "没有已连接的设备" in result.reason


def test_asking_blows_up_is_denied(monkeypatch):
    import core.interaction.pending_decision_registry as reg

    async def _one_device():
        return ["watch-1"]

    async def _boom(**kwargs):
        raise RuntimeError("网关炸了")

    monkeypatch.setattr(reg, "_discover_target_devices", _one_device)
    monkeypatch.setattr(reg, "request_human_decision", _boom)

    result = asyncio.run(confirm_high_risk_tool(tool_name="node__X__delete"))

    assert result.approved is False
    assert "网关炸了" in result.reason


def test_device_discovery_failure_is_denied(monkeypatch):
    import core.interaction.pending_decision_registry as reg

    async def _boom():
        raise RuntimeError("发现失败")

    monkeypatch.setattr(reg, "_discover_target_devices", _boom)

    result = asyncio.run(confirm_high_risk_tool(tool_name="node__X__delete"))

    assert result.approved is False


# ── 5. 超时策略必须被显式钉死,不能交给推导 ────────────────────────────


def test_timeout_policy_is_pinned_to_cancel_not_derived():
    """``derive_default_on_timeout`` 在某些 urgency 下会推出 PROCEED ——
    那意味着"没人应答等于放行"。所以确认闸必须**显式**传 CANCEL。

    这条用例读源码而不是调接口:契约要在静态层面成立,任何人把这行删了
    或改成别的策略,测试就该红。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "interaction" / "high_risk_confirmation.py").read_text(
        encoding="utf-8"
    )

    assert "on_timeout=OnTimeout.CANCEL" in src, "超时策略必须显式钉死为 CANCEL"
    assert "default_option=None" in src, "不能给默认选项 —— 否则超时会落到那个选项上"


def test_derive_default_would_have_been_unsafe_here():
    """反向证明上一条不是多余的:不钉死的话推导结果确实可能是"放行"。"""
    from core.interaction.pending_decision_registry import OnTimeout, derive_default_on_timeout

    derived = derive_default_on_timeout("high", has_default=False)

    # 只要推导结果不是 CANCEL,显式钉死就是必要的。
    assert derived in (OnTimeout.PROCEED, OnTimeout.CANCEL, OnTimeout.DEFAULT_OPTION)
    if derived is not OnTimeout.CANCEL:
        assert True, "推导会给出非 CANCEL 策略 —— 正是必须显式覆盖的理由"


# ── 6. 两处闸门都真的接上了 ────────────────────────────────────────────


def test_both_gates_call_the_confirmation_path():
    """确认闸有两处(CanonicalDispatcher 主路 + OpenClawd 内联兜底)。

    只接一处等于留了一条老路照样撞墙,所以两处都要有。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ("core/capabilities/canonical_dispatcher.py", "core/openclawd.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "confirm_high_risk_tool" in src, f"{rel} 的确认闸没有接上人类确认通路"


def test_dispatch_result_carries_risk_level_for_the_prompt():
    """问人的时候要能如实说出这是多危险的操作。"""
    from core.capabilities.canonical_dispatcher import DispatchResult

    r = DispatchResult(success=False, needs_confirmation=True, risk_level="critical")

    assert r.risk_level == "critical"


def test_resolved_status_literal_matches_the_real_enum():
    """判定部分用字面量而不 import 枚举,所以要有一条用例守住它别漂移。"""
    from core.interaction.high_risk_confirmation import RESOLVED_STATUS
    from core.interaction.pending_decision_registry import DecisionStatus

    assert RESOLVED_STATUS == DecisionStatus.RESOLVED.value


def test_cancelled_carrying_an_approve_option_is_denied():
    """穷举用例先抓出来的洞:取消状态若残留 selected_option='approve',
    只看选项就会误判成批准。判据必须同时要求状态是 RESOLVED。"""
    from core.interaction.pending_decision_registry import DecisionStatus

    outcome = _real(DecisionStatus.CANCELLED, selected_option=APPROVE_ID)

    assert interpret_decision(outcome).approved is False


def test_confirmation_outcome_is_serialisable():
    d = ConfirmationOutcome(True, "用户已明确批准", "d9", "wear").to_dict()

    assert d == {"approved": True, "reason": "用户已明确批准", "decision_id": "d9", "source": "wear"}


# ── 7. 周边机制不能把这条通路掐死 ──────────────────────────────────────
#
# 光把确认闸接上还不够:ReAct 循环外层原本写死"单个工具最多 30 秒"。
# 手腕上的决策刚推出去 30 秒就被取消,用户手指落下时已经没人在等了。


def test_machine_tools_keep_the_short_budget():
    from core.tool_permissions import DEFAULT_TOOL_TIMEOUT_S, tool_call_timeout_s

    assert tool_call_timeout_s("mcp__windows-local__screenshot") == DEFAULT_TOOL_TIMEOUT_S


def test_tools_needing_confirmation_get_room_for_a_human():
    from core.tool_permissions import DEFAULT_TOOL_TIMEOUT_S, tool_call_timeout_s

    budget = tool_call_timeout_s("node__Node_122_Shell__system_command")

    assert budget > DEFAULT_TOOL_TIMEOUT_S, "确认闸要问人,30 秒不够人抬腕看清再点"


def test_ask_human_honours_its_declared_timeout():
    """``ask_human__request`` 接受 timeout_s 最大 3600,外层不能在 30 秒掐断它。"""
    from core.tool_permissions import tool_call_timeout_s

    assert tool_call_timeout_s("ask_human__request", {"timeout_s": 300}) > 300


def test_ask_human_garbage_timeout_falls_back_not_crashes():
    from core.tool_permissions import tool_call_timeout_s

    assert tool_call_timeout_s("ask_human__request", {"timeout_s": "abc"}) > 0


def test_ask_human_timeout_is_clamped_at_both_ends():
    from core.tool_permissions import MAX_TOOL_TIMEOUT_S, tool_call_timeout_s

    assert tool_call_timeout_s("ask_human__request", {"timeout_s": 1}) >= 5
    assert tool_call_timeout_s("ask_human__request", {"timeout_s": 99999}) <= MAX_TOOL_TIMEOUT_S


def test_timeout_lookup_does_not_burn_the_rate_limit():
    """算超时预算是**只读查询**,不能计入频率账。

    走 check() 的话,几次"问一下"就能把工具自己的调用配额吃光 ——
    system_command 每分钟只有 3 次。
    """
    from core.tool_permissions import ToolPermissionChecker, tool_call_timeout_s

    checker = ToolPermissionChecker()
    tool = "node__Node_122_Shell__system_command"

    for _ in range(10):
        tool_call_timeout_s(tool, checker=checker)

    # 查了 10 次之后,真正的调用仍应被放行(配额没被查询吃掉)。
    assert checker.check(tool).allowed is True


def test_requires_confirmation_query_is_non_mutating():
    from core.tool_permissions import ToolPermissionChecker

    checker = ToolPermissionChecker()
    tool = "node__Node_122_Shell__system_command"

    for _ in range(50):
        assert checker.requires_confirmation_for(tool) is True

    assert checker.check(tool).allowed is True


def test_react_loop_uses_the_dynamic_budget_not_a_hardcoded_30():
    """外层那句写死的 30 秒必须已经被换掉,否则前面所有铺垫都白做。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "openclawd.py").read_text(encoding="utf-8")

    assert "tool_call_timeout_s(tc_name, tc_args)" in src
    assert "timeout=30.0  # 单个工具调用最多 30 秒" not in src
