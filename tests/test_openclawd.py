"""
OpenClawd 核心智能体单元测试
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.openclawd import OpenClawd, get_openclawd


class TestOpenClawdInit:
    """OpenClawd 初始化测试"""

    def test_instantiation(self):
        oc = OpenClawd()
        assert oc._initialized is False
        assert oc._request_count == 0
        assert oc._error_count == 0

    def test_ensure_initialized(self):
        oc = OpenClawd()
        oc._ensure_initialized()
        assert oc._initialized is True

    def test_get_openclawd_singleton(self):
        oc1 = get_openclawd()
        oc2 = get_openclawd()
        assert oc1 is oc2


class TestOpenClawdHandlerFallback:
    """Handler 回退测试"""

    def test_intent_handler_map_keys(self):
        oc = OpenClawd()
        expected_intents = {
            "chat", "device_control", "task_manage", "file_operation",
            "search", "ocr", "system_status", "network", "code",
            # Priority D+E: high-level autonomous execution
            "goal_execution", "parallel_goal",
        }
        assert set(oc._INTENT_HANDLER_MAP.keys()) == expected_intents

    def test_handler_fallback_for_unknown_intent(self):
        """未知意图应回退到 _dispatch_chat"""
        oc = OpenClawd()
        handler_name = oc._INTENT_HANDLER_MAP.get("unknown_intent_xyz", "_dispatch_chat")
        assert handler_name == "_dispatch_chat"
        assert hasattr(oc, handler_name)

    def test_all_mapped_handlers_exist(self):
        """所有映射的 handler 方法必须存在"""
        oc = OpenClawd()
        for intent, handler_name in oc._INTENT_HANDLER_MAP.items():
            assert hasattr(oc, handler_name), (
                f"Intent '{intent}' maps to '{handler_name}' which does not exist"
            )


class TestOpenClawdSessionMemory:
    """会话记忆测试"""

    def test_session_memory_init(self):
        oc = OpenClawd()
        assert isinstance(oc._session_memory, dict)
        assert len(oc._session_memory) == 0


@pytest.mark.asyncio
async def test_process_basic_chat():
    """基本聊天消息处理 — mock 意图解析和 LLM"""
    oc = OpenClawd()

    # PR86: 禁用 kernel 路径，以便测试直接路径
    with patch.object(oc, "_get_kernel", return_value=None):
        with patch.object(oc, "sync_device_capabilities", return_value=0):
            # Mock _parse_intent 返回 None (回退到 chat)
            with patch.object(oc, "_parse_intent", new_callable=AsyncMock) as mock_parse:
                mock_parse.return_value = None

                with patch.object(oc, "_dispatch_chat", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = {
                        "response": "你好！",
                        "intent": "chat",
                    }

                    result = await oc.process("你好", session_id="test_session")

                    assert result["success"] is True
                    assert "response" in result
                    mock_parse.assert_called_once()
                    mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_process_returns_session_id():
    """process() 应返回 session_id"""
    oc = OpenClawd()

    with patch.object(oc, "_get_kernel", return_value=None):
        with patch.object(oc, "sync_device_capabilities", return_value=0):
            with patch.object(oc, "_parse_intent", new_callable=AsyncMock, return_value=None):
                with patch.object(oc, "_dispatch_chat", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = {"response": "OK"}

                    result = await oc.process("test", session_id="sid_123")

                    assert result.get("metadata", {}).get("session_id") == "sid_123"
