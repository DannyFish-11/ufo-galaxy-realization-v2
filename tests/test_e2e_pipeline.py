"""
Tests for E2E Pipeline and Session Manager
===========================================

Covers: SessionManager, EndToEndPipeline, Session API routes.
"""

import json
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.session_manager import (
    SessionManager,
    Session,
    SessionMessage,
    get_session_manager,
)
from core.e2e_pipeline import EndToEndPipeline


# ══════════════════════ Fixtures ══════════════════════

@pytest.fixture
def session_manager(tmp_path):
    """SessionManager with temp storage."""
    sm = SessionManager()
    sm._sessions.clear()
    sm._user_active_session.clear()
    # Override persist to avoid file conflicts
    sm._persist_state = lambda: None
    return sm


@pytest.fixture
def mock_llm_router():
    """Mock LLM router."""
    router = MagicMock()
    router.is_available = MagicMock(return_value=True)
    router.get_default_model = MagicMock(return_value="mock-model")
    router.chat_completion = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(message=MagicMock(content="Hello from Galaxy!"))],
        model="mock-model",
    ))
    return router


@pytest.fixture
def mock_connection_manager():
    """Mock connection manager."""
    cm = MagicMock()
    cm.send_to_device = AsyncMock(return_value=True)
    cm.broadcast_status = AsyncMock()
    return cm


@pytest.fixture
def pipeline(session_manager, mock_llm_router, mock_connection_manager):
    """EndToEndPipeline with mocks."""
    return EndToEndPipeline(
        session_manager=session_manager,
        llm_router=mock_llm_router,
        agent_factory=None,
        connection_manager=mock_connection_manager,
    )


# ============================================================================
# SessionManager Tests
# ============================================================================


class TestSessionManager:
    """Tests for cross-device unified session management."""

    def test_create_session(self, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        assert session.user_id == "user_001"
        assert "phone_01" in session.devices
        assert session.id.startswith("session_")

    def test_get_or_create_session(self, session_manager):
        s1 = session_manager.get_or_create_session("user_001", "phone_01")
        s2 = session_manager.get_or_create_session("user_001", "pc_01")
        # Same user should get same session
        assert s1.id == s2.id
        # Both devices should be in the session
        assert "phone_01" in s2.devices
        assert "pc_01" in s2.devices

    def test_different_users_get_different_sessions(self, session_manager):
        s1 = session_manager.get_or_create_session("user_001", "phone_01")
        s2 = session_manager.get_or_create_session("user_002", "phone_02")
        assert s1.id != s2.id

    def test_join_session(self, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        ok = session_manager.join_session(session.id, "tablet_01")
        assert ok is True
        assert "tablet_01" in session.devices

    def test_join_nonexistent_session(self, session_manager):
        ok = session_manager.join_session("nonexistent", "device_01")
        assert ok is False

    def test_add_message(self, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        ok = session_manager.add_message(
            session.id, "user", "Hello", "phone_01"
        )
        assert ok is True
        assert len(session.history) == 1
        assert session.history[0].content == "Hello"
        assert session.history[0].device_id == "phone_01"

    def test_add_message_to_nonexistent(self, session_manager):
        ok = session_manager.add_message("nonexistent", "user", "Hello")
        assert ok is False

    def test_get_history(self, session_manager):
        session = session_manager.create_session("user_001")
        for i in range(5):
            session_manager.add_message(session.id, "user", f"msg_{i}")

        history = session_manager.get_history(session.id, max_turns=3)
        assert len(history) == 3
        # Should be the last 3 messages
        assert history[0]["content"] == "msg_2"
        assert history[2]["content"] == "msg_4"

    def test_get_history_as_llm_format(self, session_manager):
        session = session_manager.create_session("user_001")
        session_manager.add_message(session.id, "user", "What's the weather?")
        session_manager.add_message(session.id, "assistant", "It's sunny!")

        history = session_manager.get_history(session.id)
        assert history[0] == {"role": "user", "content": "What's the weather?"}
        assert history[1] == {"role": "assistant", "content": "It's sunny!"}

    def test_history_truncation(self, session_manager):
        session_manager.MAX_HISTORY = 5
        session = session_manager.create_session("user_001")
        for i in range(10):
            session_manager.add_message(session.id, "user", f"msg_{i}")

        assert len(session.history) == 5
        assert session.history[0].content == "msg_5"

    def test_list_sessions(self, session_manager):
        session_manager.create_session("user_001", "phone_01")
        session_manager.create_session("user_002", "phone_02")

        all_sessions = session_manager.list_sessions()
        assert len(all_sessions) == 2

        user1_sessions = session_manager.list_sessions("user_001")
        assert len(user1_sessions) == 1

    def test_list_device_sessions(self, session_manager):
        s1 = session_manager.create_session("user_001", "phone_01")
        s2 = session_manager.create_session("user_002", "pc_01")
        session_manager.join_session(s2.id, "phone_01")

        phone_sessions = session_manager.list_device_sessions("phone_01")
        assert len(phone_sessions) == 2

    def test_get_full_history(self, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        session_manager.add_message(
            session.id, "user", "Hello", "phone_01", {"source": "voice"}
        )

        full = session_manager.get_full_history(session.id)
        assert len(full) == 1
        assert full[0]["device_id"] == "phone_01"
        assert full[0]["metadata"] == {"source": "voice"}
        assert "timestamp" in full[0]

    def test_session_to_dict_roundtrip(self, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        session_manager.add_message(session.id, "user", "test")

        d = session.to_dict()
        restored = Session.from_dict(d)
        assert restored.id == session.id
        assert restored.user_id == "user_001"
        assert len(restored.history) == 1

    def test_session_summary(self, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        session_manager.add_message(session.id, "user", "test")

        summary = session.to_summary()
        assert summary["message_count"] == 1
        assert "history" not in summary

    def test_update_callback(self, session_manager):
        called = []
        session_manager.set_update_callback(
            lambda sid, msg, devices: called.append((sid, msg, devices))
        )
        session = session_manager.create_session("user_001", "phone_01")
        session_manager.add_message(session.id, "user", "test", "phone_01")

        assert len(called) == 1
        assert called[0][0] == session.id
        assert called[0][1]["content"] == "test"


# ============================================================================
# SessionMessage Tests
# ============================================================================


class TestSessionMessage:

    def test_to_dict(self):
        msg = SessionMessage(
            role="user",
            content="Hello",
            device_id="phone_01",
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert d["device_id"] == "phone_01"

    def test_from_dict(self):
        d = {"role": "assistant", "content": "Hi!", "device_id": "pc_01", "timestamp": 12345.0}
        msg = SessionMessage.from_dict(d)
        assert msg.role == "assistant"
        assert msg.content == "Hi!"
        assert msg.timestamp == 12345.0


# ============================================================================
# EndToEndPipeline Tests
# ============================================================================


class TestEndToEndPipeline:
    """Tests for the end-to-end pipeline."""

    @pytest.mark.asyncio
    async def test_chat_mode(self, pipeline):
        result = await pipeline.execute(
            message="你好，今天天气怎么样？",
            user_id="user_001",
            source_device_id="phone_01",
        )
        assert result["success"] is True
        assert result["mode"] == "chat"
        assert result["reply"] == "Hello from Galaxy!"
        assert result["session_id"].startswith("session_")

    @pytest.mark.asyncio
    async def test_session_created_and_reused(self, pipeline):
        r1 = await pipeline.execute(
            message="Hello", user_id="user_001", source_device_id="phone_01"
        )
        r2 = await pipeline.execute(
            message="World", user_id="user_001", source_device_id="pc_01"
        )
        # Same user should use same session
        assert r1["session_id"] == r2["session_id"]

    @pytest.mark.asyncio
    async def test_session_history_accumulated(self, pipeline, session_manager):
        await pipeline.execute(
            message="msg1", user_id="user_001", source_device_id="phone_01"
        )
        await pipeline.execute(
            message="msg2", user_id="user_001", source_device_id="phone_01"
        )

        sessions = session_manager.list_sessions("user_001")
        assert len(sessions) == 1
        session_id = sessions[0]["id"]

        # Each execute adds user + assistant = 2 messages per call
        history = session_manager.get_full_history(session_id)
        assert len(history) == 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_cross_device_broadcast(self, pipeline, mock_connection_manager):
        # First message from phone
        await pipeline.execute(
            message="Hello", user_id="user_001", source_device_id="phone_01"
        )
        # Second message from PC (should broadcast back to phone)
        result = await pipeline.execute(
            message="World", user_id="user_001", source_device_id="pc_01"
        )
        # phone_01 should have been notified
        assert "phone_01" in result["devices_notified"]

    @pytest.mark.asyncio
    async def test_explicit_session_id(self, pipeline, session_manager):
        session = session_manager.create_session("user_001", "phone_01")
        result = await pipeline.execute(
            message="test",
            user_id="user_001",
            source_device_id="pc_01",
            session_id=session.id,
        )
        assert result["session_id"] == session.id

    @pytest.mark.asyncio
    async def test_fallback_without_llm(self):
        pipeline = EndToEndPipeline(
            session_manager=None,
            llm_router=None,
        )
        result = await pipeline.execute(message="Hello")
        assert result["success"] is False
        assert "LLM" in result["reply"]

    @pytest.mark.asyncio
    async def test_latency_tracking(self, pipeline):
        result = await pipeline.execute(
            message="test", user_id="user_001"
        )
        assert "latency_ms" in result["data"]
        assert result["data"]["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_pipeline_with_context(self, pipeline):
        context = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        result = await pipeline.execute(
            message="follow up",
            user_id="user_001",
            context=context,
        )
        assert result["success"] is True


# ============================================================================
# ChatRequest Model Tests
# ============================================================================


class TestChatRequestModel:
    """Tests for the updated ChatRequest model."""

    def test_chat_request_new_fields(self):
        from core.routes._models import ChatRequest
        req = ChatRequest(
            message="test",
            device_id="phone_01",
            user_id="user_001",
            session_id="session_abc123",
        )
        assert req.user_id == "user_001"
        assert req.session_id == "session_abc123"

    def test_chat_request_backward_compatible(self):
        from core.routes._models import ChatRequest
        # Old-style request without new fields should still work
        req = ChatRequest(message="test", device_id="phone_01")
        assert req.user_id == ""
        assert req.session_id == ""
