from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.canonical_task import (
    TaskLifecycle,
    TaskOrigin,
    build_canonical_task,
    get_canonical_task_runtime,
    reset_canonical_task_runtime,
)
from core.mcp_loader import MCPLoader, MCPServerInstance, MCPServerStatus, MCPTool
from core.skill_loader import SkillInstance, SkillLoader, SkillStatus
from core.skill_md_loader import SkillMD, SkillMDLoader
from core.system_reality_checkpoint import (
    SYSTEM_REALITY_CHECKPOINT_AUTHORITY,
    build_system_reality_checkpoint,
)
from core.unified_panel_aggregation import build_unified_panel_payload


def test_checkpoint_contains_all_subproblem_surfaces():
    reset_canonical_task_runtime()
    rt = get_canonical_task_runtime()
    task = build_canonical_task(
        task_id="alloc-checkpoint-task",
        goal="checkpoint",
        origin=TaskOrigin.API_REQUEST,
        selected_targets=["android-01"],
        route_preference="cross_device",
        transport_preference="websocket",
    )
    task.routing.effective_path = "canonical_dispatch"
    task.advance_lifecycle(TaskLifecycle.DISPATCHED)
    rt.register(task)

    checkpoint = build_system_reality_checkpoint()
    assert checkpoint["authority"] == SYSTEM_REALITY_CHECKPOINT_AUTHORITY
    assert "node_system" in checkpoint
    assert "mcp_skill_tool_capability" in checkpoint
    assert "long_running_runtime_credibility" in checkpoint
    assert "unified_panel_runtime_truth" in checkpoint
    assert "model_topology" in checkpoint
    assert "task_allocation_visibility" in checkpoint
    assert "device_support_boundaries" in checkpoint
    assert "device_autonomy_evidence" in checkpoint
    assert "final_checkpoint" in checkpoint
    assert checkpoint["task_allocation_visibility"]["allocation_record_count"] >= 1
    assert checkpoint["task_allocation_visibility"]["history_record_count"] >= 1
    assert checkpoint["mcp_skill_tool_capability"]["compat_wrapper_tool_count"] >= 0
    assert checkpoint["model_topology"]["runtime_topology"]["runtime_host"] == "v2_control_plane"
    assert isinstance(checkpoint["model_topology"]["runtime_topology"]["galaxy_tree"], dict)
    assert checkpoint["model_topology"]["runtime_topology"]["grounded_node_count"] >= 0


def test_unified_panel_embeds_system_reality_checkpoint():
    payload = build_unified_panel_payload()
    assert isinstance(payload.system_reality_checkpoint, dict)
    assert payload.system_reality_checkpoint.get("authority") == SYSTEM_REALITY_CHECKPOINT_AUTHORITY
    assert "final_checkpoint" in payload.system_reality_checkpoint


@pytest.mark.asyncio
async def test_mcp_call_tool_requires_declared_tool_capability():
    loader = MCPLoader()
    server = MCPServerInstance(
        id="s1",
        name="srv",
        command=["python"],
        status=MCPServerStatus.RUNNING,
        tools=[MCPTool(name="declared_tool", description="d", inputSchema={})],
    )
    loader.servers["s1"] = server

    blocked = await loader.call_tool("s1", "missing_tool", {})
    assert blocked["success"] is False
    assert blocked["capability_checked"] is True
    assert blocked["runtime_semantics"] == "formal_mcp_tool_call"

    with patch.object(
        loader,
        "_send_request",
        new=AsyncMock(return_value=type("Resp", (), {"error": None, "result": {"isError": False}})()),
    ):
        ok = await loader.call_tool("s1", "declared_tool", {})
    assert ok["success"] is True
    assert ok["capability_checked"] is True


@pytest.mark.asyncio
async def test_skill_md_execute_checks_runtime_command_capability():
    loader = SkillMDLoader()
    loader.skills["s"] = SkillMD(
        name="s",
        description="d",
        commands=[{"language": "bash", "command": "curl https://example.com"}],
    )
    with patch("shutil.which", return_value=None), patch(
        "asyncio.create_subprocess_exec", new=AsyncMock()
    ) as mock_exec:
        result = await loader.execute("s")
    assert result["success"] is False
    assert result["runtime_semantics"] == "shell_command_skill"
    assert result["results"][0]["capability_checked"] is True
    assert "运行时能力不可用" in result["results"][0]["error"]
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_skill_loader_execute_marks_in_process_callable_semantics():
    loader = SkillLoader()
    loader.skills["callable"] = SkillInstance(
        id="callable",
        name="callable",
        description="d",
        status=SkillStatus.LOADED,
        handler=lambda **_: {"ok": True},
    )
    result = await loader.execute("callable")
    assert result["success"] is True
    assert result["runtime_semantics"] == "in_process_callable_skill"
    assert result["capability_checked"] is True
