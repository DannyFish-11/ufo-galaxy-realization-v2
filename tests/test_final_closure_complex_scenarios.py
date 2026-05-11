"""tests/test_final_closure_complex_scenarios.py
=================================================
基于双仓真实代码全景审查后的最终复杂场景回归测试集。

本测试文件在完整审查 V2 真实代码（closed_loop_governance_consolidation.py、
unified_execution_governance.py、canonical_completion_ingress.py 等核心模块）后，
针对以下此前未被覆盖的真实残留场景补充回归保护：

已确认已有约束（无需重复）：
  - mature closure 需要 center_lifecycle 终态权威  ✓ (test_pr18_system_completion_readiness.py)
  - partial uplink（单侧缺失）不能成熟闭环        ✓ (test_pr18_system_completion_readiness.py)
  - conflicting result+state 不能成熟闭环          ✓ (test_pr18_system_completion_readiness.py)
  - recovered/degraded runtime 不能成熟闭环        ✓ (test_pr18_system_completion_readiness.py)

本文件新增覆盖的真实残留场景：
  Group A — 闭环阶段与成熟度判定（advanced reconciliation scenarios）
    A01. uplink-only terminal（无 center lifecycle）→ 不能成熟闭环
    A02. delayed conflict center truth retained → 不能成熟闭环
    A03. in-progress terminal observation held → 不能成熟闭环
    A04. timeout 终态 + 双侧 uplink → 确实能成熟闭环（verifiably closed failure）
    A05. 完全无记录 → unknown 阶段，不闭环
    A06. 单源终态 uplink（需 reconciliation）→ 不能成熟闭环
    A07. 冲突终态 uplink 无 lifecycle authority → 不能成熟闭环

  Group B — CanonicalCompletionIngress 修复验证
    B01. 重复注册同 handoff_id 不孤儿（新 Future 存活，旧 Future 被取消）
    B02. 重复注册同 task_id 不孤儿（新 Future 存活，旧 Future 被取消）
    B03. is_terminal=False 的 notify 不解析 Future
    B04. is_terminal 属性缺失的 notify 仍能解析 Future
    B05. is_terminal 属性抛出非 AttributeError 异常 → notify 返回 False 不解析
    B06. 新策略 sentinel 可导入且非空

合同版本：final_closure_complex_scenarios::v1.0.0
"""
from __future__ import annotations

import asyncio
import time
import types

import pytest

from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    _clear_execution_governance_runtime_state,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)
from core.closed_loop_governance_consolidation import (
    ClosedLoopStage,
    query_closed_loop_governance_state,
)


# ---------------------------------------------------------------------------
# Shared reset fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_gov():
    _clear_execution_governance_runtime_state()
    yield
    _clear_execution_governance_runtime_state()


# ===========================================================================
# Group A — 闭环阶段与成熟度判定（advanced reconciliation scenarios）
# ===========================================================================


class TestGroupA_AdvancedReconciliationScenarios:
    """验证各类复杂 reconciliation 场景均正确阻止 system_completion_ready=True。"""

    def test_A01_uplink_only_terminal_not_mature(self):
        """A01: 无 center lifecycle，双侧 uplink 均报告 terminal → 不能成熟闭环。

        reconciliation_status 应为 uplink_only_terminal_observation，
        terminal_truth_authoritative_source 应为 reported_uplink（非 center_lifecycle），
        system_completion_ready 应为 False。
        """
        eid = "A01-exec-uplink-only-terminal"
        did = "A01-device"

        # 注意：不调用 record_execution_lifecycle_event，
        # 模拟 center lifecycle 尚未记录任何终态事件的情况。
        # 双侧 uplink 均报告 succeeded。
        record_result_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "succeeded"},
        )
        record_state_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "succeeded"},
        )

        view = query_closed_loop_governance_state(eid, did)
        # center lifecycle 未达到终态 → stage 应为 reconciliation（uplink_only_terminal_observation）
        assert view.stage == ClosedLoopStage.reconciliation
        assert view.system_completion_ready is False
        assert "center_lifecycle_authority_missing" in view.system_completion_gap_types
        assert "reconciliation_not_fully_accepted" in view.system_completion_gap_types

    def test_A02_delayed_conflict_center_truth_retained_not_mature(self):
        """A02: center lifecycle 先达到终态，随后收到冲突的 delayed uplink → 不能成熟闭环。

        center lifecycle 报告 succeeded，但 result_uplink 报告 failed（模拟延迟上报冲突）。
        reconciliation_status 应为 conflict_center_truth_retained 或
        delayed_conflict_center_truth_retained，system_completion_ready 应为 False。
        """
        eid = "A02-exec-delayed-conflict"
        did = "A02-device"

        record_execution_lifecycle_event(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )
        # result uplink 报告 failed（与 center lifecycle 的 succeeded 冲突）
        record_result_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "failed"},
        )
        record_state_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "succeeded"},
        )

        view = query_closed_loop_governance_state(eid, did)
        assert view.system_completion_ready is False
        gap_types = set(view.system_completion_gap_types)
        # 冲突场景应有 reconciliation_conflict_present 和/或 reconciliation_not_fully_accepted
        assert "reconciliation_conflict_present" in gap_types or \
               "reconciliation_not_fully_accepted" in gap_types, \
               f"Expected conflict/not-fully-accepted gap, got: {gap_types}"

    def test_A03_in_progress_terminal_observation_held_not_mature(self):
        """A03: lifecycle 仍在 running，但 uplink 已报告 terminal → 不能成熟闭环。

        reconciliation_status 应为 terminal_observation_held_for_lifecycle_authority，
        system_completion_ready 应为 False（center lifecycle 尚未终态）。
        """
        eid = "A03-exec-in-progress-terminal-held"
        did = "A03-device"

        # lifecycle 尚未终态（admitted 阶段）
        record_execution_lifecycle_event(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
            enforce_transition=False,
        )
        # 但 result uplink 已报告 succeeded
        record_result_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "succeeded"},
        )
        record_state_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "succeeded"},
        )

        view = query_closed_loop_governance_state(eid, did)
        # lifecycle 未终态 → 不能成熟闭环
        assert view.system_completion_ready is False
        # stage 应为 reconciliation（terminal observation held）
        assert view.stage in {ClosedLoopStage.reconciliation, ClosedLoopStage.observation}

    def test_A04_timeout_terminal_with_full_uplink_is_mature(self):
        """A04: 执行超时（timed_out），双侧 uplink 均对应 → 应能成熟闭环。

        失败性终态（timed_out）只要有 center lifecycle authority 且双侧 uplink
        与其一致，system_completion_ready 应为 True（verifiably closed failure）。
        """
        eid = "A04-exec-timeout-mature"
        did = "A04-device"

        record_execution_lifecycle_event(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.timed_out,
            enforce_transition=False,
        )
        record_result_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "timeout"},
        )
        record_state_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "timed_out"},
        )

        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.system_completion_ready is True
        assert view.system_completion_level == "mature_closed_loop"
        assert view.system_completion_gap_types == []

    def test_A05_empty_execution_not_closed(self):
        """A05: 完全无记录 → unknown 阶段，system_completion_ready = False。"""
        eid = "A05-exec-empty"
        did = "A05-device"

        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.unknown
        assert view.system_completion_ready is False
        assert "loop_not_in_completion_stage" in view.system_completion_gap_types

    def test_A06_single_source_uplink_terminal_requires_reconciliation(self):
        """A06: 仅 result uplink 报告 terminal，state uplink 无终态 → 需 reconciliation。

        reconciliation_status 应为 uplink_terminal_observation_requires_reconciliation，
        system_completion_ready 应为 False（单源 terminal，无 cross-uplink 确认）。
        """
        eid = "A06-exec-single-source-terminal"
        did = "A06-device"

        # 只有 result uplink 报告 terminal，state uplink 无 terminal 内容
        record_result_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "succeeded"},
        )
        # state uplink 只报告 running（非 terminal）
        record_state_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "running"},
        )

        view = query_closed_loop_governance_state(eid, did)
        assert view.system_completion_ready is False
        # 应处于 reconciliation 阶段或 observation 阶段（不是 completion）
        assert view.stage != ClosedLoopStage.completion

    def test_A07_conflicting_uplink_terminals_no_lifecycle_not_mature(self):
        """A07: result 和 state uplink 报告冲突终态，且无 lifecycle authority → 不能成熟闭环。

        例如 result 报告 succeeded，state 报告 cancelled（非 success/failure 对）→
        conflicting_terminal_unresolved，system_completion_ready 应为 False。
        """
        eid = "A07-exec-conflict-uplink-no-lifecycle"
        did = "A07-device"

        record_result_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "succeeded"},
        )
        record_state_uplink(
            execution_id=eid,
            device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"phase": "cancelled"},
        )

        view = query_closed_loop_governance_state(eid, did)
        assert view.system_completion_ready is False
        # center lifecycle 不存在 → center_lifecycle_authority_missing
        assert "center_lifecycle_authority_missing" in view.system_completion_gap_types


# ===========================================================================
# Group B — CanonicalCompletionIngress 修复验证
# ===========================================================================


class TestGroupB_CanonicalCompletionIngressFixes:
    """验证 canonical_completion_ingress.py 中修复的两个问题：
    1. 重复注册同一 handoff_id 不再孤儿 Future（新 future 替换旧 future 并取消旧的）。
    2. is_terminal 属性异常处理区分 AttributeError 与其他 Exception。
    """

    def _make_ingress(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress
        return CanonicalCompletionIngress()

    def _run_sync(self, coro):
        """在新 event loop 中同步运行协程。"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_B01_duplicate_handoff_id_cancels_first_future(self):
        """B01: 同一 handoff_id 注册两次 → 第一个 Future 被取消，第二个保持 pending。"""
        ingress = self._make_ingress()

        async def _do():
            loop = asyncio.get_running_loop()
            fut1 = ingress.register_pending_dispatch("hid-dup", task_id=None)
            fut2 = ingress.register_pending_dispatch("hid-dup", task_id=None)

            # 给 cancellation 一点调度时间
            await asyncio.sleep(0)

            assert fut1.cancelled(), "First Future should have been cancelled on re-registration"
            assert not fut2.done(), "Second Future should still be pending"
            return True

        result = self._run_sync(_do())
        assert result is True

    def test_B02_duplicate_task_id_cancels_first_future(self):
        """B02: 同一 task_id 注册两次 → 第一个 Future 被取消，第二个保持 pending。"""
        ingress = self._make_ingress()

        async def _do():
            fut1 = ingress.register_pending_dispatch(handoff_id="", task_id="tid-dup")
            fut2 = ingress.register_pending_dispatch(handoff_id="", task_id="tid-dup")

            await asyncio.sleep(0)

            assert fut1.cancelled(), "First task_id Future should have been cancelled"
            assert not fut2.done(), "Second task_id Future should still be pending"
            return True

        result = self._run_sync(_do())
        assert result is True

    def test_B03_notify_non_terminal_does_not_resolve(self):
        """B03: is_terminal=False 的 envelope → notify() 返回 False，Future 不被解析。"""
        ingress = self._make_ingress()

        async def _do():
            fut = ingress.register_pending_dispatch("hid-nonterminal", task_id=None)

            envelope = types.SimpleNamespace(
                is_terminal=False,
                handoff_id="hid-nonterminal",
                task_id="",
                response_kind="ack",
            )
            result = ingress.notify(envelope)
            assert result is False
            assert not fut.done(), "Non-terminal notify should not resolve Future"
            return True

        result = self._run_sync(_do())
        assert result is True

    def test_B04_notify_missing_is_terminal_attribute_resolves(self):
        """B04: envelope 缺少 is_terminal 属性（AttributeError）→ 视为 terminal，Future 被解析。

        原有设计意图：AttributeError 时视为 terminal。本修复保留此语义。
        """
        ingress = self._make_ingress()

        async def _do():
            fut = ingress.register_pending_dispatch("hid-no-attr", task_id=None)

            # 不包含 is_terminal 属性
            envelope = types.SimpleNamespace(
                handoff_id="hid-no-attr",
                task_id="",
                response_kind="result",
            )
            result = ingress.notify(envelope)
            assert result is True, "Missing is_terminal attr should be treated as terminal"
            assert fut.done(), "Future should be resolved when is_terminal attr is absent"
            return True

        result = self._run_sync(_do())
        assert result is True

    def test_B05_notify_broken_is_terminal_property_returns_false(self):
        """B05: is_terminal 抛出非 AttributeError 异常 → notify() 返回 False，不解析 Future。

        修复前：任何异常均 pass 并继续解析。
        修复后：非 AttributeError 异常视为 non-terminal，返回 False。
        """
        ingress = self._make_ingress()

        class BrokenEnvelope:
            handoff_id = "hid-broken"
            task_id = ""
            response_kind = "result"

            @property
            def is_terminal(self):
                raise RuntimeError("simulated broken property")

        async def _do():
            fut = ingress.register_pending_dispatch("hid-broken", task_id=None)

            result = ingress.notify(BrokenEnvelope())
            # 修复后：RuntimeError → 非 terminal → returns False
            assert result is False, "Broken is_terminal property should return False"
            assert not fut.done(), "Future should NOT be resolved on broken is_terminal"
            return True

        result = self._run_sync(_do())
        assert result is True

    def test_B06_new_policy_sentinels_importable(self):
        """B06: 新增策略 sentinel 可导入且非空。"""
        from core.canonical_completion_ingress import (
            DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY,
            IS_TERMINAL_ATTRIBUTE_ERROR_POLICY,
        )
        assert DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY
        assert "DUPLICATE_REGISTRATION_CANCELS_ORPHAN" in DUPLICATE_REGISTRATION_CANCELS_ORPHAN_POLICY
        assert IS_TERMINAL_ATTRIBUTE_ERROR_POLICY
        assert "IS_TERMINAL_ATTRIBUTE_ERROR" in IS_TERMINAL_ATTRIBUTE_ERROR_POLICY
