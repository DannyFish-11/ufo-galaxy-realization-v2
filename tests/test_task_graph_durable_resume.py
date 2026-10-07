"""tests/test_task_graph_durable_resume.py
=============================================
Feature ① — task graph 的【步级检查点 + 断点续跑】。
默认开(GALAXY_DURABLE_EXEC 未设);只有显式写 0/false/no/off 才关 → 不落盘。开启时:每步 transition 原子
落盘;新实例(模拟进程重启)从盘上重建;已完成步被跳过、依赖满足的待执行步可续跑。
落盘位置跟 GALAXY_DATA_DIR,且有保留上限(只留续跑要的 + 最近结束的一小批)。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import core.task_graph_checkpoint as ck
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


def test_enabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(tmp_path / "g.json"))
    # 未设 GALAXY_DURABLE_EXEC → durable 开(产品默认)
    assert ck.durable_exec_enabled() is True
    rt = TaskGraphRuntime()
    assert rt._durable is True
    rt.register_node(_node("t1"))
    assert (tmp_path / "g.json").exists()


@pytest.mark.parametrize("off", ["0", "false", "No", "OFF"])
def test_explicitly_off_writes_nothing(tmp_path, monkeypatch, off):
    monkeypatch.setenv("GALAXY_DURABLE_EXEC", off)
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(tmp_path / "g.json"))
    rt = TaskGraphRuntime()
    assert rt._durable is False
    rt.register_node(_node("t1"))
    rt.transition("t1", GraphNodeState.COMPLETED)
    assert not (tmp_path / "g.json").exists()  # 零落盘


def test_the_checkpoint_lives_under_the_data_dir_not_the_repo(tmp_path, monkeypatch):
    """默认开之后,检查点不能再落在仓库的 runtime/ 下 —— 测试与别的数据目录会读到同一份。"""
    monkeypatch.delenv("GALAXY_TASK_GRAPH_STATE_PATH", raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    assert ck.task_graph_state_path() == str(tmp_path / "task_graph_state.json")


def test_a_checkpoint_already_at_the_old_location_is_still_found(tmp_path, monkeypatch):
    monkeypatch.delenv("GALAXY_TASK_GRAPH_STATE_PATH", raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    legacy_root = tmp_path / "repo"
    (legacy_root / "runtime").mkdir(parents=True)
    legacy = legacy_root / "runtime" / "task_graph_state.json"
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ck, "_REPO_ROOT", str(legacy_root))
    assert ck.task_graph_state_path() == str(legacy), "旧位置上已有检查点、新位置还没有:沿用旧的,不丢"


def test_the_checkpoint_is_bounded_but_keeps_what_resume_needs(tmp_path, monkeypatch):
    """每次状态变更都整份重写检查点;不设上限就是「有史以来所有节点」。续跑要的必须留:没结束的、它们依赖的。"""
    monkeypatch.setattr(ck, "KEEP_FINISHED", 3)
    p = tmp_path / "g.json"
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(p))
    rt = TaskGraphRuntime()
    rt.register_node(_node("dep"))
    rt.transition("dep", GraphNodeState.COMPLETED)
    rt.register_node(_node("waiting", depends_on=["dep"]))  # 没结束,依赖 dep
    for i in range(10):  # 十个已经结束、也没人依赖的
        rt.register_node(_node(f"old{i}"))
        rt.transition(f"old{i}", GraphNodeState.COMPLETED)
    rt.register_node(GraphNode(task_id="proj", metadata={"assimilation_projection": True}))  # 能力吸收投影,不落盘

    kept = {n["task_id"] for n in json.loads(p.read_text(encoding="utf-8"))["nodes"]}
    assert {"waiting", "dep"} <= kept, "还要续跑的节点和它依赖的节点必须留"
    assert "proj" not in kept
    assert len(kept - {"waiting", "dep"}) == 3, "已结束且没人依赖的只留最近 3 个"

    rt2 = TaskGraphRuntime()  # 重启:依赖还在,waiting 仍可续跑
    assert [n.task_id for n in rt2.resumable_nodes()] == ["waiting"]


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


def test_assimilation_projection_nodes_are_not_resumable_work(tmp_path, monkeypatch, caplog):
    """能力吸收投影进任务图的"执行参与者"节点不是待派发任务：重启续跑不碰、也不报"重派失败"。

    真机：每个 Node 一个 executor__<Node> 投影节点，没有工具名也没有载荷，一次启动刷 ~100 条警告。
    """
    import logging

    monkeypatch.setenv("GALAXY_DURABLE_EXEC", "1")
    monkeypatch.setenv("GALAXY_TASK_GRAPH_STATE_PATH", str(tmp_path / "g.json"))
    rt = TaskGraphRuntime()
    rt.register_node(GraphNode(task_id="executor__Node_01_OneAPI", metadata={"assimilation_projection": True}))
    rt.register_node(_node("real-task"))

    rt2 = TaskGraphRuntime()  # 重启
    assert [n.task_id for n in rt2.resumable_nodes()] == ["real-task"]
    snap = rt2.resume_snapshot()
    assert "executor__Node_01_OneAPI" not in snap["resumable"] + snap["blocked"]

    seen = []
    caplog.set_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime")
    result = asyncio.run(rt2.resume_pending_dispatch(lambda n: seen.append(n.task_id)))
    assert seen == ["real-task"] and result["failed"] == []
    assert not [r for r in caplog.records if "续跑重派失败" in r.getMessage()]
