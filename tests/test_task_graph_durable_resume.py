"""tests/test_task_graph_durable_resume.py
=============================================
Feature ① — task graph 的【步级检查点 + 断点续跑】。
默认关(GALAXY_DURABLE_EXEC 未设)→ 不落盘、零行为变化。开启后:每步 transition 原子
落盘;新实例(模拟进程重启)从盘上重建;已完成步被跳过、依赖满足的待执行步可续跑。
"""

from __future__ import annotations

import asyncio

import pytest

import core.task_graph_runtime as tg
from core.task_graph_runtime import GraphNode, GraphNodeState, TaskGraphRuntime


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    monkeypatch.delenv("GALAXY_DURABLE_EXEC", raising=False)
    monkeypatch.delenv("GALAXY_TASK_GRAPH_STATE_PATH", raising=False)
    tg.reset_task_graph_runtime()
    yield
    tg.reset_task_graph_runtime()


def _node(task_id, state=GraphNodeState.QUEUED, depends_on=None):
    return GraphNode(task_id=task_id, state=state, depends_on=list(depends_on or []))


def test_disabled_by_default_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(tmp_path / "g.json"))
    # 未设 GALAXY_DURABLE_EXEC → durable 关
    rt = TaskGraphRuntime()
    assert rt._durable is False
    rt.register_node(_node("t1"))
    rt.transition("t1", GraphNodeState.COMPLETED)
    assert not (tmp_path / "g.json").exists()  # 零落盘


def test_checkpoint_and_resume_across_restart(tmp_path, monkeypatch):
    p = str(tmp_path / "g.json")
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", p)

    rt = TaskGraphRuntime()
    # 两步 DAG:t2 依赖 t1。t1 完成、t2 还在排队。
    rt.register_node(_node("t1"))
    rt.register_node(_node("t2", depends_on=["t1"]))
    rt.transition("t1", GraphNodeState.COMPLETED)
    assert (tmp_path / "g.json").exists()

    # 模拟进程重启:全新实例从盘上重建
    rt2 = TaskGraphRuntime()
    assert rt2.get_node_by_task_id("t1").state == GraphNodeState.COMPLETED
    assert rt2.get_node_by_task_id("t2").state == GraphNodeState.QUEUED
    # t1 已完成 → 跳过;t2 依赖已满足 → 可续跑
    assert rt2.completed_task_ids() == ["t1"]
    assert [n.task_id for n in rt2.resumable_nodes()] == ["t2"]


def test_blocked_when_dependency_incomplete(tmp_path, monkeypatch):
    p = str(tmp_path / "g.json")
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", p)
    rt = TaskGraphRuntime()
    rt.register_node(_node("a"))
    rt.register_node(_node("b", depends_on=["a"]))
    # a 还没完成 → b 被依赖阻塞,不在可续跑集合里
    rt2 = TaskGraphRuntime()
    assert [n.task_id for n in rt2.resumable_nodes()] == ["a"]  # 只有无依赖的 a 可跑
    snap = rt2.resume_snapshot()
    assert "b" in snap["blocked"] and "a" in snap["resumable"]


def test_completed_node_not_resumable(tmp_path, monkeypatch):
    p = str(tmp_path / "g.json")
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", p)
    rt = TaskGraphRuntime()
    rt.register_node(_node("done"))
    rt.transition("done", GraphNodeState.COMPLETED)
    rt2 = TaskGraphRuntime()
    assert rt2.resumable_nodes() == []  # 终态不重派(不重复副作用)
    assert rt2.resume_snapshot()["completed"] == ["done"]


def test_executed_result_state_not_resumable(tmp_path, monkeypatch):
    # RESULT 态 = 已执行、拿到结果、等定案 → 不应重派(否则重复副作用)
    p = str(tmp_path / "g.json")
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", p)
    rt = TaskGraphRuntime()
    rt.register_node(_node("r"))
    rt.transition("r", GraphNodeState.RESULT)
    rt2 = TaskGraphRuntime()
    assert rt2.resumable_nodes() == []
    assert "r" in rt2.resume_snapshot()["executed_pending_finalization"]


def test_atomic_write_no_tmp_leftover(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(tmp_path / "g.json"))
    rt = TaskGraphRuntime()
    rt.register_node(_node("t1"))
    rt.transition("t1", GraphNodeState.DISPATCH)
    rt.transition("t1", GraphNodeState.COMPLETED)
    assert [f for f in tmp_path.iterdir() if f.suffix == ".tmp"] == []


def test_running_node_is_resumable_relies_on_idempotency(tmp_path, monkeypatch):
    # RUNNING(崩时在途)算可续跑,重派靠 ② 派发幂等守卫防二次副作用
    p = str(tmp_path / "g.json")
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", p)
    rt = TaskGraphRuntime()
    rt.register_node(_node("run"))
    rt.transition("run", GraphNodeState.DISPATCH)
    rt.transition("run", GraphNodeState.RUNNING)
    rt2 = TaskGraphRuntime()
    assert [n.task_id for n in rt2.resumable_nodes()] == ["run"]


def test_resume_pending_dispatch_calls_back_and_marks_dispatch(tmp_path, monkeypatch):
    p = str(tmp_path / "g.json")
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", p)
    rt = TaskGraphRuntime()
    rt.register_node(_node("t1"))
    rt.register_node(_node("t2", depends_on=["t1"]))
    rt.transition("t1", GraphNodeState.COMPLETED)

    rt2 = TaskGraphRuntime()  # 重启
    dispatched = []

    async def _dispatch(node):
        dispatched.append(node.task_id)

    out = asyncio.run(rt2.resume_pending_dispatch(_dispatch))
    assert dispatched == ["t2"]  # 只重派可续跑的 t2(t1 已完成跳过)
    assert out["resumed"] == ["t2"] and out["failed"] == []
    assert rt2.get_node_by_task_id("t2").state == GraphNodeState.DISPATCH  # 置回 DISPATCH


def test_resume_pending_dispatch_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(tmp_path / "g.json"))
    rt = TaskGraphRuntime()
    rt.register_node(_node("ok"))
    rt.register_node(_node("bad"))

    def _dispatch(node):
        if node.task_id == "bad":
            raise RuntimeError("dispatch boom")

    out = asyncio.run(rt.resume_pending_dispatch(_dispatch))
    assert "ok" in out["resumed"]
    assert any(f[0] == "bad" for f in out["failed"])  # 单个失败被隔离
