"""
PR86 回归测试 — 架构对齐验收
================================

验收清单：
  1. /api/v1/chat 只调用 OpenClawd（无 AgentKernel 前置）
  2. AgentKernel 由 OpenClawd 内部嵌入调用
  3. 新增 MCP/Skill 后可通过自然语言调用
  4. 新设备注册后 OpenClawd 立即可感知并同步到 capability bus
  5. 模型 fallback 生效
  6. SOUL 注入规则：chat_only 不注 SOUL；task_execute/hybrid 强制注 SOUL
  7. 网关统一命令路径含 trace ID
  8. CapabilityRegistry 在 ExecutionPlanner 中强制使用
  9. MCP/Skill 热重载返回可观测状态
"""

import asyncio
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────────────


def _make_kernel_response(mode="chat_only", reply="OK", model="gpt-4o"):
    """构建一个最小化的 KernelResponse mock。"""
    from core.agent.kernel import KernelResponse
    from core.agent.intent_router import IntentResult
    return KernelResponse(
        success=True,
        mode=mode,
        reply=reply,
        model=model,
        session_id="test-session",
        intent=IntentResult(mode=mode, raw_intent=mode, confidence=0.9),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. OpenClawd 是 /api/v1/chat 的唯一入口
# ──────────────────────────────────────────────────────────────────────────────


class TestOpenClawdSoleEntrypoint:
    """验证 /api/v1/chat 只通过 OpenClawd 处理请求，不直接调用 AgentKernel。"""

    def test_create_router_does_not_import_kernel_directly(self):
        """create_router 返回的路由不应在 chat 处理函数中直接 import AgentKernel。"""
        import ast
        import pathlib

        chat_file = pathlib.Path(__file__).parent.parent / "core" / "routes" / "chat.py"
        source = chat_file.read_text(encoding="utf-8")

        # chat 函数内不应该有直接导入 kernel 的语句
        # 整个 chat.py 中不允许出现 "from core.agent.kernel import" 这种直接导入
        assert "from core.agent.kernel import" not in source, (
            "core/routes/chat.py 不应直接导入 AgentKernel — "
            "Kernel 必须通过 OpenClawd 内部调用，不在路由层直接使用"
        )

    def test_chat_route_calls_openclawd(self):
        """create_router 中的 chat 端点必须调用 OpenClawd.process()。"""
        import pathlib

        chat_file = pathlib.Path(__file__).parent.parent / "core" / "routes" / "chat.py"
        source = chat_file.read_text(encoding="utf-8")

        assert "get_openclawd" in source or "OpenClawd" in source, (
            "chat.py 必须调用 OpenClawd"
        )
        assert "clawd.process" in source, (
            "chat.py 必须调用 clawd.process()"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 2. AgentKernel 由 OpenClawd 内部嵌入
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentKernelEmbedded:
    """验证 AgentKernel 由 OpenClawd 内部持有和调用。"""

    def test_openclawd_has_kernel_attribute(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        assert hasattr(oc, "_kernel"), "OpenClawd 必须有 _kernel 属性（内嵌 AgentKernel）"

    def test_openclawd_has_get_kernel_method(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        assert hasattr(oc, "_get_kernel"), "OpenClawd 必须有 _get_kernel() 方法"
        assert callable(oc._get_kernel)

    def test_openclawd_process_accepts_context(self):
        """process() 必须接受 context 参数（传递对话历史给 Kernel）。"""
        import inspect
        from core.openclawd import OpenClawd
        sig = inspect.signature(OpenClawd.process)
        assert "context" in sig.parameters, (
            "OpenClawd.process() 必须接受 context 参数"
        )

    @pytest.mark.asyncio
    async def test_openclawd_process_uses_kernel(self):
        """process() 内部应调用 _get_kernel() 并通过 kernel.handle_message() 处理。"""
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        oc._initialized = False

        mock_kernel = AsyncMock()
        mock_kernel.handle_message = AsyncMock(return_value=_make_kernel_response())

        with patch.object(oc, "_get_kernel", return_value=mock_kernel):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                result = await oc.process("hello", session_id="test-session")

        assert result["success"] is True
        mock_kernel.handle_message.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 3. 新 MCP/Skill 可通过自然语言调用（热重载后 CapabilityRegistry 更新）
# ──────────────────────────────────────────────────────────────────────────────


class TestMCPSkillHotReload:
    """验证 MCP/Skill 热重载后能力立即可用。"""

    @pytest.mark.asyncio
    async def test_reload_mcp_returns_status(self):
        """reload_mcp() 返回包含 loaded/validated 字段的状态。"""
        from core.mcp_skill_reload import reload_mcp

        mock_loader = MagicMock()
        mock_loader.list_tools = AsyncMock(return_value=[
            {"name": "test_tool", "description": "Test tool", "input_schema": {}},
        ])
        mock_loader.list_servers = MagicMock(return_value={})

        mock_mcp_cls = MagicMock()
        mock_mcp_cls.get_instance = MagicMock(return_value=mock_loader)

        mock_cap_reg = AsyncMock()
        mock_cap_reg.refresh = AsyncMock()

        with patch("core.mcp_loader.MCPLoader", mock_mcp_cls):
            with patch("core.agent.capability_registry.get_capability_registry",
                       return_value=mock_cap_reg):
                result = await reload_mcp("test_server")

        assert "loaded" in result
        assert "server_id" in result
        assert result["server_id"] == "test_server"

    @pytest.mark.asyncio
    async def test_reload_skill_returns_status(self):
        """reload_skill() 返回包含 loaded/validated 字段的状态。"""
        from core.mcp_skill_reload import reload_skill

        mock_skill = MagicMock()
        mock_skill.name = "test_skill"
        mock_skill.description = "Test skill"
        mock_skill.handler = lambda: None
        mock_skill.version = "1.0.0"

        mock_loader = MagicMock()
        mock_loader.reload_skill = AsyncMock(return_value=mock_skill)

        mock_skill_cls = MagicMock()
        mock_skill_cls.get_instance = MagicMock(return_value=mock_loader)

        mock_cap_reg = AsyncMock()
        mock_cap_reg.refresh = AsyncMock()

        with patch("core.skill_loader.SkillLoader", mock_skill_cls):
            with patch("core.agent.capability_registry.get_capability_registry",
                       return_value=mock_cap_reg):
                result = await reload_skill("test_skill_id")

        assert "loaded" in result
        assert result["skill_id"] == "test_skill_id"

    def test_get_load_status_returns_dict(self):
        """get_load_status() 返回 {mcp: ..., skills: ...} 字典。"""
        from core.mcp_skill_reload import get_load_status

        mock_mcp_loader = MagicMock()
        mock_mcp_loader.get_instance.return_value = MagicMock(
            list_servers=MagicMock(return_value={})
        )
        mock_skill_loader = MagicMock()
        mock_skill_loader.get_instance.return_value = MagicMock(
            list_skills=MagicMock(return_value=[])
        )

        with patch("core.mcp_loader.MCPLoader", mock_mcp_loader):
            with patch("core.skill_loader.SkillLoader", mock_skill_loader):
                status = get_load_status()

        assert "mcp" in status
        assert "skills" in status


# ──────────────────────────────────────────────────────────────────────────────
# 4. 新设备注册后 OpenClawd 感知并同步到 capability bus
# ──────────────────────────────────────────────────────────────────────────────


class TestDeviceRegistrationVisible:
    """验证新设备注册后 OpenClawd 能感知并将其纳入 capability bus。"""

    def test_openclawd_has_sync_device_capabilities(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        assert hasattr(oc, "sync_device_capabilities"), (
            "OpenClawd 必须有 sync_device_capabilities() 方法"
        )
        assert callable(oc.sync_device_capabilities)

    def test_sync_device_capabilities_registers_to_capability_bus(self):
        """新设备的能力应被注册到 CapabilityRegistry。"""
        from core.openclawd import OpenClawd
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem

        oc = OpenClawd()

        # 构造一个包含设备能力的 mock DeviceRegistry
        mock_device = {
            "device_name": "Android_01",
            "device_type": "android",
            "capabilities": ["screenshot", "touch", "keyboard"],
        }
        mock_registry_instance = MagicMock()
        mock_registry_instance.list_devices = MagicMock(return_value={"device_001": mock_device})

        mock_device_registry_cls = MagicMock()
        mock_device_registry_cls.get_instance = MagicMock(return_value=mock_registry_instance)

        # 获取 CapabilityRegistry 实例，监控 register 调用
        cap_reg = CapabilityRegistry.get_instance()
        registered_keys = []
        original_register = cap_reg.register

        def _capture_register(item: CapabilityItem):
            registered_keys.append(item.name)
            original_register(item)

        mock_cap_reg_cls = MagicMock()
        mock_cap_reg_cls.get_instance = MagicMock(return_value=cap_reg)

        with patch("core.device_registry.DeviceRegistry", mock_device_registry_cls):
            with patch("core.agent.capability_registry.CapabilityRegistry", mock_cap_reg_cls):
                with patch.object(cap_reg, "register", side_effect=_capture_register):
                    count = oc.sync_device_capabilities()

        assert count == len(mock_device["capabilities"])  # screenshot + touch + keyboard
        assert any("device_001" in k for k in registered_keys)


# ──────────────────────────────────────────────────────────────────────────────
# 5. 模型 fallback 生效
# ──────────────────────────────────────────────────────────────────────────────


class TestModelFallback:
    """验证主模型失败时 Router 自动切换到 fallback 提供商。"""

    @pytest.mark.asyncio
    async def test_router_fallback_on_primary_failure(self):
        """当主提供商抛出异常时，Router 应切换到备用提供商。"""
        from core.multi_llm_router import MultiLLMRouter, ProviderConfig, LLMResponse

        router = MultiLLMRouter.__new__(MultiLLMRouter)
        router.providers = {}
        router.adapters = {}
        router.circuit_breakers = {}
        router.call_history = []
        router._last_provider = ""
        router._last_model = ""
        router._lock = asyncio.Lock()

        # 主提供商（失败）
        primary_cfg = ProviderConfig(
            name="primary", api_key="test-key",
            base_url="https://example.com",
            models=["model-a"], default_model="model-a",
        )
        primary_adapter = MagicMock()
        primary_adapter.chat = AsyncMock(side_effect=Exception("primary down"))

        # 备用提供商（成功）
        fallback_cfg = ProviderConfig(
            name="fallback", api_key="fallback-key",
            base_url="https://fallback.com",
            models=["model-b"], default_model="model-b",
        )
        fallback_response = LLMResponse(
            content="fallback response",
            provider="fallback", model="model-b",
            input_tokens=10, output_tokens=20,
        )
        fallback_adapter = MagicMock()
        fallback_adapter.chat = AsyncMock(return_value=fallback_response)

        router.providers["primary"] = primary_cfg
        router.providers["fallback"] = fallback_cfg
        router.adapters["primary"] = primary_adapter
        router.adapters["fallback"] = fallback_adapter

        from core.multi_llm_router import ProviderCircuitBreaker
        router.circuit_breakers["primary"] = ProviderCircuitBreaker("primary")
        router.circuit_breakers["fallback"] = ProviderCircuitBreaker("fallback")

        # 构造 RoutingDecision，包含 fallback 候选
        from core.multi_llm_router import RoutingDecision
        with patch.object(router, "route") as mock_route:
            from core.multi_llm_router import TaskType
            mock_route.return_value = RoutingDecision(
                provider="primary", model="model-a",
                reason="test",
                alternatives=["fallback:model-b"],
            )
            with patch.object(router, "classify_task", return_value=TaskType.GENERAL):
                with patch.object(router, "_compute_complexity_vector") as mock_cv:
                    mock_cv.return_value = MagicMock(
                        weighted_score=0.3, tier=MagicMock(value="lite"),
                        model_dump=lambda: {},
                    )
                    response = await router.chat([{"role": "user", "content": "test"}])

        assert response.content == "fallback response"
        assert router._last_provider == "fallback"

    def test_router_config_priority_reads_dashboard_first(self):
        """_get_key() 应先尝试读取 Dashboard/UnifiedConfig，再读 ENV。"""
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter.__new__(MultiLLMRouter)
        router.providers = {}
        router.adapters = {}
        router.circuit_breakers = {}
        router.call_history = []
        router._last_provider = ""
        router._last_model = ""
        router._lock = asyncio.Lock()

        # 构建一个 mock config 对象，使 `config.get("llm.providers.openai.api_key")` 返回值
        mock_cfg = MagicMock()
        mock_cfg.get = MagicMock(side_effect=lambda k, default="": (
            "dashboard-key" if "openai" in k else ""
        ))

        with patch("core.unified_config.config", mock_cfg):
            key = router._get_key("openai")

        assert key == "dashboard-key", (
            "_get_key() 应从 Dashboard 配置优先读取 API key"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 6. SOUL 注入规则
# ──────────────────────────────────────────────────────────────────────────────


class TestSOULInjectionRules:
    """验证 SOUL 注入规则：chat_only 不注入，task_execute/hybrid 强制注入。"""

    @pytest.mark.asyncio
    async def test_chat_only_no_soul_injection(self):
        """chat_only 模式的 Kernel 处理不应注入 SOUL 策略。"""
        from core.agent.kernel import AgentKernel
        from core.agent.intent_router import IntentMode

        kernel = AgentKernel()
        kernel._initialized = True

        # Mock IntentRouter 返回 chat_only
        mock_intent_router = MagicMock()
        from core.agent.intent_router import IntentResult
        mock_intent_router.route = AsyncMock(return_value=IntentResult(
            mode=IntentMode.CHAT_ONLY,
            raw_intent="chat_only",
            confidence=0.95,
        ))
        kernel._intent_router = mock_intent_router

        # Mock LLM router
        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "纯聊天回复"
        mock_response.model = "gpt-4o"
        mock_response.provider = "openai"
        mock_response.tool_calls = None
        mock_router.chat = AsyncMock(return_value=mock_response)
        kernel._llm_router = mock_router

        # Mock policy_loader (SOUL should NOT be loaded)
        with patch("core.agent.kernel.get_soul") as mock_soul:
            mock_soul.return_value = "SOUL content"
            with patch("core.agent.kernel.get_agents") as mock_agents:
                mock_agents.return_value = "AGENTS content"
                with patch("core.agent.kernel.get_user") as mock_user:
                    mock_user.return_value = "USER content"
                    result = await kernel.handle_message("你好", session_id="test")

        # chat_only 下 SOUL 不应被加载到执行上下文中
        assert result.mode == IntentMode.CHAT_ONLY
        # 在 chat_only 路径中 get_soul 不应被调用
        mock_soul.assert_not_called(), "chat_only 路径禁止调用 get_soul()"

    @pytest.mark.asyncio
    async def test_task_execute_injects_soul(self):
        """task_execute 模式下必须注入 SOUL 策略。"""
        from core.agent.kernel import AgentKernel
        from core.agent.intent_router import IntentMode, IntentResult

        kernel = AgentKernel()
        kernel._initialized = True

        mock_intent_router = MagicMock()
        mock_intent_router.route = AsyncMock(return_value=IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            raw_intent="task_execute",
            confidence=0.9,
            task_hint="do something",
        ))
        kernel._intent_router = mock_intent_router

        mock_planner = MagicMock()
        from core.agent.execution_planner import ExecutionResult
        mock_planner.execute = AsyncMock(return_value=ExecutionResult(
            success=True,
            mode="task_execute",
            reply="任务完成",
        ))
        kernel._planner = mock_planner

        with patch("core.agent.kernel.get_soul", return_value="SOUL") as mock_soul:
            with patch("core.agent.kernel.get_agents", return_value="AGENTS"):
                with patch("core.agent.kernel.get_user", return_value="USER"):
                    result = await kernel.handle_message("执行任务", session_id="test")

        assert result.mode == IntentMode.TASK_EXECUTE
        mock_soul.assert_called_once(), "task_execute 路径必须调用 get_soul()"

        # 确认 SOUL 被传入 plan
        call_args = mock_planner.execute.call_args
        plan = call_args[0][0] if call_args[0] else call_args.kwargs.get("plan")
        if plan is not None:
            assert plan.soul_policy == "SOUL", "ExecutionPlan 必须包含 SOUL 策略"


# ──────────────────────────────────────────────────────────────────────────────
# 7. 网关统一命令路径含 trace ID
# ──────────────────────────────────────────────────────────────────────────────


class TestGatewayTraceID:
    """验证网关命令路径包含 trace ID (command_id/task_id)。"""

    @pytest.mark.asyncio
    async def test_send_gateway_command_has_trace_ids(self):
        """send_gateway_command() 返回的结果必须包含 command_id 和 task_id。"""
        from core.openclawd import OpenClawd
        oc = OpenClawd()

        # 当所有连接路径都失败时，command_id/task_id 仍应存在于返回值中
        # 用 monkeypatch 方式：直接测试包含 command_id/task_id 的核心逻辑
        result = await oc.send_gateway_command(
            device_id="device_001",
            command="screenshot",
            payload={"quality": "high"},
            task_id="task_xyz",
        )

        assert "command_id" in result, "命令结果必须包含 command_id (trace ID)"
        assert "task_id" in result, "命令结果必须包含 task_id (trace ID)"
        assert result["device_id"] == "device_001"
        assert result["command"] == "screenshot"
        assert result["task_id"] == "task_xyz"

    @pytest.mark.asyncio
    async def test_send_gateway_command_logs_trace(self):
        """send_gateway_command() 必须记录包含 trace 字段的日志。"""
        from core.openclawd import OpenClawd
        import logging
        oc = OpenClawd()

        log_records = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                log_records.append(record.getMessage())

        handler = CapturingHandler()
        galaxy_logger = logging.getLogger("Galaxy.OpenClawd")
        old_level = galaxy_logger.level
        galaxy_logger.setLevel(logging.INFO)
        galaxy_logger.addHandler(handler)

        try:
            await oc.send_gateway_command("dev_01", "tap", {"x": 100, "y": 200})
        finally:
            galaxy_logger.removeHandler(handler)
            galaxy_logger.setLevel(old_level)

        assert any("command_id" in msg for msg in log_records), (
            f"send_gateway_command 日志必须包含 command_id，实际日志: {log_records[:5]}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 8. CapabilityRegistry 在 ExecutionPlanner 中强制使用
# ──────────────────────────────────────────────────────────────────────────────


class TestCapabilityRegistryMandatory:
    """验证 ExecutionPlanner 在执行前强制刷新并使用 CapabilityRegistry。"""

    @pytest.mark.asyncio
    async def test_execution_planner_calls_capability_registry(self):
        """ExecutionPlanner.execute() 必须调用 CapabilityRegistry.refresh()。"""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        plan = ExecutionPlan(
            message="打开文件",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
            ),
            timeout=10.0,
        )

        mock_reg = AsyncMock()
        mock_reg.refresh = AsyncMock()
        mock_reg.list_tools = MagicMock(return_value=[])
        mock_reg.stats = MagicMock(return_value={"total": 0, "available": 0, "by_source": {}})

        with patch("core.agent.capability_registry.get_capability_registry", return_value=mock_reg):
            with patch.object(planner, "_dispatch") as mock_dispatch:
                from core.agent.execution_planner import ExecutionResult
                mock_dispatch.return_value = ExecutionResult(
                    success=True, mode="single_agent", reply="done"
                )
                result = await planner.execute(plan)

        mock_reg.refresh.assert_called_once(), (
            "ExecutionPlanner 必须在执行前调用 CapabilityRegistry.refresh()"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 9. OpenClawd 持有 Router，process() 包含 request_id
# ──────────────────────────────────────────────────────────────────────────────


class TestOpenClawdRouterAndTracing:
    """验证 OpenClawd 持有 Router 实例，且 process() 返回 request_id。"""

    def test_openclawd_has_router_attribute(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        assert hasattr(oc, "_router"), "OpenClawd 必须有 _router 属性（持有 Router）"
        assert hasattr(oc, "_get_router"), "OpenClawd 必须有 _get_router() 方法"

    @pytest.mark.asyncio
    async def test_process_returns_request_id(self):
        """process() 返回的 metadata 必须包含 request_id（trace ID）。"""
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        oc._initialized = False

        mock_kernel = AsyncMock()
        mock_kernel.handle_message = AsyncMock(return_value=_make_kernel_response())

        with patch.object(oc, "_get_kernel", return_value=mock_kernel):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                result = await oc.process("test", session_id="sess_abc")

        assert "request_id" in result["metadata"], (
            "process() 返回的 metadata 必须包含 request_id (trace ID)"
        )
        assert result["metadata"]["request_id"], "request_id 不能为空"
