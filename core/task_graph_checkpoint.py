"""任务图检查点（落盘 / 续跑）的开关、位置与保留规则。

从 ``core/task_graph_runtime.py`` 拆出来 —— 那个文件已经顶到体量基线，而这三件事本来就是一块：
**要不要落盘、落在哪、落哪些**。运行时只负责「什么时候落」。

* ``durable_exec_enabled()``  —— 默认开；只有显式 0 / false / no / off 才关。
* ``task_graph_state_path()`` —— 认 ``GALAXY_DATA_DIR``（本仓所有持久化点的约定）。以前落在仓库的 ``runtime/`` 下，
  默认开之后这件事不能再含糊：测试与别的数据目录会读到同一份。旧位置上已有文件、新位置还没有时沿用旧位置。
* ``select_retained()``       —— 每次状态变更都整份重写检查点，不设上限就是「有史以来所有节点」。续跑要的必须留：
  没结束的节点、它们依赖的节点、连接它们的边；其余已经结束、也没人依赖的只留最近一小批。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable, List, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 除了「还要续跑的节点和它们依赖的节点」之外，最多再留多少个已经结束、也没人依赖的节点（给操作台看最近的结果）。
KEEP_FINISHED = 200


def durable_exec_enabled() -> bool:
    """是否启用【DAG 步级检查点 + 断点续跑】的可持久化。**默认开**。

    开启后 task graph 的每步状态变更会原子落盘，进程重启即从盘上重建、跳过已完成步、把未完成步交给恢复协调器重派
    （逐节点先过派发幂等守卫，崩溃前已派发过的不会二次触发副作用）。只有显式写成 0 / false / no / off 才关。
    """
    return str(os.getenv("GALAXY_DURABLE_EXEC", "")).strip().lower() not in ("0", "false", "no", "off")


def task_graph_state_path() -> str:
    """检查点文件的位置：显式指定 > ``$GALAXY_DATA_DIR/task_graph_state.json``（旧位置上已有文件则沿用）。"""
    explicit = str(os.getenv("GALAXY_TASK_GRAPH_STATE_PATH", "")).strip()
    if explicit:
        return explicit
    data_dir = str(os.getenv("GALAXY_DATA_DIR", "")).strip() or os.path.join(_REPO_ROOT, "data")
    current = os.path.join(data_dir, "task_graph_state.json")
    legacy = os.path.join(_REPO_ROOT, "runtime", "task_graph_state.json")
    if not os.path.exists(current) and os.path.exists(legacy):
        return legacy
    return current


def select_retained(
    nodes: Iterable[Any],
    edges: Iterable[Any],
    *,
    terminal_states: Any,
    is_projection_only: Callable[[Any], bool],
) -> Tuple[List[Any], List[Any]]:
    """落盘要留哪些节点和边：**续跑需要的**，外加最近结束的一小批。

    续跑要的是：还没结束的节点（含已执行待定案的）、它们依赖的节点（``resumable_nodes`` 要求依赖都在已完成集合里）、
    以及连接它们的边。能力吸收只是把「某节点能执行」投影进任务图 —— 没有可重放的载荷，不落盘。
    """
    all_nodes = list(nodes)
    by_task = {n.task_id: n for n in all_nodes}
    live = [n for n in all_nodes if n.state not in terminal_states and not is_projection_only(n)]
    keep = {n.task_id for n in live}
    for n in live:
        keep.update(dep for dep in (n.depends_on or []) if dep in by_task)
    finished = sorted(
        (n for n in all_nodes if n.task_id not in keep and n.state in terminal_states and not is_projection_only(n)),
        key=lambda n: n.completed_at or n.queued_at or 0.0,
        reverse=True,
    )
    keep.update(n.task_id for n in finished[:KEEP_FINISHED])
    kept_nodes = [n for n in all_nodes if n.task_id in keep]
    node_ids = {n.node_id for n in kept_nodes}
    kept_edges = [e for e in edges if e.source_node_id in node_ids and e.target_node_id in node_ids]
    return kept_nodes, kept_edges


__all__ = ["KEEP_FINISHED", "durable_exec_enabled", "select_retained", "task_graph_state_path"]
