"""
Tests for core/agent/ — 统一智能体内核
==========================================

Covers:
  - PolicyLoader        — 策略文件加载与缓存
  - IntentRouter        — 意图路由（chat_only / task_execute / hybrid）
  - CapabilityRegistry  — 能力注册表
  - ExecutionPlanner    — 执行规划
  - AgentKernel         — 统一内核入口
  - SOUL 注入约束        — 仅在执行链路，聊天路径不得接触 SOUL
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────── PolicyLoader ───────────────────────────

class TestPolicyLoader:
    """策略文件加载器测试。"""

    def setup_method(self):
        """每个测试前重置单例缓存。"""
        from core.agent.policy_loader import PolicyLoader
        # 重置单例以确保测试隔离
        PolicyLoader._instance = None

    def test_get_soul_returns_string(self):
        """get_soul() 返回字符串（文件存在时非空）。"""
        from core.agent.policy_loader import get_soul
        content = get_soul()
        assert isinstance(content, str)
        assert len(content) > 0, "SOUL.md 应当有内容"

    def test_get_agents_returns_string(self):
        """get_agents() 返回字符串（文件存在时非空）。"""
        from core.agent.policy_loader import get_agents
        content = get_agents()
        assert isinstance(content, str)
        assert len(content) > 0, "AGENTS.md 应当有内容"

    def test_get_user_returns_string(self):
        """get_user() 返回字符串（文件存在时非空）。"""
        from core.agent.policy_loader import get_user
        content = get_user()
        assert isinstance(content, str)
        assert len(content) > 0, "USER.md 应当有内容"

    def test_missing_policy_returns_empty(self, tmp_path, monkeypatch):
        """策略文件不存在时返回空字符串，不抛出异常。"""
        from core.agent import policy_loader
        monkeypatch.setattr(policy_loader, "_POLICIES_DIR", tmp_path)
        # 重置单例
        policy_loader._loader = policy_loader.PolicyLoader.__new__(policy_loader.PolicyLoader)
        policy_loader._loader._initialized = False
        policy_loader._loader.__init__()
        policy_loader._loader._cache.clear()

        result = policy_loader._loader.get_soul()
        assert result == ""

    def test_reload_clears_cache(self):
        """reload() 清除缓存，下次访问重新读取。"""
        from core.agent import policy_loader as pl
        # 使用模块级 _loader（唯一真正的单例）
        loader = pl._loader
        # 先加载一次填充缓存
        _ = loader.get_soul()
        assert "SOUL" in loader._cache
        pl.reload_policies()
        assert len(loader._cache) == 0

    def test_caching_returns_same_content(self):
        """连续两次调用返回相同内容（缓存命中）。"""
        from core.agent.policy_loader import get_soul
        first = get_soul()
        second = get_soul()
        assert first == second

    def test_soul_content_contains_key_sections(self):
        """SOUL.md 内容应包含角色定义和能力边界章节。"""
        from core.agent.policy_loader import get_soul
        content = get_soul()
        assert "角色定义" in content or "role" in content.lower()

    def test_agents_content_contains_workflow(self):
        """AGENTS.md 应包含工作流程相关内容。"""
        from core.agent.policy_loader import get_agents
        content = get_agents()
        assert "工作流程" in content or "workflow" in content.lower()

    def test_user_content_contains_preferences(self):
        """USER.md 应包含偏好相关内容。"""
        from core.agent.policy_loader import get_user
        content = get_user()
        assert "偏好" in content or "preference" in content.lower()


# ─────────────────────────── IntentRouter ───────────────────────────

class TestIntentRouter:
    """意图路由器测试。"""

    @pytest.fixture
    def router(self):
        from core.agent.intent_router import IntentRouter
        return IntentRouter(llm_router=None)

    @pytest.mark.asyncio
    async def test_chat_only_for_greeting(self, router):
        """问候语应被分类为 chat_only。"""
        result = await router.route("你好，今天天气怎么样？")
        assert result.mode == "chat_only"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_task_execute_for_device_command(self, router):
        """设备操控指令应被分类为 task_execute。"""
        result = await router.route("帮我截图")
        assert result.mode == "task_execute"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_task_execute_for_file_operation(self, router):
        """文件操作指令应被分类为 task_execute。"""
        result = await router.route("打开桌面上的文件夹")
        assert result.mode == "task_execute"

    @pytest.mark.asyncio
    async def test_task_execute_english(self, router):
        """英文任务指令应被正确分类。"""
        result = await router.route("take a screenshot of my screen")
        assert result.mode == "task_execute"

    @pytest.mark.asyncio
    async def test_hybrid_when_chat_and_task_mixed(self, router):
        """聊天+任务混合时应为 hybrid 或 task_execute。"""
        result = await router.route("你好，帮我截个图看看桌面")
        # 含任务词"截图"，应为 task 或 hybrid
        assert result.mode in ("task_execute", "hybrid")

    @pytest.mark.asyncio
    async def test_short_message_is_chat(self, router):
        """极短消息应为 chat_only。"""
        result = await router.route("hi")
        assert result.mode == "chat_only"

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, router):
        """IntentResult 必须包含所有必填字段。"""
        result = await router.route("打开应用")
        assert hasattr(result, "mode")
        assert hasattr(result, "confidence")
        assert hasattr(result, "task_hint")
        assert hasattr(result, "raw_intent")
        assert hasattr(result, "method")
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_is_execution_helper(self, router):
        """is_execution() 对 task/hybrid 返回 True，对 chat 返回 False。"""
        chat_result = await router.route("你好")
        task_result = await router.route("帮我运行代码")
        assert not chat_result.is_execution()
        assert task_result.is_execution()

    @pytest.mark.asyncio
    async def test_llm_not_called_for_high_confidence(self, router):
        """高置信度规则分类时不应调用 LLM。"""
        mock_llm = AsyncMock()
        router._llm_router = mock_llm
        # 明确的任务指令，规则置信度应 >= 0.6
        result = await router.route("帮我截屏", use_llm=True, llm_confidence_threshold=0.6)
        assert result.mode == "task_execute"
        # LLM 不应被调用（规则已足够）
        mock_llm.chat.assert_not_called()


# ─────────────────────────── CapabilityRegistry ───────────────────────────

class TestCapabilityRegistry:
    """能力注册表测试。"""

    def setup_method(self):
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None

    def test_singleton(self):
        """CapabilityRegistry 应为单例。"""
        from core.agent.capability_registry import CapabilityRegistry
        a = CapabilityRegistry()
        b = CapabilityRegistry()
        assert a is b

    def test_register_and_get(self):
        """手动注册能力后可通过 get() 获取。"""
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry()
        item = CapabilityItem(
            name="test_tool",
            description="测试工具",
            source="test",
        )
        reg.register(item)
        found = reg.get("test_tool")
        assert found is not None
        assert found.name == "test_tool"

    def test_find_by_keyword(self):
        """find() 应按关键词搜索名称和描述。"""
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry()
        reg.register(CapabilityItem(name="file_writer", description="写入文件", source="test"))
        results = reg.find("文件")
        assert any(i.name == "file_writer" for i in results)

    def test_list_tools_returns_available_only(self):
        """list_tools() 只返回 available=True 的条目。"""
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry()
        reg.register(CapabilityItem(name="online_tool", description="在线工具", source="test", available=True))
        reg.register(CapabilityItem(name="offline_tool", description="离线工具", source="test", available=False))
        tools = reg.list_tools()
        names = [t.name for t in tools]
        assert "online_tool" in names
        assert "offline_tool" not in names

    def test_to_tool_schemas(self):
        """to_tool_schemas() 返回正确的 OpenAI function calling 格式。"""
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry()
        reg.register(CapabilityItem(name="my_func", description="测试函数", source="test"))
        schemas = reg.to_tool_schemas()
        schema = next((s for s in schemas if s["function"]["name"] == "my_func"), None)
        assert schema is not None
        assert schema["type"] == "function"
        assert "description" in schema["function"]

    def test_stats(self):
        """stats() 返回正确的统计信息。"""
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry()
        # 清空
        reg._items.clear()
        reg.register(CapabilityItem(name="a", description="a", source="mcp"))
        reg.register(CapabilityItem(name="b", description="b", source="skill"))
        stats = reg.stats()
        assert stats["total"] == 2
        assert stats["by_source"]["mcp"] == 1
        assert stats["by_source"]["skill"] == 1

    @pytest.mark.asyncio
    async def test_refresh_with_mocked_loaders(self):
        """refresh() 在 MCP/Skill/Gateway 均不可用时不崩溃。"""
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry()
        reg._items.clear()
        reg._last_refresh = 0.0
        # 所有依赖均 mock 失败
        with patch("core.agent.capability_registry.CapabilityRegistry._load_mcp", new_callable=AsyncMock) as m_mcp, \
             patch("core.agent.capability_registry.CapabilityRegistry._load_skills", new_callable=AsyncMock) as m_skill, \
             patch("core.agent.capability_registry.CapabilityRegistry._load_gateway", new_callable=AsyncMock) as m_gw:
            await reg.refresh(force=True)
        # 不抛出异常即通过


# ─────────────────────────── AgentKernel ───────────────────────────

class TestAgentKernel:
    """统一智能体内核测试。"""

    def setup_method(self):
        from core.agent.kernel import AgentKernel
        AgentKernel._instance = None

    def test_singleton(self):
        """AgentKernel 应为单例。"""
        from core.agent.kernel import AgentKernel, get_kernel
        a = get_kernel()
        b = get_kernel()
        assert a is b

    @pytest.mark.asyncio
    async def test_chat_message_does_not_load_soul(self):
        """纯聊天消息不应加载 SOUL 策略。"""
        from core.agent import kernel as kernel_mod
        from core.agent.policy_loader import PolicyLoader

        # 重置内核单例
        kernel_mod._kernel = None
        kernel_mod.AgentKernel._instance = None

        soul_calls = []
        original_soul = PolicyLoader.get_soul

        def tracking_soul(self):
            soul_calls.append(1)
            return original_soul(self)

        kernel = kernel_mod.get_kernel()

        # Mock _handle_chat 以避免需要真实 LLM
        async def fake_handle_chat(message, session_id, context, user_policy, task_hint=""):
            from core.agent.kernel import KernelResponse
            from core.agent.intent_router import IntentMode
            return KernelResponse(
                success=True, mode=IntentMode.CHAT_ONLY, reply="你好！"
            )

        with patch.object(kernel, "_handle_chat", side_effect=fake_handle_chat), \
             patch.object(PolicyLoader, "get_soul", tracking_soul):
            result = await kernel.handle_message("你好，今天天气怎么样？")

        # 聊天路径不应调用 get_soul
        assert len(soul_calls) == 0, "纯聊天路径不得加载 SOUL"
        assert result.mode == "chat_only"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_task_message_loads_soul(self):
        """任务执行消息必须加载 SOUL 策略。"""
        from core.agent import kernel as kernel_mod
        from core.agent.policy_loader import PolicyLoader

        kernel_mod._kernel = None
        kernel_mod.AgentKernel._instance = None

        soul_calls = []
        original_soul = PolicyLoader.get_soul

        def tracking_soul(self):
            soul_calls.append(1)
            return original_soul(self)

        kernel = kernel_mod.get_kernel()

        # Mock execution planner to avoid real agent calls
        from core.agent.execution_planner import ExecutionResult, ExecutionPlanner

        async def fake_execute(plan):
            from core.agent.intent_router import IntentMode
            return ExecutionResult(
                success=True,
                mode="single_agent",
                reply="截图已完成",
            )

        with patch.object(ExecutionPlanner, "execute", side_effect=fake_execute), \
             patch.object(PolicyLoader, "get_soul", tracking_soul):
            result = await kernel.handle_message("帮我截图")

        # 执行路径必须调用 get_soul
        assert len(soul_calls) > 0, "执行路径必须加载 SOUL"
        assert result.mode in ("task_execute", "hybrid")

    @pytest.mark.asyncio
    async def test_kernel_response_has_required_fields(self):
        """KernelResponse 必须包含所有规定字段。"""
        from core.agent import kernel as kernel_mod
        from core.agent.kernel import KernelResponse
        from core.agent.intent_router import IntentMode

        kernel_mod._kernel = None
        kernel_mod.AgentKernel._instance = None
        kernel = kernel_mod.get_kernel()

        async def fake_handle_chat(message, session_id, context, user_policy, task_hint=""):
            return KernelResponse(
                success=True, mode=IntentMode.CHAT_ONLY, reply="测试回复"
            )

        with patch.object(kernel, "_handle_chat", side_effect=fake_handle_chat):
            result = await kernel.handle_message("你好")

        assert hasattr(result, "success")
        assert hasattr(result, "mode")
        assert hasattr(result, "reply")
        assert hasattr(result, "agent_steps")
        assert hasattr(result, "tool_calls")
        assert hasattr(result, "task_result")

    @pytest.mark.asyncio
    async def test_kernel_timeout_returns_error_response(self):
        """超时时内核应返回 success=False 的错误响应，不抛出异常。"""
        from core.agent import kernel as kernel_mod

        kernel_mod._kernel = None
        kernel_mod.AgentKernel._instance = None
        kernel = kernel_mod.get_kernel()

        async def slow_process(*args, **kwargs):
            await asyncio.sleep(999)

        with patch.object(kernel, "_process", side_effect=slow_process):
            result = await kernel.handle_message("帮我截图", timeout=0.05)

        assert result.success is False
        assert result.error == "timeout"
        assert "超时" in result.reply

    @pytest.mark.asyncio
    async def test_to_api_dict_compatibility(self):
        """to_api_dict() 必须包含向后兼容的 'response' 字段。"""
        from core.agent.kernel import KernelResponse
        from core.agent.intent_router import IntentResult

        resp = KernelResponse(
            success=True,
            mode="chat_only",
            reply="测试",
        )
        d = resp.to_api_dict()
        assert "reply" in d
        assert "response" in d  # 向后兼容
        assert "success" in d
        assert "mode" in d
        assert "agent_steps" in d
        assert "tool_calls" in d

    def test_get_status_returns_dict(self):
        """get_status() 返回包含内核关键信息的 dict。"""
        from core.agent import kernel as kernel_mod
        kernel_mod._kernel = None
        kernel_mod.AgentKernel._instance = None
        kernel = kernel_mod.get_kernel()
        status = kernel.get_status()
        assert isinstance(status, dict)
        assert "kernel" in status
        assert "llm_available" in status
        assert "soul_policy_loaded" in status


# ─────────────────────────── SOUL 注入约束 ───────────────────────────

class TestSoulInjectionConstraint:
    """验证 SOUL 仅在执行链路注入的核心约束。"""

    @pytest.mark.asyncio
    async def test_soul_not_in_chat_plan(self):
        """chat_only 意图构建的执行计划不应包含 SOUL 内容。"""
        from core.agent.kernel import AgentKernel
        from core.agent.intent_router import IntentResult, IntentMode

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()  # 确保 _intent_router 已初始化

        # 构造 chat_only 意图
        chat_intent = IntentResult(mode=IntentMode.CHAT_ONLY, confidence=0.9)

        # 验证：chat_only 路径 _process 调用 get_soul 次数为 0
        soul_loaded = []

        from core.agent import policy_loader

        original_get_soul = policy_loader.get_soul

        def spy_soul():
            soul_loaded.append(True)
            return original_get_soul()

        async def fake_chat(message, session_id, context, user_policy, task_hint=""):
            from core.agent.kernel import KernelResponse
            return KernelResponse(success=True, mode="chat_only", reply="ok")

        with patch("core.agent.kernel.get_soul", spy_soul), \
             patch.object(kernel, "_handle_chat", side_effect=fake_chat), \
             patch("core.agent.kernel.get_agents", return_value="agents"), \
             patch("core.agent.kernel.get_user", return_value="user"), \
             patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=chat_intent):
            await kernel._process("你好", "s1", "", [])

        assert len(soul_loaded) == 0, "chat_only 路径中 get_soul 不应被调用"

    @pytest.mark.asyncio
    async def test_soul_in_task_execution_plan(self):
        """task_execute 意图应将 SOUL 内容注入执行计划。"""
        from core.agent.kernel import AgentKernel
        from core.agent.intent_router import IntentResult, IntentMode
        from core.agent.execution_planner import ExecutionPlanner, ExecutionResult

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()

        task_intent = IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=0.9,
            task_hint="截图",
        )

        received_plans = []

        async def capture_plan(plan):
            received_plans.append(plan)
            return ExecutionResult(success=True, mode="single_agent", reply="ok")

        with patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=task_intent), \
             patch.object(kernel._planner, "execute", side_effect=capture_plan), \
             patch("core.agent.kernel.get_soul", return_value="SOUL_CONTENT"), \
             patch("core.agent.kernel.get_agents", return_value="agents"), \
             patch("core.agent.kernel.get_user", return_value="user"):
            await kernel._process("帮我截图", "s1", "", [])

        assert len(received_plans) == 1
        assert received_plans[0].soul_policy == "SOUL_CONTENT", \
            "task_execute 计划必须包含 SOUL 内容"
