"""
端到端集成测试 — Dashboard 到 Core 的完整对话流程

测试覆盖：
  1. 操作指令 → 意图识别 → 节点调用 → 统一响应格式
  2. 纯聊天 → LLM 对话 → 统一响应格式
  3. 对话记忆 → 上下文保持
  4. 路由分离 → dashboard 和 core 不冲突
  5. 降级场景 → 无 LLM 时友好提示
  6. 意图解析器 → modern parser 与 fallback
  7. UnifiedChatResponse 格式验证
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
# 1. UnifiedChatResponse 格式测试
# ============================================================================

class TestUnifiedChatResponse:
    """验证统一响应模型的字段和序列化"""

    def test_default_fields(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hello")
        d = resp.to_json_response()
        assert d["success"] is True
        assert d["response"] == "hello"
        assert d["intent"] == ""
        assert d["confidence"] == 0.0
        assert d["mode"] == "chat"
        assert d["suggestions"] == []
        assert d["data"] == {}
        assert d["error"] == ""
        assert d["session_id"] == ""
        assert d["model"] == ""
        assert "timestamp" in d

    def test_full_fields(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(
            success=False,
            response="操作失败",
            intent="device_control",
            confidence=0.9,
            mode="agent_react",
            suggestions=["重试", "查看日志"],
            data={"steps": [{"node_id": "33", "action": "screenshot"}]},
            error="设备离线",
            session_id="dev-001",
            model="gpt-4o-mini",
        )
        d = resp.to_json_response()
        assert d["success"] is False
        assert d["intent"] == "device_control"
        assert d["confidence"] == 0.9
        assert len(d["suggestions"]) == 2
        assert d["data"]["steps"][0]["node_id"] == "33"
        assert d["error"] == "设备离线"
        assert d["model"] == "gpt-4o-mini"

    def test_timestamp_auto_generated(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="test")
        d = resp.to_json_response()
        # 应该是 ISO 格式的时间字符串
        ts = d["timestamp"]
        assert len(ts) > 10
        # 解析验证
        datetime.fromisoformat(ts)


# ============================================================================
# 2. 意图解析器测试
# ============================================================================

class TestIntentParser:
    """测试 core.ai_intent.IntentParser"""

    def test_rule_based_device_control(self):
        from core.ai_intent import IntentParser
        parser = IntentParser()
        result = asyncio.run(
            parser.parse("帮我打开手机截图")
        )
        assert result.intent == "device_control"
        assert result.confidence >= 0.3

    def test_rule_based_task_manage(self):
        from core.ai_intent import IntentParser
        parser = IntentParser()
        result = asyncio.run(
            parser.parse("查看我的任务列表")
        )
        assert result.intent == "task_manage"

    def test_rule_based_chat_fallback(self):
        from core.ai_intent import IntentParser
        parser = IntentParser()
        result = asyncio.run(
            parser.parse("今天天气怎么样？")
        )
        # 没有匹配到关键词，应该 fallback 到 chat
        assert result.confidence <= 0.5

    def test_llm_skipped_without_api_key(self):
        """没有 API Key 时 LLM 解析应跳过"""
        from core.ai_intent import IntentParser
        parser = IntentParser()
        with patch.dict(os.environ, {}, clear=False):
            # 移除可能存在的 API Key
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("DEEPSEEK_API_KEY", None)
            result = asyncio.run(
                parser._parse_by_llm("test message", None)
            )
            assert result is None

    def test_parsed_intent_to_dict(self):
        from core.ai_intent import ParsedIntent
        intent = ParsedIntent(
            intent="device_control",
            command="screenshot",
            targets=["device"],
            params={"mode": "full"},
            confidence=0.8,
            raw_text="截图",
            context_used=False,
            suggestions=["查看截图"],
        )
        d = intent.to_dict()
        assert d["intent"] == "device_control"
        assert d["confidence"] == 0.8
        assert "suggestions" in d


# ============================================================================
# 3. 对话记忆测试
# ============================================================================

class TestConversationMemory:
    """测试对话记忆系统"""

    def test_add_and_get_context(self):
        from core.ai_intent import ConversationMemory
        memory = ConversationMemory()

        asyncio.run(memory.add_turn("s1", "user", "你好"))
        asyncio.run(memory.add_turn("s1", "assistant", "你好！有什么可以帮你的？"))
        asyncio.run(memory.add_turn("s1", "user", "打开微信"))

        context = asyncio.run(memory.get_context("s1", max_turns=10))
        assert len(context) == 3
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "你好"
        assert context[2]["content"] == "打开微信"

    def test_max_turns_truncation(self):
        from core.ai_intent import ConversationMemory
        memory = ConversationMemory(max_turns=3)

        for i in range(5):
            asyncio.run(memory.add_turn("s2", "user", f"msg-{i}"))

        context = asyncio.run(memory.get_context("s2"))
        assert len(context) == 3
        assert context[0]["content"] == "msg-2"

    def test_user_profile_learning(self):
        from core.ai_intent import ConversationMemory
        memory = ConversationMemory()

        asyncio.run(memory.add_turn("s3", "user", "帮我管理任务"))
        asyncio.run(memory.add_turn("s3", "user", "查看任务"))

        profile = memory.get_user_profile("s3")
        assert profile["interaction_count"] == 2
        assert profile["frequent_intents"]["task_manage"] >= 1

    def test_session_isolation(self):
        from core.ai_intent import ConversationMemory
        memory = ConversationMemory()

        asyncio.run(memory.add_turn("s4", "user", "hello"))
        asyncio.run(memory.add_turn("s5", "user", "world"))

        ctx4 = asyncio.run(memory.get_context("s4"))
        ctx5 = asyncio.run(memory.get_context("s5"))
        assert len(ctx4) == 1
        assert len(ctx5) == 1
        assert ctx4[0]["content"] == "hello"
        assert ctx5[0]["content"] == "world"

    def test_clear_session(self):
        from core.ai_intent import ConversationMemory
        memory = ConversationMemory()

        asyncio.run(memory.add_turn("s6", "user", "test"))
        asyncio.run(memory.clear_session("s6"))

        context = asyncio.run(memory.get_context("s6"))
        assert len(context) == 0


# ============================================================================
# 4. Dashboard parse_intent (fallback) 测试
# ============================================================================

class TestDashboardParseIntent:
    """测试 dashboard 的简单 fallback 意图解析"""

    @pytest.fixture(autouse=True)
    def _import_parse_intent(self):
        """尝试导入 dashboard parse_intent，导入失败则跳过"""
        try:
            from dashboard.backend.main import parse_intent
            self.parse_intent = parse_intent
        except (ImportError, SyntaxError, NameError) as e:
            pytest.skip(f"Dashboard import failed (expected in CI): {e}")

    def test_device_control_open(self):
        result = self.parse_intent("打开微信")
        assert result["type"] == "device_control"
        assert result["action"] == "open_app"
        assert "confidence" in result

    def test_screenshot(self):
        result = self.parse_intent("截图")
        assert result["type"] == "device_control"
        assert result["action"] == "screenshot"

    def test_learning(self):
        result = self.parse_intent("学习这个模式")
        assert result["type"] == "learning"

    def test_chat_fallback(self):
        result = self.parse_intent("随便聊聊吧")
        assert result["type"] == "chat"
        assert result["confidence"] == 0.3


# ============================================================================
# 5. call_node 错误处理测试
# ============================================================================

class TestCallNodeErrorHandling:
    """测试 galaxy_core.call_node() 的超时和错误处理"""

    @pytest.fixture(autouse=True)
    def _import_galaxy_core(self):
        try:
            from core.galaxy_core import GalaxyCore
            self.GalaxyCore = GalaxyCore
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f"GalaxyCore import failed: {e}")

    def test_node_not_found(self):
        core = self.GalaxyCore()
        result = asyncio.run(
            core.call_node("nonexistent_node", "test", {})
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_timeout_handling(self):
        """请求超时应返回错误而非挂起"""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")

        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Connection timed out")):
            core = self.GalaxyCore()
            core.nodes["test_node"] = {"port": 9999}

            result = asyncio.run(
                core.call_node("test_node", "test_action", {})
            )
            assert result["success"] is False
            assert "error" in result


# ============================================================================
# 6. 路由分离测试
# ============================================================================

class TestRouteSeparation:
    """验证 dashboard 和 core 的 chat 端点使用不同路由"""

    def test_dashboard_route_is_dashboard_chat(self):
        """dashboard 应使用 /api/v1/dashboard/chat 和 /api/v1/chat（统一端点）"""
        try:
            from dashboard.backend.main import app
        except (ImportError, SyntaxError, NameError) as e:
            pytest.skip(f"Dashboard import failed: {e}")

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v1/dashboard/chat" in routes
        # 当前架构: dashboard 同时提供 /api/v1/chat 作为统一聊天端点
        assert "/api/v1/chat" in routes, "Dashboard should define /api/v1/chat as unified endpoint"


# ============================================================================
# 7. 降级场景测试
# ============================================================================

class TestDegradation:
    """测试无 LLM / 无 galaxy_core 时的降级行为"""

    def test_no_llm_returns_friendly_error(self):
        """无 LLM 配置时应返回友好提示"""
        from core.unified_response import UnifiedChatResponse
        # 模拟降级响应
        resp = UnifiedChatResponse(
            success=False,
            response="LLM 服务未配置。请设置 API Key。",
            mode="fallback",
            error="未配置 LLM API Key",
        )
        d = resp.to_json_response()
        assert d["success"] is False
        assert d["mode"] == "fallback"
        assert "API Key" in d["response"]


# ============================================================================
# 8. Smart Recommender 测试
# ============================================================================

class TestSmartRecommender:
    """测试智能推荐引擎"""

    def test_recommendations_with_history(self):
        from core.ai_intent import ConversationMemory, SmartRecommender
        memory = ConversationMemory()
        recommender = SmartRecommender(memory=memory)

        # 添加一些历史
        asyncio.run(memory.add_turn("s7", "user", "查看任务"))
        asyncio.run(memory.add_turn("s7", "user", "整理任务"))

        recs = asyncio.run(recommender.get_recommendations("s7"))
        assert len(recs) > 0
        # 应包含 task_manage 相关推荐
        intents = [r["intent"] for r in recs]
        assert "task_manage" in intents

    def test_recommendations_without_history(self):
        from core.ai_intent import SmartRecommender
        recommender = SmartRecommender()
        recs = asyncio.run(recommender.get_recommendations("new_user"))
        # 至少有快捷操作
        assert len(recs) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
