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
from unittest.mock import patch

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


# ============================================================================
# 4. 统一响应格式测试
# ============================================================================


# 已删除依赖 core/galaxy_core.py 的用例 —— 该模块是建在近乎废弃的
# core/node_protocol.py 之上的门面：它声称依赖的 NodeProtocolClient /
# NodeProtocolServer **根本不存在**（被 try/except 包着所以 import 不报错，
# 但 call_node_with_protocol() 拿到的是 None），生产面零 import。已删除。
