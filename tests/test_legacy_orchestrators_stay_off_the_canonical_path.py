"""节点声明的类别在没登记的时候也算数(第 11 轮)。

``core/orchestration_authority/legacy_paths.py`` 声明 Node_110 / Node_81 / Node_50 是旧编排节点(``LEGACY_ORCHESTRATOR_NODE``),
规范调用路径不经它们调度。可是声明从没生效:

* 启动器登记节点时一律写 ``CAPABILITY_NODE``;
* 没在跑的节点在进程内起、不登记,治理门对没登记的节点一律放行(日志里那句 ``governance not enforced``)。

于是第 10 轮开放给模型的 ``nodes__invoke`` 能驱动这三个本该退下的编排节点(它们会替模型去调别的节点、绕开各自的门)。
现在一处说了算(``core/node_declared_class.py``):启动器按声明登记,治理门对没登记的节点也按声明的类别判,模型的节点目录不列它们。
"""

from __future__ import annotations

import asyncio

import pytest

LEGACY = ("Node_110_SmartOrchestrator", "Node_81_Orchestrator", "Node_50_Transformer")


@pytest.fixture(autouse=True)
def _no_node_processes(monkeypatch, tmp_path):
    import core.node_route_bridge as bridge

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(bridge, "_node_url", lambda node_id: "")


def test_the_declared_class_comes_from_one_place():
    from core.node_declared_class import declared_class
    from core.nodes.node_fabric_registry import NodeArchitecturalClass as C

    for node in LEGACY + ("110", "Node_81"):
        assert declared_class(node) is C.LEGACY_ORCHESTRATOR_NODE, node
    assert declared_class("Node_30_Reserved") is C.ARCHIVED_NODE, "目录里登记为不可运行的占位节点"
    assert declared_class("Node_23_Time") is C.CAPABILITY_NODE
    assert declared_class("ghost-node") is C.CAPABILITY_NODE, "不在 nodes/ 下的:与登记表的缺省一致"


@pytest.mark.parametrize("node", LEGACY + ("Node_30_Reserved",))
def test_an_unregistered_node_is_judged_by_its_declared_class(node):
    from core.node_invocation_governance import evaluate_invocation_governance
    from core.nodes.node_fabric_registry import NodeFabricRegistry

    decision = evaluate_invocation_governance(node, registry=NodeFabricRegistry())
    assert decision.invocation_allowed is False
    assert decision.governance_status == "unregistered_declared_class_excluded"
    assert decision.denial_reasons in (["non_capability_architectural_class"], ["archived_node"])
    assert decision.diagnostic_context["note"], "说得出为什么"


def test_an_unregistered_capability_node_still_goes_through():
    from core.node_invocation_governance import evaluate_invocation_governance
    from core.nodes.node_fabric_registry import NodeFabricRegistry

    decision = evaluate_invocation_governance("Node_23_Time", registry=NodeFabricRegistry())
    assert decision.invocation_allowed is True and decision.governance_status == "unregistered_unmanaged"


def test_the_launcher_registers_nodes_with_their_declared_class(monkeypatch):
    import core.nodes.node_fabric_registry as fabric_mod
    from core.nodes.node_fabric_registry import NodeArchitecturalClass as C
    from core.nodes.node_fabric_registry import NodeFabricRegistry
    from launcher.node_startup import NodeSystemLauncher

    fabric = NodeFabricRegistry()
    monkeypatch.setattr(fabric_mod, "get_node_fabric_registry", lambda: fabric)
    launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
    launcher.node_configs = {}
    launcher._register_node_in_canonical_registry("Node_110_SmartOrchestrator", 8110, "healthy")
    launcher._register_node_in_canonical_registry("Node_23_Time", 8023, "healthy")
    assert fabric.get("Node_110_SmartOrchestrator").architectural_class is C.LEGACY_ORCHESTRATOR_NODE
    assert fabric.get("Node_23_Time").architectural_class is C.CAPABILITY_NODE


def test_the_unified_executor_refuses_a_legacy_orchestrator():
    from core.node_invocation import InvocationSource, invoke_node

    res = asyncio.run(invoke_node("Node_81_Orchestrator", "workflows", {}, invocation_source=InvocationSource.SYSTEM))
    assert res.success is False and "governance" in str(res.error)


def test_the_model_neither_sees_nor_can_invoke_them(monkeypatch):
    import core.approval_gate as gate
    from core.node_tools import dispatch_nodes_tool

    asked = []

    async def ask(**kw):
        asked.append(kw)
        raise AssertionError("不该为一个不会执行的调用去问人")

    monkeypatch.setattr(gate, "request_approval", ask)
    listed = asyncio.run(dispatch_nodes_tool("list", {}))
    lines = [line for group in listed["groups"].values() for line in group]
    for node in LEGACY + ("Node_30_Reserved",):
        assert not any(line.startswith(node) for line in lines), node
    out = asyncio.run(
        dispatch_nodes_tool("invoke", {"node": "Node_110_SmartOrchestrator", "action": "submit_task", "params": {}})
    )
    assert not out["success"] and "旧的编排节点" in out["error"] and asked == []
    detail = asyncio.run(dispatch_nodes_tool("list", {"node": "81"}))
    assert not detail["success"] and "devices__plan" in detail["error"]


def test_a_stale_snapshot_that_registered_it_as_a_capability_node_does_not_count():
    """真跑时查到:登记快照(数据目录里)是启动器以前一律按能力节点写的,恢复回来仍是能力节点。"""
    from core.node_invocation_governance import evaluate_invocation_governance
    from core.nodes.node_fabric_registry import NodeArchitecturalClass as C
    from core.nodes.node_fabric_registry import NodeFabricRegistry, NodeInfo, NodeStatus

    fabric = NodeFabricRegistry()
    fabric.register(
        NodeInfo(node_id="Node_81_Orchestrator", architectural_class=C.CAPABILITY_NODE, status=NodeStatus.HEALTHY)
    )
    fabric.heartbeat("Node_81_Orchestrator")
    decision = evaluate_invocation_governance("Node_81_Orchestrator", registry=fabric)
    assert decision.invocation_allowed is False
    assert "non_capability_architectural_class" in decision.denial_reasons


def test_relaunching_a_node_corrects_its_stale_class(monkeypatch):
    import core.nodes.node_fabric_registry as fabric_mod
    from core.nodes.node_fabric_registry import NodeArchitecturalClass as C
    from core.nodes.node_fabric_registry import NodeFabricRegistry, NodeInfo
    from launcher.node_startup import NodeSystemLauncher

    fabric = NodeFabricRegistry()
    fabric.register(NodeInfo(node_id="Node_50_Transformer", architectural_class=C.CAPABILITY_NODE))
    monkeypatch.setattr(fabric_mod, "get_node_fabric_registry", lambda: fabric)
    launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
    launcher.node_configs = {}
    launcher._register_node_in_canonical_registry("Node_50_Transformer", 8050, "healthy")
    assert fabric.get("Node_50_Transformer").architectural_class is C.LEGACY_ORCHESTRATOR_NODE


def test_rest_says_403_not_500_when_governance_refuses():
    from core.routes.nodes import _call_failure_status

    err = "Node Node_81_Orchestrator denied invocation due to governance eligibility check failure: ['x']"
    assert _call_failure_status(err) == 403
