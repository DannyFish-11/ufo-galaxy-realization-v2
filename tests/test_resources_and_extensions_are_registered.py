"""tests/test_resources_and_extensions_are_registered.py — 扩展装卸、系统资源表、多设备收口这一批接线真的生效。

此前这些都是「写好了接收方、没人调」：

* 系统资源表：OpenClawd 的 resource__* 工具在读，登记方一个都没被调用，表永远是空的；
* MCP 工具只进 CapabilityRegistry，统一能力总线里没有；装卸之后能力编排器也不刷新；
* 设备回来的任务结果只唤醒本地事件，经 NATS 转来的任务永远等到超时；
* 并行组的子结果到齐了也没人收口，要等超时清扫；
* 唤醒路由判定了新设备，漫游会话却永远留在原来那台；
* DAG 执行路径的子任务在任务图里一个都看不见；
* 智能体消息总线没人取消息，长期存活的父 Agent 攒满队列后发送方会永远卡住；
* 工具失败的性质（瞬时 / 确定性 / 被拒）只进了状态，模型自己看不见。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# 系统资源表
# ---------------------------------------------------------------------------


@pytest.fixture
def _fresh_resources():
    import core.capability_bus as cb
    import core.system_resource as sr

    sr.reset_system_resource_registry()
    cb.reset_capability_bus()
    yield sr, cb
    sr.reset_system_resource_registry()
    cb.reset_capability_bus()


class TestSystemResourcesAreSeeded:
    def test_builtin_resources_and_their_capabilities_are_registered(self, _fresh_resources):
        sr, cb = _fresh_resources
        summary = sr.seed_builtin_system_resources()
        registry = sr.get_system_resource_registry()
        for rid in ("builtin__engineering", "local_tool__code_sandbox"):
            assert registry.lookup(rid) is not None, rid
        assert summary["resources"] == 4 and summary["engineering_capabilities"] > 0
        bus = cb.get_capability_bus()
        for action in sr.RESOURCE_CAPABILITY_ACTIONS:
            assert bus.lookup(f"resource__{action}") is not None
        assert any(e.name.startswith("engineer__") for e in bus.list_all())

    def test_resource_actions_match_the_tools_the_model_sees(self):
        from core.openclawd import _RESOURCE_BUILTIN_TOOLS
        from core.system_resource import RESOURCE_CAPABILITY_ACTIONS

        tool_actions = {t["function"]["name"].split("__", 1)[1] for t in _RESOURCE_BUILTIN_TOOLS}
        assert tool_actions == set(RESOURCE_CAPABILITY_ACTIONS)

    def test_device_resource_follows_presence(self, _fresh_resources):
        sr, _ = _fresh_resources
        from core.unified.presence_fanout import presence_changed

        device = SimpleNamespace(device_id="res-dev-1", capabilities=["camera"], ip_address="", port=0)
        presence_changed(device, online=True)
        record = sr.get_system_resource_registry().lookup("device__res-dev-1")
        assert record is not None and record.health == sr.SystemResourceHealth.HEALTHY
        presence_changed(device, online=False, reason="test")
        record = sr.get_system_resource_registry().lookup("device__res-dev-1")
        assert record.health == sr.SystemResourceHealth.UNAVAILABLE  # 离线保留记录、标为不可用


# ---------------------------------------------------------------------------
# MCP / 技能装卸
# ---------------------------------------------------------------------------


class TestExtensionsReachTheCapabilityBus:
    def test_mcp_tools_enter_and_leave_the_bus_with_their_server(self, _fresh_resources):
        _, cb = _fresh_resources
        from core.mcp_loader import MCPLoader

        loader = MCPLoader.get_instance()
        server = SimpleNamespace(
            name="probe", tools=[SimpleNamespace(name="echo", description="echo it", inputSchema={})]
        )
        loader.servers["probe-srv"] = server
        try:
            loader._inject_server_to_registry("probe-srv")
            assert cb.get_capability_bus().lookup("mcp__probe-srv__echo") is not None
            loader._eject_server_from_registry("probe-srv", server)
            assert cb.get_capability_bus().lookup("mcp__probe-srv__echo") is None
        finally:
            loader.servers.pop("probe-srv", None)

    @pytest.mark.asyncio
    async def test_load_or_unload_refreshes_the_orchestrator_and_skill_registry(self, monkeypatch):
        import core.capability_orchestrator as co
        from core.routes import protocols
        from core.skill_registry import get_skill_registry

        refreshed, removed = [], []

        async def _reinit():
            refreshed.append(1)

        monkeypatch.setattr(co.capability_orchestrator, "reinitialize", _reinit)
        monkeypatch.setattr(get_skill_registry(), "unregister_skill", lambda name: removed.append(name))
        await protocols._capabilities_changed(removed_skill="gone-skill")
        assert refreshed == [1] and removed == ["gone-skill"]

    def test_scheduler_execute_code_tool_comes_from_the_executor(self):
        from core.safe_executor import SafeExecutor
        from core.scheduler import _BUILTIN_TOOLS

        defs = [t for t in _BUILTIN_TOOLS if t["function"]["name"] == "execute_code"]
        assert defs == [SafeExecutor.as_tool_definition()]


# ---------------------------------------------------------------------------
# 多设备收口
# ---------------------------------------------------------------------------


class TestMultiDeviceResultsClose:
    @pytest.mark.asyncio
    async def test_device_result_resolves_the_nats_waiter(self, monkeypatch):
        import galaxy_gateway.gateway_nats_adapter as gna
        from galaxy_gateway.device_router import DeviceRouter

        fut = asyncio.get_running_loop().create_future()
        adapter = SimpleNamespace(_pending={"nats-task-1": fut})
        adapter.resolve_task = lambda task_id, result: adapter._pending[task_id].set_result(result)
        monkeypatch.setattr(gna, "_adapter", adapter)
        await DeviceRouter().handle_task_result("nats-task-1", {"success": True, "result": "ok"})
        assert fut.done() and fut.result()["result"] == "ok"

    @pytest.mark.asyncio
    async def test_parallel_group_closes_when_the_last_result_arrives(self):
        from galaxy_gateway.orchestrator.parallel_tracker import get_tracker, record_parallel_fields

        tracker = get_tracker()
        await tracker.start_group("pg-close-1", expected_count=2, timeout_s=600)
        await record_parallel_fields({"group_id": "pg-close-1", "subtask_index": 0, "status": "success"})
        assert "pg-close-1" not in tracker._finalized
        await record_parallel_fields({"group_id": "pg-close-1", "subtask_index": 1, "status": "success"})
        assert tracker._finalized["pg-close-1"].status == "success"

    @pytest.mark.asyncio
    async def test_wake_decision_moves_the_roaming_session(self, monkeypatch):
        import importlib

        from galaxy_gateway.bootstrap.lifecycle import _follow_attention_with_roaming_sessions

        # 包的 __init__ 把同名单例抬到了包上，``import galaxy_gateway.wake_router as wr`` 拿到的是单例不是模块
        roaming = importlib.import_module("galaxy_gateway.session_roaming")
        wr = importlib.import_module("galaxy_gateway.wake_router")
        callbacks, shifts = [], []

        async def _shift(attention):
            shifts.append(attention)

        monkeypatch.setattr(wr, "wake_router", SimpleNamespace(set_decision_callback=callbacks.append))
        monkeypatch.setattr(roaming, "session_roaming", SimpleNamespace(auto_migrate_on_attention_shift=_shift))
        _follow_attention_with_roaming_sessions()
        await callbacks[0](SimpleNamespace(selected_device_id="tablet-9"))
        assert shifts == [{"tablet-9": True}]

    @pytest.mark.asyncio
    async def test_dag_run_is_projected_into_the_task_graph(self, monkeypatch):
        import core.task_graph as tg
        from core.e2e_orchestrator import compile_and_run_dag
        from core.task_graph_runtime import GraphNodeState, get_task_graph_runtime

        class _Graph:
            async def execute(self, **_kw):
                return SimpleNamespace(
                    success=False,
                    graph_id="g-proj",
                    trace_id="t-proj",
                    done_nodes=1,
                    failed_nodes=1,
                    skipped_nodes=0,
                    elapsed_ms=1.0,
                    node_statuses={"dag-node-ok": "done", "dag-node-bad": "failed"},
                    error="",
                )

        monkeypatch.setattr(tg, "compile_subtasks_to_graph", lambda *a, **k: _Graph())
        out = await compile_and_run_dag([], trace_id="t-proj", runtime_session_id="s-proj")
        assert out["graph_id"] == "g-proj"
        runtime = get_task_graph_runtime()
        assert runtime.get_node_by_task_id("dag-node-ok").state == GraphNodeState.COMPLETED
        assert runtime.get_node_by_task_id("dag-node-bad").state == GraphNodeState.FAILED


# ---------------------------------------------------------------------------
# 智能体小件
# ---------------------------------------------------------------------------


class TestAgentLoopDetails:
    @pytest.mark.asyncio
    async def test_full_agent_queue_drops_the_oldest_instead_of_blocking(self):
        from core.agent_factory import AgentMessage, AgentMessageBus

        bus = AgentMessageBus()
        bus.MAX_QUEUE_SIZE = 2
        bus.register("parent")
        for i in range(3):
            msg = AgentMessage(id=f"m{i}", sender_id="child", receiver_id="parent", msg_type="task_result")
            assert await asyncio.wait_for(bus.send(msg), timeout=1.0) is True
        got = [(await bus.receive("parent", timeout=0.1)).id for _ in range(2)]
        assert got == ["m1", "m2"]

    def test_the_model_is_told_what_kind_of_failure_it_was(self):
        from core.react_progress import classify_tool_outcome, outcome_hint

        def hint(error):
            return outcome_hint(classify_tool_outcome({"success": False, "error": error}))

        assert "可以原样重试" in hint("request timed out")
        assert "换工具或换参数" in hint("unknown tool foo")
        assert "交给用户" in hint("permission denied")
        assert hint("业务失败") == ""
        assert outcome_hint(classify_tool_outcome({"success": True})) == ""
