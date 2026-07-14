"""
集成测试 — 从 Dashboard 到 Core 的完整聊天流程
================================================

验证:
  1. 意图解析 (现代 IntentParser + 旧版 fallback)
  2. 对话记忆存取
  3. 统一响应格式 (UnifiedChatResponse)
  4. call_node 错误处理 (超时, HTTP 错误)
  5. Dashboard chat 端到端流程
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# 1. IntentParser 集成测试
# ============================================================================


class TestIntentParser:
    """测试意图解析器的规则引擎和 LLM 回退"""

    @pytest.fixture
    def parser(self):
        from core.ai_intent import IntentParser

        return IntentParser()

    @pytest.mark.asyncio
    async def test_rule_based_device_control(self, parser):
        """规则引擎识别设备控制意图"""
        result = await parser.parse("帮我打开微信")
        assert result.intent == "device_control"
        assert result.confidence >= 0.3
        assert result.raw_text == "帮我打开微信"

    @pytest.mark.asyncio
    async def test_rule_based_task_manage(self, parser):
        """规则引擎识别任务管理意图"""
        result = await parser.parse("整理我的任务")
        assert result.intent == "task_manage"
        assert result.confidence >= 0.3

    @pytest.mark.asyncio
    async def test_rule_based_chat_fallback(self, parser):
        """无法识别时回退到聊天"""
        result = await parser.parse("你好呀")
        assert result.intent == "chat"
        assert result.confidence <= 0.5

    @pytest.mark.asyncio
    async def test_suggestions_generated(self, parser):
        """解析后生成后续建议"""
        result = await parser.parse("搜索文件")
        assert isinstance(result.suggestions, list)
        assert len(result.suggestions) > 0

    @pytest.mark.asyncio
    async def test_parse_caching(self, parser):
        """相同输入使用缓存"""
        r1 = await parser.parse("打开设备")
        r2 = await parser.parse("打开设备")
        assert r1.intent == r2.intent
        assert r1.confidence == r2.confidence

    @pytest.mark.asyncio
    async def test_llm_skip_without_api_key(self, parser):
        """没有 API Key 时 LLM 解析跳过，不报错"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": ""}, clear=False):
            result = await parser._parse_by_llm("测试消息", None)
            assert result is None


# ============================================================================
# 2. ConversationMemory 集成测试
# ============================================================================


class TestConversationMemory:
    """测试对话记忆系统"""

    @pytest.fixture(autouse=True)
    def _isolated_sm(self, tmp_path, monkeypatch):
        # 融合(域3)后 CM 直写/透读唯一属主 SessionManager —— 隔离其单例与状态文件,
        # 避免测试轮次写进全局 data/sessions.json 并与其它测试的同名会话交叉污染。
        import core.session_manager as smmod

        monkeypatch.setattr(smmod, "_SESSION_FILE", str(tmp_path / "sessions.json"))
        monkeypatch.setattr(smmod, "_session_manager", smmod.SessionManager())
        yield

    @pytest.fixture
    def memory(self):
        from core.ai_intent import ConversationMemory

        return ConversationMemory()

    @pytest.mark.asyncio
    async def test_add_and_get_turns(self, memory):
        """添加和获取对话轮次"""
        await memory.add_turn("s1", "user", "你好")
        await memory.add_turn("s1", "assistant", "你好！有什么可以帮你的？")

        context = await memory.get_context("s1")
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_max_turns_limit(self, memory):
        """超出最大轮次时自动裁剪"""
        for i in range(25):
            await memory.add_turn("s2", "user", f"消息 {i}")

        context = await memory.get_context("s2", max_turns=10)
        assert len(context) <= 10

    @pytest.mark.asyncio
    async def test_session_isolation(self, memory):
        """不同会话之间隔离"""
        await memory.add_turn("s_a", "user", "会话A")
        await memory.add_turn("s_b", "user", "会话B")

        ctx_a = await memory.get_context("s_a")
        ctx_b = await memory.get_context("s_b")

        assert len(ctx_a) == 1
        assert len(ctx_b) == 1
        assert ctx_a[0]["content"] == "会话A"
        assert ctx_b[0]["content"] == "会话B"

    @pytest.mark.asyncio
    async def test_user_profile_learning(self, memory):
        """用户偏好学习"""
        await memory.add_turn("s3", "user", "打开设备")
        await memory.add_turn("s3", "user", "关闭设备")
        profile = memory.get_user_profile("s3")
        assert profile["interaction_count"] == 2

    @pytest.mark.asyncio
    async def test_session_summary(self, memory):
        """会话摘要"""
        await memory.add_turn("s4", "user", "你好")
        summary = await memory.get_summary("s4")
        assert "1 轮" in summary

    @pytest.mark.asyncio
    async def test_clear_session(self, memory):
        """清除会话"""
        await memory.add_turn("s5", "user", "测试")
        await memory.clear_session("s5")
        context = await memory.get_context("s5")
        assert len(context) == 0


# ============================================================================
# 3. GalaxyCore call_node 错误处理测试
# ============================================================================


class TestGalaxyCoreCallNode:
    """测试 call_node 的错误处理"""

    @pytest.fixture
    def core(self):
        from core.galaxy_core import GalaxyCore

        c = GalaxyCore()
        # 确保测试用节点 "04" 存在（无论 node_registry.json 内容如何）
        c.nodes.setdefault("04", {"name": "Router", "port": 8004, "capabilities": ["route"]})
        return c

    @pytest.mark.asyncio
    async def test_node_not_found(self, core):
        """调用不存在的节点"""
        result = await core.call_node("999", "test", {})
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_call_node_timeout(self, core):
        """节点请求超时"""
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        core._http_client = mock_client

        result = await core.call_node("04", "test", {})
        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_call_node_http_error(self, core):
        """节点返回 HTTP 错误"""
        import httpx

        mock_response_mcp = MagicMock()
        mock_response_mcp.status_code = 404

        mock_response_direct = MagicMock()
        mock_response_direct.status_code = 500
        mock_response_direct.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=mock_response_direct,
            )
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_response_mcp, mock_response_direct])
        core._http_client = mock_client

        result = await core.call_node("04", "test", {})
        assert result["success"] is False
        assert "HTTP" in result["error"]


# ============================================================================
# 4. 统一响应格式测试
# ============================================================================


class TestDashboardRetired:
    """终态(用户裁决):dashboard/ 整体删除(ui_surface_authority: DELETED)。
    原三组用例(UnifiedResponse 格式 / 现代意图集成 / 端到端 chat 流)的被测
    对象是 dashboard/backend/main.py——对话主链路已收口到 core 路由与
    DesktopPresenceRuntime(有各自的套件专钉),此处只钉退役不复活。"""

    def test_dashboard_backend_retired(self):
        assert not os.path.exists(
            os.path.join(PROJECT_ROOT, "dashboard")
        ), "dashboard/ 已按用户裁决整体退役删除,不得复活"

    def test_canonical_chat_surface_exists(self):
        # 对话主链路的 canonical 承载(core 路由)仍在
        assert os.path.exists(os.path.join(PROJECT_ROOT, "core", "routes", "chat.py"))
