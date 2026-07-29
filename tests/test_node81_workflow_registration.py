"""tests/test_node81_workflow_registration.py
=============================================
``nodes/Node_81_Orchestrator`` 工作流登记行为测试。

这个节点此前**零测试覆盖**,于是一个很直接的缺陷长期存在:
ConstellationRuntime **主路径**直接构造 WorkflowResult 就返回,从不写进
``orchestrator.workflows``;而 ``orchestrator.workflows`` 全文件只有降级路径的
``execute_workflow()`` 会写。结果是主路径返回的 workflow_id 在所有查询接口里
都不存在 —— 刚拿到的 id 立刻 404,而降级路径反倒正常。

本文件锁定的契约很朴素:**execute_workflow 返回的 workflow_id,必须能被查到。**
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MAIN = pathlib.Path(__file__).resolve().parent.parent / "nodes" / "Node_81_Orchestrator" / "main.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_n81_under_test", _MAIN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_n81_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def n81():
    mod = _load_module()
    mod.orchestrator.workflows.clear()
    return mod


def _run_primary_path(mod, task_id="wf-cr-1"):
    """走 ConstellationRuntime 主路径,返回 WorkflowResult。"""
    import core.constellation_runtime as cr

    fake_runtime = MagicMock()
    fake_runtime.run = AsyncMock(return_value={"success": True})
    with (
        patch.object(cr, "get_constellation_runtime", return_value=fake_runtime),
        patch.object(
            cr,
            "wrap_as_orchestration_response",
            return_value={"task_id": task_id, "result": {"ok": 1}},
        ),
    ):
        req = mod.WorkflowRequest(description="demo", tasks=[])
        return asyncio.run(mod.execute_workflow(req, MagicMock()))


class TestPrimaryPathRegistersWorkflow:
    """主路径(ConstellationRuntime)返回的 id 必须可查。"""

    def test_returned_id_is_retrievable(self, n81):
        result = _run_primary_path(n81)
        wid = result.workflow_id
        # 回归锁定:修复前这里是 None —— GET /workflow/{id} 会 404
        assert n81.orchestrator.workflows.get(wid) is not None

    def test_returned_id_appears_in_listing(self, n81):
        result = _run_primary_path(n81)
        assert result.workflow_id in n81.orchestrator.workflows

    def test_active_workflow_count_includes_primary_path(self, n81):
        assert len(n81.orchestrator.workflows) == 0
        _run_primary_path(n81)
        # /status 的 active_workflows 读的就是这个长度
        assert len(n81.orchestrator.workflows) == 1

    def test_registered_object_is_the_returned_one(self, n81):
        result = _run_primary_path(n81)
        assert n81.orchestrator.workflows[result.workflow_id] is result

    def test_distinct_workflows_are_all_registered(self, n81):
        a = _run_primary_path(n81, task_id="wf-a")
        b = _run_primary_path(n81, task_id="wf-b")
        assert {a.workflow_id, b.workflow_id} <= set(n81.orchestrator.workflows)
        assert len(n81.orchestrator.workflows) == 2
