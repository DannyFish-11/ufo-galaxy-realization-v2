"""
E2E 集成加固冒烟测试 — Phase 5
================================

验证超时防护、容错兜底、混沌防御等加固措施是否生效。
不依赖真实 LLM API，使用 Mock/Stub 模拟极端场景。
"""

import asyncio
import json
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# 测试夹具
# ============================================================================


@pytest.fixture
def openclawd(monkeypatch):
    """创建 OpenClawd 实例"""
    # 断言漂移修正(生产契约演进,PR-10):_collect_tools 的规范 Node 工具
    # 来源改为 NodeFabricRegistry 运行时注册(节点进程启动时上报),
    # config/node_registry.json + fusion_entry 的直接扫描已从规范路径移除,
    # 仅保留在显式兼容开关 OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED 之后。
    # 单测进程内没有真实节点起来注册,fabric 注册表为空;本测试验证的是
    # 工具总线的收集/分发链路本身,故按 PR-10 提供的兼容途径打开扫描开关。
    monkeypatch.setenv("OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED", "true")
    from core.openclawd import OpenClawd

    return OpenClawd()


@dataclass
class FakeLLMResponse:
    """模拟 LLM 响应"""

    content: str = "test response"
    provider: str = "mock"
    model: str = "mock-model"
    input_tokens: int = 10
    output_tokens: int = 20
    tool_calls: list = None


# ============================================================================
# Test 1: Node 工具收集 + 分发（真实路径）
# ============================================================================


class TestNodeIntegration:
    """验证 Node 工具总线第三层真正接入"""

    def test_collect_tools_includes_nodes(self, openclawd):
        """_collect_tools() 应包含 node__ 前缀工具"""
        tools = openclawd._collect_tools()
        node_tools = [t for t in tools if t["function"]["name"].startswith("node__")]
        assert len(node_tools) >= 10, f"期望至少 10 个 node 工具，实际 {len(node_tools)}"
        # 验证核心节点存在
        names = {t["function"]["name"] for t in node_tools}
        assert "node__06__read" in names, "缺少 Filesystem 读文件工具"
        assert "node__07__status" in names, "缺少 Git 状态工具"
        assert "node__09__execute" in names, "缺少 Sandbox 执行工具"

    def test_collect_tools_has_descriptions(self, openclawd):
        """Node 工具应有中文描述"""
        tools = openclawd._collect_tools()
        node_tools = [t for t in tools if t["function"]["name"].startswith("node__")]
        for tool in node_tools:
            desc = tool["function"]["description"]
            assert desc and len(desc) > 5, f"{tool['function']['name']} 缺少描述"

    def test_dispatch_node_tool(self, openclawd):
        """node__120__list 可以实际执行"""
        result = asyncio.run(openclawd._dispatch_tool_call("node__120__list", {"params": {"path": "."}}))
        assert result.get("success") is True, f"Node 执行失败: {result}"

    def test_dispatch_unknown_node_returns_error(self, openclawd):
        """不存在的节点返回错误而非崩溃"""
        result = asyncio.run(openclawd._dispatch_tool_call("node__999__action", {"params": {}}))
        assert result.get("success") is False
        assert "error" in result

    def test_dispatch_invalid_prefix_returns_error(self, openclawd):
        """未知工具前缀返回错误"""
        result = asyncio.run(openclawd._dispatch_tool_call("unknown__tool", {}))
        assert result.get("success") is False


# ============================================================================
# Test 2: Agent 任务结果判空
# ============================================================================


class TestAgentResultNullCheck:
    """验证 Agent 执行结果 None 时不崩溃"""

    def test_handle_agent_task_null_result(self, openclawd):
        """factory.execute_agent_task 返回 None 时不抛 AttributeError"""
        # 我们只验证 result 判空逻辑存在
        import inspect

        source = inspect.getsource(openclawd.handle_agent_task)
        assert "not result or not isinstance(result, dict)" in source, "handle_agent_task 缺少 result 判空防护"


# ============================================================================
# Test 3: JSON 解析容错
# ============================================================================


class TestJsonPoisonPayload:
    """验证 LLM 返回畸形 JSON 不崩溃"""

    def test_chat_json_invalid_json(self):
        """chat_json 对畸形 JSON 返回 error dict 而非异常"""
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter()
        # Mock chat 返回畸形文本
        fake_resp = FakeLLMResponse(content="not valid json {{")

        async def run():
            with patch.object(router, "chat", new_callable=AsyncMock, return_value=fake_resp):
                result = await router.chat_json([{"role": "user", "content": "test"}])
                assert isinstance(result, dict)
                assert "error" in result

        asyncio.run(run())

    def test_chat_json_valid_json(self):
        """chat_json 对有效 JSON 正常解析"""
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter()
        fake_resp = FakeLLMResponse(content='{"key": "value"}')

        async def run():
            with patch.object(router, "chat", new_callable=AsyncMock, return_value=fake_resp):
                result = await router.chat_json([{"role": "user", "content": "test"}])
                assert result == {"key": "value"}

        asyncio.run(run())


# ============================================================================
# Test 4: 所有 Provider 熔断优雅降级
# ============================================================================


class TestAllProvidersDown:
    """验证所有 Provider 失败返回标准响应而非 RuntimeError"""

    def test_returns_response_not_exception(self):
        """所有 provider 调用失败后返回 LLMResponse 而非抛异常。

        前提由本用例**自己钉死**,不靠"这台机器恰好没装什么"
        ----------------------------------------------------
        ``MultiLLMRouter()`` 在构造时自动发现提供商:本机起着 Ollama(而本项目的
        安装文档本身就要求装它),就会发现一个,于是 ``provider`` 是 ``"ollama"``
        而不是 ``"none"``,断言当场翻 —— 而失败信息只说 ``'ollama' == 'none'``,
        完全不提"因为你装了 Ollama"。

        这条是每日环境耦合扫描(``scripts/detect_environment_coupled_tests.py``)
        逮出来的:干净环境过、起了 Ollama 桩就红。CI 恒绿(runner 干净),只砸本机
        开发者。

        用例名字就叫"所有 provider 都下线",那就**把它们真的清空**,而不是指望
        机器上恰好一个都没有。这不是放松断言 —— 恰恰相反,断言从此在任何机器上
        都成立,而且测的正是它名字说的那件事。
        """
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter()
        # "所有 provider 都下线" = 一个可用提供商都没有。适配器一并清掉:留着的话
        # 路由虽然选不出 provider,后面的兜底路径仍可能摸到一个还活着的适配器。
        router.providers.clear()
        router.adapters.clear()

        async def run():
            # 没有配置任何 provider 时调用 chat
            try:
                result = await router.chat(
                    [{"role": "user", "content": "hello"}],
                    auto_failover=True,
                )
                # 应该返回 LLMResponse 而非抛异常
                assert hasattr(result, "content"), "返回值应为 LLMResponse"
                assert result.provider == "none"
                assert "不可用" in result.content or "服务" in result.content
            except RuntimeError:
                pytest.fail("不应抛 RuntimeError，应返回优雅降级响应")

        asyncio.run(run())


# ============================================================================
# Test 5: Dashboard deletion
# ============================================================================


class TestDashboardRouterSingleton:
    """验证 dashboard 旧表层已删除。"""

    def test_dashboard_backend_deleted(self):
        """dashboard/backend/main.py 不应再作为非主线表层存在。"""
        from pathlib import Path

        assert not Path("dashboard/backend/main.py").exists()


# ============================================================================
# Test 6: ReAct 超时防护签名检查
# ============================================================================


class TestReActTimeout:
    """验证 ReAct 循环有超时参数"""

    def test_react_loop_has_timeout_param(self, openclawd):
        """_react_loop 应有 timeout 参数"""
        import inspect

        sig = inspect.signature(openclawd._react_loop)
        assert "timeout" in sig.parameters, "_react_loop 缺少 timeout 参数"
        default = sig.parameters["timeout"].default
        assert isinstance(default, (int, float)) and default > 0, f"timeout 默认值应为正数，实际: {default}"


# ============================================================================
# Test 7: 工具分发超时防护
# ============================================================================


class TestToolDispatchTimeout:
    """验证工具分发有超时保护"""

    def test_react_loop_has_wait_for(self, openclawd):
        """_react_loop 内部使用 asyncio.wait_for 包裹工具调用。

        这条原本还断言字面量 ``timeout=30``。写死 30 秒被实测证明是个 bug:
        它对机器工具合理,对**等人的工具**是错的 —— ``ask_human__request``
        声明的 timeout_s(最大 3600)会被外层在 30 秒掐断,高风险工具的
        确认闸刚把决策推上手表也会被取消,用户手指落下时已经没人在等了。

        所以断言改成守**不变量**而不是守那个魔数:必须有 wait_for、超时必须
        由预算函数算出、且预算必须有上界(不能变成无界等待)。这比"源码里
        出现过 30 这个数字"严格。
        """
        import inspect

        source = inspect.getsource(openclawd._react_loop)
        assert "wait_for" in source, "_react_loop 应使用 asyncio.wait_for 保护工具调用"
        assert "tool_call_timeout_s" in source, "单工具超时应由预算函数算出,而不是写死"
        assert "timeout=None" not in source, "工具调用不得无界等待"

    def test_tool_timeout_budget_is_bounded(self):
        """预算函数不能给出无界(或荒谬大)的超时 —— 那等于没有超时保护。"""
        from core.tool_permissions import MAX_TOOL_TIMEOUT_S, tool_call_timeout_s

        for tool, args in (
            ("mcp__windows-local__screenshot", None),
            ("node__Node_122_Shell__system_command", None),
            ("ask_human__request", {"timeout_s": 99999}),
        ):
            budget = tool_call_timeout_s(tool, args)
            assert 0 < budget <= MAX_TOOL_TIMEOUT_S, f"{tool} 的超时预算 {budget} 越界"


# ============================================================================
# Test 8: Team gather 容错
# ============================================================================


class TestTeamGatherResilience:
    """验证团队并行执行的 gather 容错"""

    def test_parallel_uses_return_exceptions(self):
        """_execute_parallel 应使用 return_exceptions=True"""
        import inspect

        from core.agent_team import AgentTeam

        source = inspect.getsource(AgentTeam._execute_parallel)
        assert "return_exceptions=True" in source, "_execute_parallel 的 gather 应使用 return_exceptions=True"

    def test_parallel_has_member_timeout(self):
        """_execute_parallel 应有成员超时保护"""
        import inspect

        from core.agent_team import AgentTeam

        source = inspect.getsource(AgentTeam._execute_parallel)
        assert "wait_for" in source, "_execute_parallel 应使用 asyncio.wait_for"
        assert "90" in source, "成员超时应为 90 秒"


# ============================================================================
# Test 9: Windows Client legacy shell deletion
# ============================================================================


class TestWindowsClientEncoding:
    """验证旧 windows_client/main.py 已删除，避免继续承载旧壳逻辑。"""

    def test_legacy_main_deleted(self):
        """windows_client/main.py 不应再作为根层旧壳存在。"""
        from pathlib import Path

        assert not Path("windows_client/main.py").exists()

    def test_status_board_v2_is_gone(self):
        """status_board_v2 已随面板表层收敛删除。

        这条原本钉的是"删掉旧壳后 status_board_v2 仍在"——当时它是 Windows 侧
        的 canonical 状态表层。现在面板收敛到唯一一份(Tauri/Electron 壳内的
        React 面板),这个终端状态板整包移除,断言相应翻面。
        """
        from pathlib import Path

        assert not Path("windows_client/status_board_v2").exists()
