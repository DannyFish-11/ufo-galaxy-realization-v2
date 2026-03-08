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
        return GalaxyCore()

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

class TestUnifiedResponseFormat:
    """测试 UnifiedChatResponse 格式"""

    def test_build_unified_response(self):
        """验证统一响应结构"""
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "dashboard", "backend"))
        from main import _build_unified_response

        resp = _build_unified_response(
            success=True,
            response="测试回复",
            intent="device_control",
            confidence=0.85,
            suggestions=["建议1"],
            data={"key": "value"},
        )

        assert resp["success"] is True
        assert resp["response"] == "测试回复"
        assert resp["intent"] == "device_control"
        assert resp["confidence"] == 0.85
        assert resp["suggestions"] == ["建议1"]
        assert resp["data"] == {"key": "value"}
        assert resp["error"] is None
        assert "timestamp" in resp

    def test_unified_response_error(self):
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "dashboard", "backend"))
        from main import _build_unified_response

        resp = _build_unified_response(
            success=False,
            response="出错了",
            error="连接超时",
        )

        assert resp["success"] is False
        assert resp["error"] == "连接超时"


# ============================================================================
# 5. Dashboard 现代意图解析集成测试
# ============================================================================

class TestDashboardModernIntentIntegration:
    """测试 Dashboard 与现代意图解析器的集成"""

    @pytest.mark.asyncio
    async def test_get_parsed_intent_modern_available(self):
        """现代解析器可用时使用现代解析器"""
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "dashboard", "backend"))
        from main import get_parsed_intent_modern

        result = await get_parsed_intent_modern("打开微信", "test_session")
        assert result["type"] in ("device_control", "chat")
        assert "confidence" in result
        assert "suggestions" in result

    @pytest.mark.asyncio
    async def test_get_parsed_intent_fallback(self):
        """现代解析器不可用时回退到旧版"""
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "dashboard", "backend"))

        import main as dashboard_main
        original = dashboard_main.MODERN_INTENT_AVAILABLE
        dashboard_main.MODERN_INTENT_AVAILABLE = False
        try:
            result = await dashboard_main.get_parsed_intent_modern("打开微信")
            assert result["modern"] is False
            assert result["type"] == "device_control"
        finally:
            dashboard_main.MODERN_INTENT_AVAILABLE = original


# ============================================================================
# 6. 端到端流程模拟测试
# ============================================================================

class TestEndToEndChatFlow:
    """模拟完整的用户请求流程"""

    @pytest.mark.asyncio
    async def test_full_chat_flow_intent_to_memory(self):
        """验证: 用户消息 → 意图解析 → 记忆存储 的完整流程"""
        from core.ai_intent import IntentParser, ConversationMemory

        parser = IntentParser()
        memory = ConversationMemory()
        session_id = "e2e_test"

        # 1. 用户发送消息
        user_msg = "帮我搜索文件"

        # 2. 记录用户消息
        await memory.add_turn(session_id, "user", user_msg)

        # 3. 解析意图
        context = {"history": await memory.get_context(session_id)}
        parsed = await parser.parse(user_msg, context=context)

        # 4. 验证意图
        assert parsed.intent in ("search", "file_operation")
        assert parsed.confidence > 0

        # 5. 模拟助手回复
        assistant_reply = f"已完成: {parsed.intent}"
        await memory.add_turn(session_id, "assistant", assistant_reply)

        # 6. 验证记忆
        full_context = await memory.get_context(session_id)
        assert len(full_context) == 2
        assert full_context[0]["role"] == "user"
        assert full_context[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_multi_turn_conversation_flow(self):
        """验证多轮对话流程"""
        from core.ai_intent import IntentParser, ConversationMemory

        parser = IntentParser()
        memory = ConversationMemory()
        session_id = "multi_turn_test"

        messages = [
            ("user", "你好"),
            ("assistant", "你好！有什么可以帮你的？"),
            ("user", "帮我打开设备"),
            ("assistant", "已打开设备"),
            ("user", "查看状态"),
        ]

        for role, content in messages:
            await memory.add_turn(session_id, role, content)

        # 解析最后一条消息
        context = {"history": await memory.get_context(session_id)}
        parsed = await parser.parse("查看状态", context=context)

        assert parsed.intent == "system_status"
        assert parsed.context_used is False  # 规则引擎不使用上下文

        # 验证完整历史
        full = await memory.get_context(session_id)
        assert len(full) == 5


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
