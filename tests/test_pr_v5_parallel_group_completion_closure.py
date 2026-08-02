"""tests/test_pr_v5_parallel_group_completion_closure.py
=========================================================
PR-V5-CONVERGE：并行组的终态必须由 V5 规范闭合权威判定，
而不是由 ``flow_aware_result_convergence`` 自己数个数。

修的是什么
----------
``core/unified_orchestration_spine.py``（V4，**活模块**，由
``galaxy_gateway/android/handlers/goal_execution.py`` 真实调用）自己的哨兵
``ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY`` 把规则写死了：

    所有高级执行模式（并行扇出、委派、接管、唤醒路由、跨设备、混合）**MUST**
    通过调用 ``core.canonical_group_completion_closure.apply_completion_closure()``
    决定其规范终态。**任何模式不得**维护私有完成契约、**不得把子任务成功当作组
    完成**、不得在规范闭合之外发出终态。

而全仓**没有任何一处**真正 import 过 ``apply_completion_closure``。与此同时，
``core/flow_aware_result_convergence.py``（活模块，被 flow_level_operator_surface /
delegated_flow_acceptance_gate / delegated_flow_readiness_gate 等多处使用）
维护了一份**私有完成契约** —— 正是那条哨兵明令禁止的东西：

    # core/flow_aware_result_convergence.py:1159
    and record.absorbed_count >= record.expected_count
    and not record.all_complete
    ):
        record.all_complete = True
        ...  group_complete=True

它**只数「结果到齐了几个」，完全不看这些结果是成功还是失败**。
``ParallelFlowAggregationRecord`` 里也没有任何失败计数字段。

具体后果
--------
并行扇出到三台设备，两台失败一台成功 —— 只要三份结果都回来了，父流程就被标成
``group_complete=True`` 并发出 ``parent_flow_aggregate``。**上游看到的是"组完成"，
不是"部分失败"。** 被阻塞（非就绪）的设备槽位也完全不参与判定。

V5 恰恰为此而写：``CanonicalTerminalKind`` 有 ``partial_failure`` /
``partial_success`` / ``degraded_success`` / ``aggregate_failure`` 这套词汇，
``CompletionContract`` 有 ``partial_failure_policy`` 与 ``blocked_device_exclusion``
三档策略。

本文件的组织
------------
- ``TestLiveConvergenceLosesFailureSemantics`` —— **红→绿的主体**。接入前，
  "两失败一成功"会被判成完成且不带任何失败信号。
- ``TestV5AuthorityItselfIsCorrect`` —— 独立验证 V5 权威本身的判定是对的
  （即"该用的东西没坏"，避免接一个本身有问题的权威）。
- ``TestConvergenceDelegatesToV5`` —— 断言接线本身：收敛路径确实调用了权威，
  而不是自己又算了一遍。
"""

from __future__ import annotations

import time
from typing import Any, List

import pytest

try:
    from core.canonical_group_completion_closure import (
        CanonicalTerminalKind,
        CompletionClosureContext,
        DeviceResultSignal,
        SignalKind,
        apply_completion_closure,
    )

    _V5_AVAILABLE = True
except ImportError:  # pragma: no cover
    _V5_AVAILABLE = False

try:
    from core.unified_orchestration_spine import CompletionContract

    _CONTRACT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CONTRACT_AVAILABLE = False

try:
    from core.flow_aware_result_convergence import (
        FlowAwareConvergenceCoordinator,
        ResultConvergenceContext,
    )

    _CONVERGENCE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CONVERGENCE_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not (_V5_AVAILABLE and _CONTRACT_AVAILABLE and _CONVERGENCE_AVAILABLE),
    reason="V5 closure / CompletionContract / convergence coordinator unavailable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GROUP = "grp-v5-repro"
_PARENT = "flow-parent-v5"


def _subtask_ctx(index: int, *, success: bool, device_id: str) -> Any:
    """构造一条并行子任务结果。失败态写进 result_payload —— 这正是活路径忽略的地方。"""
    return ResultConvergenceContext(
        flow_id=f"{_PARENT}::sub{index}",
        result_id=f"res-{index}",
        semantic_kind="subtask_result",
        lineage="subtask_of_group",
        group_id=_GROUP,
        subtask_index=index,
        parent_flow_id=_PARENT,
        result_payload={"status": "success" if success else "failed", "ok": success},
        device_id=device_id,
        task_id=f"task-{index}",
    )


def _absorb_two_failures_one_success(coord: Any) -> Any:
    """三台设备并行：dev-a 成功，dev-b / dev-c 失败。返回**聚合** artifact。

    注意取的是 ``get_parallel_group(gid).aggregate_artifact``，不是 ``absorb()``
    的返回值 —— 后者是**子任务** artifact。第一版就取错了：触发收口的那一份子任务
    artifact 上也带着 ``group_complete=True``（既有行为），于是断言落在了它身上，
    看起来像代码没生效，实际是用例找错了对象。
    """
    coord.register_parallel_group(_GROUP, _PARENT, expected_count=3)
    for i, (dev, ok) in enumerate([("dev-a", True), ("dev-b", False), ("dev-c", False)]):
        coord.absorb(_subtask_ctx(i, success=ok, device_id=dev))
    record = coord.get_parallel_group(_GROUP)
    assert record is not None and record.aggregate_artifact is not None, "前提：三份到齐后产出了聚合 artifact"
    return record.aggregate_artifact


def _v5_outcome_for_two_failures_one_success() -> Any:
    """同一场景交给 V5 权威判定。"""
    now = time.time()
    signals = [
        DeviceResultSignal(
            device_id=dev,
            signal_kind=SignalKind.subtask_result.value,
            is_success=ok,
            result_payload={"status": "success" if ok else "failed"},
            received_at=now,
            signal_id=f"sig-{dev}",
        )
        for dev, ok in [("dev-a", True), ("dev-b", False), ("dev-c", False)]
    ]
    ctx = CompletionClosureContext(
        orchestration_id="orch-v5-repro",
        execution_mode="parallel_fanout",
        signals=signals,
        expected_device_ids=["dev-a", "dev-b", "dev-c"],
        started_at=now,
        group_id=_GROUP,
    )
    return apply_completion_closure(ctx, CompletionContract(expected_result_count=3))


# ---------------------------------------------------------------------------
# 1 — V5 权威本身判定正确（先证明"要用的东西没坏"）
# ---------------------------------------------------------------------------


class TestV5AuthorityItselfIsCorrect:
    def test_two_failures_one_success_is_not_plain_complete(self) -> None:
        outcome = _v5_outcome_for_two_failures_one_success()
        assert outcome.terminal_kind != CanonicalTerminalKind.complete.value, (
            "三台里两台失败，规范终态不该是 'complete'；" f"实际={outcome.terminal_kind!r}"
        )

    def test_failure_count_is_recorded(self) -> None:
        outcome = _v5_outcome_for_two_failures_one_success()
        assert outcome.failure_count == 2, f"失败数应为 2，实际 {outcome.failure_count}"
        assert outcome.success_count == 1, f"成功数应为 1，实际 {outcome.success_count}"

    def test_all_success_is_complete(self) -> None:
        """反向用例：全成功时必须判成 complete —— 防止为了抓失败把正常路径也判坏。"""
        now = time.time()
        signals = [
            DeviceResultSignal(
                device_id=d,
                signal_kind=SignalKind.subtask_result.value,
                is_success=True,
                result_payload={"status": "success"},
                received_at=now,
                signal_id=f"sig-{d}",
            )
            for d in ("dev-a", "dev-b", "dev-c")
        ]
        ctx = CompletionClosureContext(
            orchestration_id="orch-all-ok",
            execution_mode="parallel_fanout",
            signals=signals,
            expected_device_ids=["dev-a", "dev-b", "dev-c"],
            started_at=now,
            group_id="grp-all-ok",
        )
        outcome = apply_completion_closure(ctx, CompletionContract(expected_result_count=3))
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value
        assert outcome.failure_count == 0


# ---------------------------------------------------------------------------
# 2 — 活路径丢失失败语义（红 → 绿的主体）
# ---------------------------------------------------------------------------


class TestLiveConvergenceLosesFailureSemantics:
    """接入前这些会红：活路径把"两失败一成功"报成组完成。"""

    def test_aggregate_artifact_must_not_claim_plain_group_complete(self) -> None:
        coord = FlowAwareConvergenceCoordinator()
        agg = _absorb_two_failures_one_success(coord)
        kind = getattr(agg, "canonical_terminal_kind", None)
        assert kind is not None, (
            "聚合 artifact 必须携带 V5 规范终态（canonical_terminal_kind）—— "
            "当前只有一个布尔 group_complete，无法表达部分失败"
        )
        assert (
            kind != CanonicalTerminalKind.complete.value
        ), f"三台里两台失败，不得报成 'complete'；实际 canonical_terminal_kind={kind!r}"

    def test_failure_counts_must_survive_aggregation(self) -> None:
        coord = FlowAwareConvergenceCoordinator()
        agg = _absorb_two_failures_one_success(coord)
        evidence = getattr(agg, "evidence", {}) or {}
        assert evidence.get("failure_count") == 2, (
            "聚合证据必须保留失败计数 —— 否则上游无从得知这组是部分失败；" f"实际 evidence={evidence!r}"
        )
        assert evidence.get("success_count") == 1

    def test_all_success_group_still_reports_complete(self) -> None:
        """反向用例：全成功的组不能被误判成失败。"""
        coord = FlowAwareConvergenceCoordinator()
        coord.register_parallel_group("grp-ok", "flow-ok", expected_count=2)
        for i in range(2):
            coord.absorb(
                ResultConvergenceContext(
                    flow_id=f"flow-ok::sub{i}",
                    result_id=f"ok-{i}",
                    semantic_kind="subtask_result",
                    lineage="subtask_of_group",
                    group_id="grp-ok",
                    subtask_index=i,
                    parent_flow_id="flow-ok",
                    result_payload={"status": "success"},
                    device_id=f"dev-{i}",
                    task_id=f"t{i}",
                )
            )
        agg = coord.get_parallel_group("grp-ok").aggregate_artifact
        assert agg is not None
        assert agg.canonical_terminal_kind == CanonicalTerminalKind.complete.value


# ---------------------------------------------------------------------------
# 3 — 接线本身：不能各算各的
# ---------------------------------------------------------------------------


class TestConvergenceDelegatesToV5:
    """「一体化」的实质要求：收敛路径**委托**给权威，而不是自己再实现一份。"""

    def test_apply_completion_closure_is_actually_called(self, monkeypatch) -> None:
        calls: List[Any] = []
        import core.canonical_group_completion_closure as v5

        real = v5.apply_completion_closure

        def _spy(ctx: Any, contract: Any) -> Any:
            calls.append((ctx, contract))
            return real(ctx, contract)

        monkeypatch.setattr(v5, "apply_completion_closure", _spy)

        coord = FlowAwareConvergenceCoordinator()
        _absorb_two_failures_one_success(coord)
        assert calls, "并行组收口时必须调用 V5 apply_completion_closure()，不得私自判定终态"

    def test_closure_context_carries_every_participating_device(self) -> None:
        """交给权威的上下文必须是完整的 —— 少传设备等于让权威在残缺输入上判定。"""
        calls: List[Any] = []
        import core.canonical_group_completion_closure as v5

        real = v5.apply_completion_closure
        try:
            v5.apply_completion_closure = lambda ctx, contract: (  # type: ignore[assignment]
                calls.append(ctx) or real(ctx, contract)
            )
            coord = FlowAwareConvergenceCoordinator()
            _absorb_two_failures_one_success(coord)
        finally:
            v5.apply_completion_closure = real  # type: ignore[assignment]

        assert calls, "前提：权威被调用过"
        ctx = calls[-1]
        assert len(ctx.signals) == 3, f"三台设备的信号都要交给权威，实际 {len(ctx.signals)}"
        assert sorted(s.device_id for s in ctx.signals) == ["dev-a", "dev-b", "dev-c"]

    def test_no_private_completion_contract_remains(self) -> None:
        """哨兵原文：任何模式不得维护私有完成契约。

        这里用可机器判定的形式表达：``all_complete`` 不再是**唯一**的终态来源，
        聚合 artifact 必须带上权威给出的 canonical_terminal_kind。
        """
        coord = FlowAwareConvergenceCoordinator()
        agg = _absorb_two_failures_one_success(coord)
        assert hasattr(agg, "canonical_terminal_kind"), (
            "ResultConvergenceArtifact 必须承载规范终态字段，" "否则私有布尔 group_complete 仍是事实上的完成契约"
        )
