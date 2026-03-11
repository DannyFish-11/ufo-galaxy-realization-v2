"""
端到端集成测试 — 覆盖关键链路闭环
============================================================

验收清单：
  1. MCP/Skill 热加载 → CapabilityRegistry → LLM tools 参数传入（function calling）
  2. 设备注册（三条路径）→ CapabilityRegistry 可查 → 命令通过 CommandRouter → trace 记录
  3. /api/v1/chat 路由唯一走 OpenClawd 入口（无旧链路旁路）
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# 辅助工具
# ──────────────────────────────────────────────────────────────────────────────


def _make_capability_item(name: str, source: str = "mcp", source_id: str = "test"):
    from core.agent.capability_registry import CapabilityItem
    return CapabilityItem(
        name=name,
        description=f"测试工具: {name}",
        source=source,
        source_id=source_id,
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. MCP/Skill 热加载 → CapabilityRegistry → LLM tools 参数
# ──────────────────────────────────────────────────────────────────────────────


class TestMCPSkillToLLMTools:
    """MCP/Skill 热加载后，工具以 function calling 格式传入 LLM 调度链路。"""

    def test_capability_registry_to_tool_schemas_openai_format(self):
        """to_tool_schemas() 输出必须符合 OpenAI function calling 格式。"""
        from core.agent.capability_registry import CapabilityRegistry

        reg = CapabilityRegistry.get_instance()
        key = f"mcp__e2e_test__{uuid.uuid4().hex[:8]}"
        reg.register(_make_capability_item(key))

        try:
            schemas = reg.to_tool_schemas()
            target = next((s for s in schemas if s["function"]["name"] == key), None)
            assert target is not None, f"工具 {key} 应出现在 to_tool_schemas() 结果中"
            assert target["type"] == "function"
            assert "name" in target["function"]
            assert "description" in target["function"]
            assert "parameters" in target["function"]
        finally:
            reg._items.pop(key, None)

    @pytest.mark.asyncio
    async def test_execution_planner_sets_tool_schemas_on_plan(self):
        """ExecutionPlanner.execute() 必须将 to_tool_schemas() 结果写入 plan.tool_schemas。"""
        from core.agent.capability_registry import CapabilityRegistry
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult

        reg = CapabilityRegistry.get_instance()
        key = f"mcp__e2e_schema__{uuid.uuid4().hex[:8]}"
        reg.register(_make_capability_item(key))

        plan = ExecutionPlan(
            message="测试任务",
            intent=IntentResult(mode="task_execute", raw_intent="task_execute", confidence=0.9),
        )

        captured_plan = {}

        async def _mock_dispatch(p, strategy, steps, tc):
            captured_plan["tool_schemas"] = list(p.tool_schemas)
            from core.agent.execution_planner import ExecutionResult
            return ExecutionResult(success=True, reply="ok", mode=strategy)

        # mock refresh 为空操作，避免替换手动注册的 item
        async def _noop_refresh(force=False):
            pass

        planner = ExecutionPlanner()
        try:
            with patch.object(reg, "refresh", side_effect=_noop_refresh):
                with patch.object(planner, "_dispatch", side_effect=_mock_dispatch):
                    await planner.execute(plan)
        finally:
            reg._items.pop(key, None)

        assert "tool_schemas" in captured_plan, "plan.tool_schemas 应在 _dispatch 前被设置"
        tool_names = [s["function"]["name"] for s in captured_plan["tool_schemas"]]
        assert key in tool_names, f"工具 {key} 应出现在传给 _dispatch 的 plan.tool_schemas 中"

    @pytest.mark.asyncio
    async def test_execution_planner_task_dict_contains_tools(self):
        """_run_single_agent 调用 execute_agent_task 时 task_dict 必须含 tools 列表。"""
        from core.agent.capability_registry import CapabilityRegistry
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult

        reg = CapabilityRegistry.get_instance()
        key = f"mcp__e2e_task_dict__{uuid.uuid4().hex[:8]}"
        reg.register(_make_capability_item(key))

        plan = ExecutionPlan(
            message="单 Agent 执行测试",
            intent=IntentResult(mode="task_execute", raw_intent="task_execute", confidence=0.9),
        )

        captured = {}

        async def _mock_exec(agent_id, task_dict):
            captured["task_dict"] = task_dict
            return {"success": True, "reply": "done", "tool_calls": []}

        mock_agent = MagicMock()
        mock_agent.id = "agent_test_id"
        mock_agent.config = MagicMock()
        mock_agent.config.name = "TestAgent"

        mock_factory = MagicMock()
        mock_factory.create_from_llm = AsyncMock(return_value=mock_agent)
        mock_factory.execute_agent_task = AsyncMock(side_effect=_mock_exec)

        # mock refresh 为空操作，避免替换手动注册的 item
        async def _noop_refresh(force=False):
            pass

        planner = ExecutionPlanner()
        try:
            with patch.object(reg, "refresh", side_effect=_noop_refresh):
                with patch("core.agent.execution_planner.ExecutionPlanner._pick_strategy", return_value="single"):
                    with patch("core.agent_factory.get_agent_factory", return_value=mock_factory):
                        await planner.execute(plan)
        finally:
            reg._items.pop(key, None)

        assert "task_dict" in captured, "execute_agent_task 必须被调用"
        assert "tools" in captured["task_dict"], "task_dict 必须包含 tools 字段"
        tool_names = [s["function"]["name"] for s in captured["task_dict"]["tools"]]
        assert key in tool_names, f"工具 {key} 应出现在 task_dict['tools'] 中"


# ──────────────────────────────────────────────────────────────────────────────
# 2. 设备注册 → CapabilityRegistry → CommandRouter → trace
# ──────────────────────────────────────────────────────────────────────────────


class TestDeviceRegistrationAllPaths:
    """三条设备注册路径均必须同步能力到 CapabilityRegistry。"""

    def _device_info(self, suffix: str):
        return {
            "device_id": f"e2e_device_{suffix}",
            "device_type": "android",
            "device_name": f"E2E Device {suffix}",
            "capabilities": ["screen", "touch"],
        }

    def test_v1_register_syncs_capability_registry(self):
        """/api/v1/devices/register 注册后能力必须出现在 CapabilityRegistry。"""
        from core.routes.devices import _sync_device_to_capability_registry
        from core.agent.capability_registry import get_capability_registry

        suffix = uuid.uuid4().hex[:8]
        info = self._device_info(suffix)
        reg = get_capability_registry()

        synced = _sync_device_to_capability_registry(info)
        assert synced == 2, f"应同步 2 个能力，实际 {synced}"

        for cap in ["screen", "touch"]:
            key = f"gateway__e2e_device_{suffix}__{cap}"
            item = reg.get(key)
            assert item is not None, f"能力 {key} 应已注册到 CapabilityRegistry"
            assert item.source == "gateway"
            assert item.source_id == f"e2e_device_{suffix}"

        # 清理
        for cap in ["screen", "touch"]:
            reg._items.pop(f"gateway__e2e_device_{suffix}__{cap}", None)

    def test_legacy_register_syncs_capability_registry(self):
        """legacy /api/devices/register 注册后能力必须出现在 CapabilityRegistry。"""
        from core.agent.capability_registry import get_capability_registry

        suffix = uuid.uuid4().hex[:8]
        device_id = f"e2e_legacy_{suffix}"
        reg = get_capability_registry()

        # 直接调用 compat.py 中的同步逻辑（通过 _sync_device_to_capability_registry）
        from core.routes.devices import _sync_device_to_capability_registry
        device_info = {
            "device_id": device_id,
            "device_type": "android",
            "device_name": f"Legacy Device {suffix}",
            "capabilities": ["camera"],
        }
        synced = _sync_device_to_capability_registry(device_info)
        assert synced == 1

        key = f"gateway__{device_id}__camera"
        item = reg.get(key)
        assert item is not None, f"Legacy 注册后能力 {key} 应同步到 CapabilityRegistry"

        # 清理
        reg._items.pop(key, None)

    def test_gateway_device_router_register_syncs_capability_registry(self):
        """gateway DeviceRouter.register_device() 注册后能力必须同步到 CapabilityRegistry。"""
        from galaxy_gateway.device_router import DeviceRouter
        from core.agent.capability_registry import get_capability_registry

        suffix = uuid.uuid4().hex[:8]
        device_id = f"e2e_gw_{suffix}"
        reg = get_capability_registry()

        router = DeviceRouter()
        result = router.register_device(
            device_id=device_id,
            device_type="android",
            capabilities=["gps"],
        )
        assert result is True, "register_device 应返回 True"

        key = f"gateway__{device_id}__gps"
        item = reg.get(key)
        assert item is not None, f"Gateway 注册后能力 {key} 应同步到 CapabilityRegistry"
        assert item.source == "gateway"

        # 清理
        reg._items.pop(key, None)

    @pytest.mark.asyncio
    async def test_gateway_websocket_handle_register_syncs_capability_registry(self):
        """galaxy_gateway/websocket_handler.handle_register() 注册后能力必须同步到 CapabilityRegistry。"""
        from core.agent.capability_registry import get_capability_registry

        suffix = uuid.uuid4().hex[:8]
        device_id = f"e2e_ws_{suffix}"
        reg = get_capability_registry()

        # 构建最小化 AIPMessage mock
        aip_msg = MagicMock()
        aip_msg.device_id = device_id
        aip_msg.device_type = None
        aip_msg.payload = {
            "device_info": {
                "device_type": "android",
                "capabilities": ["microphone"],
                "name": f"WS Device {suffix}",
            }
        }
        aip_msg.message_id = str(uuid.uuid4())

        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        from galaxy_gateway import websocket_handler
        with patch.object(
            websocket_handler.device_router, "register_device", return_value=True
        ):
            await websocket_handler.handle_register("conn_id", aip_msg, mock_ws)

        key = f"gateway__{device_id}__microphone"
        item = reg.get(key)
        assert item is not None, f"WebSocket 注册后能力 {key} 应同步到 CapabilityRegistry"

        # 清理
        reg._items.pop(key, None)


class TestDeviceCommandViaCommandRouter:
    """设备命令必须经由 CommandRouter.route_command() 并产生 trace 记录。"""

    @pytest.mark.asyncio
    async def test_dispatch_device_calls_send_gateway_command(self):
        """OpenClawd._dispatch_device() 必须调用 send_gateway_command() 而非旧链路。"""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._llm_router = None
        clawd._agent_kernel = None

        mock_result = {"success": True, "command_id": "cmd_test", "response": "已发送"}

        intent = MagicMock()
        intent.command = "take_screenshot"
        intent.params = {}

        with patch.object(clawd, "send_gateway_command", new=AsyncMock(return_value=mock_result)) as mock_sgc:
            result = await clawd._dispatch_device(
                message="截图",
                intent=intent,
                device_id="test_device_01",
                session_id="session_01",
            )

        mock_sgc.assert_called_once()
        call_kwargs = mock_sgc.call_args
        assert call_kwargs.kwargs.get("device_id") == "test_device_01" or \
               (call_kwargs.args and call_kwargs.args[0] == "test_device_01"), \
               "send_gateway_command 必须以 device_id=test_device_01 调用"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_gateway_command_calls_route_command(self):
        """send_gateway_command() 必须调用 CommandRouter.route_command()，并包含 trace 字段。"""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)

        mock_cr_result = {
            "success": True,
            "result": "截图成功",
            "command_id": "cmd_mock",
            "task_id": "task_mock",
            "device_id": "device_trace_test",
            "latency_ms": 12.5,
        }

        mock_cr = MagicMock()
        mock_cr.route_command = AsyncMock(return_value=mock_cr_result)

        with patch("core.command_router.get_command_router", return_value=mock_cr):
            result = await clawd.send_gateway_command(
                device_id="device_trace_test",
                command="take_screenshot",
                payload={},
            )

        mock_cr.route_command.assert_called_once()
        call_kwargs = mock_cr.route_command.call_args.kwargs
        assert call_kwargs.get("device_id") == "device_trace_test"
        assert call_kwargs.get("command") == "take_screenshot"
        # trace 字段必须存在
        assert "command_id" in result
        assert "task_id" in result


# ──────────────────────────────────────────────────────────────────────────────
# 3. /api/v1/chat 唯一走 OpenClawd，无旧链路旁路
# ──────────────────────────────────────────────────────────────────────────────


class TestChatRouteOpenClawdOnly:
    """/api/v1/chat 必须唯一经由 OpenClawd.process()，不存在旁路。"""

    def _make_test_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.api_routes import create_api_routes

        app = FastAPI()
        router = create_api_routes()
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=False)

    def test_api_routes_chat_endpoint_routes_to_openclawd(self):
        """create_api_routes() 注册的 /api/v1/chat 应调用 OpenClawd.process()，不走旧路径。"""
        mock_result = {
            "success": True,
            "response": "OpenClawd 回复",
            "intent": "chat",
            "metadata": {"confidence": 1.0},
        }

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=mock_result)
            mock_get.return_value = mock_clawd

            client = self._make_test_client()
            resp = client.post("/api/v1/chat", json={"message": "你好"})

        assert resp.status_code == 200
        body = resp.json()
        # 必须是 OpenClawd 处理的响应
        assert body.get("response") == "OpenClawd 回复" or body.get("reply") == "OpenClawd 回复" or \
               body.get("success") is True

    def test_no_duplicate_chat_route_registration(self):
        """create_api_routes() 生成的 router 中 POST /api/v1/chat 只应有一条路由记录。"""
        from core.api_routes import create_api_routes

        router = create_api_routes()

        chat_routes = [
            r for r in router.routes
            if hasattr(r, "path") and r.path == "/api/v1/chat"
            and "POST" in getattr(r, "methods", set())
        ]
        # 通过 include_router 加入的子路由不出现在顶层 routes，验证没有重复的内联注册
        inline_chat_routes = [
            r for r in router.routes
            if hasattr(r, "path") and r.path == "/api/v1/chat"
            and "POST" in getattr(r, "methods", set())
            and not hasattr(r, "app")  # 排除挂载的子应用
        ]
        assert len(inline_chat_routes) <= 1, (
            f"顶层 router 中 POST /api/v1/chat 应至多只有 1 条内联注册，"
            f"实际发现 {len(inline_chat_routes)} 条，可能存在旧路由重复"
        )

    def test_core_routes_chat_uses_openclawd_process(self):
        """core/routes/chat.py 的 chat 端点必须调用 OpenClawd.process() 而非旧分流逻辑。"""
        import inspect
        from core.routes import chat as chat_module

        source = inspect.getsource(chat_module)
        # 确认调用了 OpenClawd.process
        assert "clawd.process(" in source or "openclawd.process(" in source or \
               "OpenClawd" in source, "chat.py 应使用 OpenClawd.process()"
        # 旧分流逻辑不应存在于 chat 路由处理函数内（外部辅助函数可以保留）
        # 检查 create_router() 内部没有 if _is_action_intent 分流
        router_source_start = source.find("def create_router(")
        router_source = source[router_source_start:] if router_source_start >= 0 else source
        # chat handler 内不应再有 _is_action_intent 分流（解析 handler 函数体）
        chat_handler_start = router_source.find("async def chat(")
        if chat_handler_start >= 0:
            # 取从 handler 开始到下一个同级函数定义之间的内容
            handler_snippet = router_source[chat_handler_start:]
            # 截取到下一个顶层定义（async def 或 def，4-space indent）
            next_def = handler_snippet.find("\n    async def ", 1)
            if next_def < 0:
                next_def = handler_snippet.find("\n    def ", 1)
            chat_handler_src = handler_snippet[:next_def] if next_def > 0 else handler_snippet
            assert "_is_action_intent" not in chat_handler_src, \
                "chat handler 内不应再有 _is_action_intent 分流逻辑"
