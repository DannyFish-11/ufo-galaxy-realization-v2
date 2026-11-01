"""core/node_declared_class.py —— 一个节点**声明的**架构类别，不管它登没登记进 NodeFabricRegistry（第 11 轮）。

为什么要有它
============
治理门（``core/node_invocation_governance.py``）只对登记进 NodeFabricRegistry 的节点按类别判：旧编排节点
（``LEGACY_ORCHESTRATOR_NODE``）、归档节点不走规范调用路径。可是：

* 启动器登记节点时一律写 ``CAPABILITY_NODE`` —— ``core/orchestration_authority/legacy_paths.py`` 声明的三个旧编排节点
  （Node_110 / Node_81 / Node_50）登记进去也是「能力节点」，声明从没生效过；
* 第 9、10 轮之后，没在跑的节点在进程内起（不登记），治理门对它们一律「不登记 = 不管」放行 ——
  模型经 ``nodes__invoke`` 就能驱动这三个本该退下的编排节点。

这里给出一个节点声明的类别，一处说了算：

* 模块路径在 ``LEGACY_ORCHESTRATOR_NODE_PREFIXES`` 里 → ``LEGACY_ORCHESTRATOR_NODE``；
* 节点目录里登记为不可运行（占位节点）→ ``ARCHIVED_NODE``；
* 其余 → ``CAPABILITY_NODE``；认不出的节点（不在 nodes/ 下）也按 ``CAPABILITY_NODE``（与登记表的缺省一致）。

启动器登记、治理门判没登记的节点、模型的节点目录，都用它。
"""

from __future__ import annotations

from typing import Optional


def _dir(node_id: str) -> Optional[str]:
    try:
        from core.node_actions import node_dir

        return node_dir(node_id)
    except Exception:  # noqa: BLE001 — 认不出:按缺省类别
        return None


def declared_class(node_id: str):
    """这个节点声明的 :class:`~core.nodes.node_fabric_registry.NodeArchitecturalClass`。"""
    from core.nodes.node_fabric_registry import NodeArchitecturalClass
    from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_NODE_PREFIXES

    found = _dir(node_id)
    if found is None:
        return NodeArchitecturalClass.CAPABILITY_NODE
    if f"nodes.{found}" in LEGACY_ORCHESTRATOR_NODE_PREFIXES:
        return NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE
    from core.node_catalog import catalog_nodes

    runnable = {n["dir"]: n.get("runnable", True) for n in catalog_nodes()}
    if runnable.get(found) is False:
        return NodeArchitecturalClass.ARCHIVED_NODE
    return NodeArchitecturalClass.CAPABILITY_NODE


def with_declared_class(node_info):
    """登记表里的这一条,类别按声明改正后的样子(声明不是能力节点时声明为准;否则原样)。

    旧的登记快照里,旧编排节点被写成了能力节点(启动器以前一律这么登记,快照会被恢复回来)。
    """
    from core.nodes.node_fabric_registry import NodeArchitecturalClass

    declared = declared_class(getattr(node_info, "node_id", ""))
    if declared is NodeArchitecturalClass.CAPABILITY_NODE or node_info.architectural_class is declared:
        return node_info
    import dataclasses

    return dataclasses.replace(node_info, architectural_class=declared)


def why_not_callable(node_id: str) -> str:
    """规范路径不调这个节点的原因（能调就是空串）—— 给人看的一句话。"""
    from core.nodes.node_fabric_registry import NodeArchitecturalClass

    cls = declared_class(node_id)
    if cls is NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE:
        return "这是旧的编排节点（LEGACY_ORCHESTRATOR），规范路径不经它调度；多步、多设备的事用 devices__plan"
    if cls is NodeArchitecturalClass.ARCHIVED_NODE:
        return "这是占位节点，没有可用的实现"
    return ""


__all__ = ["declared_class", "why_not_callable", "with_declared_class"]
