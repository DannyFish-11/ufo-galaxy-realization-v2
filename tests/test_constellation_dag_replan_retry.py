"""tests/test_constellation_dag_replan_retry.py
==================================================
回归防护:ConstellationRuntime._execute_layers 的 DAG 演化 replan 必须【真正重跑】
被 evolver 重置为 PENDING 的任务(此前前向单遍层扫描永不回头,replan 形同虚设)。

用一个注入的假 orchestrator(某任务首次失败、重试成功)直接驱动 _execute_layers,
断言:失败任务经重试终成 SUCCESS、依赖它的下游不再被误跳过、末态计数如实、
超出重试预算的任务如实落 FAILED、evolver 重试预算按编排重置。
全部注入替身,不触网、不加载真实模型。
"""

from __future__ import annotations

import asyncio

from core.constellation_runtime import ConstellationRuntime
from core.schemas.orchestration import (
    OrchestrationRequest,
    OrchestrationStatus,
    SubTask,
    SubTaskStatus,
    TaskDecomposition,
)


def _sub(name, task_id, depends_on=None):
    return SubTask(task_id=task_id, name=name, depends_on=depends_on or [], status=SubTaskStatus.PENDING)


class _FakeOrchestrator:
    """按 task_id → 剩余失败次数 表决定每次执行成败;记录执行次数。"""

    def __init__(self, fail_plan):
        self.fail_plan = dict(fail_plan)  # task_id -> 还要失败几次
        self.runs = {}  # task_id -> 执行次数

    async def _execute_subtask(self, task, orch_request):
        self.runs[task.task_id] = self.runs.get(task.task_id, 0) + 1
        remaining = self.fail_plan.get(task.task_id, 0)
        if remaining > 0:
            self.fail_plan[task.task_id] = remaining - 1
            task.status = SubTaskStatus.FAILED
            task.error = f"fail#{self.runs[task.task_id]}"
            return {"ok": False}
        task.status = SubTaskStatus.SUCCESS
        task.error = ""
        return {"ok": True}


async def _run(runtime, orchestrator, subtasks):
    decomposition = TaskDecomposition(goal="g", subtasks=list(subtasks))
    req = OrchestrationRequest(request_id="r1", task_description="t")
    return await runtime._execute_layers(
        layers=[],  # 新实现按就绪度自行调度,忽略预算层
        task_map={},
        decomposition=decomposition,
        orch_request=req,
        orchestrator=orchestrator,
        trace_id="tr",
        request_id="r1",
        ledger=None,
    )


def test_failed_task_is_retried_and_succeeds():
    rt = ConstellationRuntime(enable_dag_evolution=True, max_replan_attempts=3)
    # A 首次失败一次后成功;B 依赖 A
    a = _sub("A", "ta")
    b = _sub("B", "tb", depends_on=["ta"])
    orch = _FakeOrchestrator(fail_plan={"ta": 1})
    res = asyncio.run(_run(rt, orch, [a, b]))
    assert a.status == SubTaskStatus.SUCCESS  # 重试后成功,不是 pending/skipped
    assert b.status == SubTaskStatus.SUCCESS  # 下游不再被误跳过
    assert orch.runs["ta"] == 2  # 确实重跑了一次
    assert orch.runs["tb"] == 1
    assert res.status == OrchestrationStatus.SUCCESS
    assert res.completed_subtasks == 2 and res.failed_subtasks == 0


def test_downstream_runs_only_after_upstream_recovers():
    rt = ConstellationRuntime(enable_dag_evolution=True, max_replan_attempts=3)
    a = _sub("A", "ta")
    b = _sub("B", "tb", depends_on=["ta"])
    c = _sub("C", "tc", depends_on=["tb"])
    orch = _FakeOrchestrator(fail_plan={"tb": 2})  # 中游失败两次后成功
    res = asyncio.run(_run(rt, orch, [a, b, c]))
    assert (a.status, b.status, c.status) == (
        SubTaskStatus.SUCCESS,
        SubTaskStatus.SUCCESS,
        SubTaskStatus.SUCCESS,
    )
    assert orch.runs["tb"] == 3  # 失败2次+成功1次
    assert orch.runs["tc"] == 1  # C 只在 B 最终成功后跑一次
    assert res.status == OrchestrationStatus.SUCCESS


def test_exhausted_retries_marks_failed_and_skips_dependents():
    rt = ConstellationRuntime(enable_dag_evolution=True, max_replan_attempts=2)
    a = _sub("A", "ta")
    b = _sub("B", "tb", depends_on=["ta"])
    orch = _FakeOrchestrator(fail_plan={"ta": 99})  # 永远失败
    res = asyncio.run(_run(rt, orch, [a, b]))
    assert a.status == SubTaskStatus.FAILED  # 耗尽重试 → 终态 FAILED(非 pending)
    assert b.status in (SubTaskStatus.FAILED, SubTaskStatus.SKIPPED)  # 下游如实未跑
    assert b.status != SubTaskStatus.PENDING  # 绝不留"假 pending"
    # A 执行次数 = 1(首次) + max_replan_attempts(2 次重试) = 3
    assert orch.runs["ta"] == 3
    assert res.status == OrchestrationStatus.FAILED
    assert res.completed_subtasks == 0


def test_no_evolution_when_disabled_still_terminates():
    rt = ConstellationRuntime(enable_dag_evolution=False, max_replan_attempts=3)
    a = _sub("A", "ta")
    orch = _FakeOrchestrator(fail_plan={"ta": 1})  # 失败一次
    res = asyncio.run(_run(rt, orch, [a]))
    # 无 evolver → 不重试,A 一次失败即终态 FAILED,循环收敛不挂死
    assert a.status == SubTaskStatus.FAILED
    assert orch.runs["ta"] == 1
    assert res.status == OrchestrationStatus.FAILED


def test_evolver_retry_budget_reset_between_orchestrations():
    rt = ConstellationRuntime(enable_dag_evolution=True, max_replan_attempts=2)
    # 第一次编排:A 永远失败,耗尽预算
    a1 = _sub("A", "ta")
    asyncio.run(_run(rt, _FakeOrchestrator(fail_plan={"ta": 99}), [a1]))
    # 第二次编排:同 task_id 的 A 失败一次后成功——若预算未按编排重置,
    # 残留计数会让它一上来就被判"耗尽"而直接失败。
    a2 = _sub("A", "ta")
    orch2 = _FakeOrchestrator(fail_plan={"ta": 1})
    res = asyncio.run(_run(rt, orch2, [a2]))
    assert a2.status == SubTaskStatus.SUCCESS, "重试预算未按编排重置(残留计数污染)"
    assert res.status == OrchestrationStatus.SUCCESS
