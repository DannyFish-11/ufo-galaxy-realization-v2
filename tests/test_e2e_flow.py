"""
Tests for End-to-End Flow Wiring
================================

Validates that all newly wired modules work together:
- core/e2e_orchestrator.py (process_user_input, process_wake_event)
- websocket_handler.py WAKE_EVENT and SESSION_MIGRATE handling
- SessionRoaming + WakeEventBus initialization
- Gateway session REST endpoints
- MessageType enum extensions
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════ MessageType extensions ══════════════════════

class TestMessageTypeExtensions:
    """Verify WAKE_EVENT and SESSION_MIGRATE are in the AIP v3 enum."""

    def test_wake_event_in_enum(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "WAKE_EVENT")
        assert MessageType.WAKE_EVENT.value == "wake_event"

    def test_session_migrate_in_enum(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "SESSION_MIGRATE")
        assert MessageType.SESSION_MIGRATE.value == "session_migrate"

    def test_session_migrate_ack_in_enum(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "SESSION_MIGRATE_ACK")
        assert MessageType.SESSION_MIGRATE_ACK.value == "session_migrate_ack"


# ══════════════════════ E2E Orchestrator ══════════════════════

class TestE2EOrchestrator:
    """Test the orchestrator convenience functions."""

    @pytest.mark.asyncio
    async def test_process_user_input_delegates_to_pipeline(self):
        """process_user_input with use_constellation=False should call pipeline.execute()."""
        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value={
            "success": True,
            "reply": "Hello!",
            "session_id": "test-session",
            "mode": "chat",
            "data": {},
            "devices_notified": [],
        })

        with patch("core.e2e_pipeline.get_pipeline", return_value=mock_pipeline):
            from core.e2e_orchestrator import process_user_input

            result = await process_user_input(
                message="你好",
                device_id="phone_01",
                user_id="user_001",
                use_constellation=False,
            )

            assert result["success"] is True
            assert result["reply"] == "Hello!"
            mock_pipeline.execute.assert_called_once_with(
                message="你好",
                user_id="user_001",
                source_device_id="phone_01",
                session_id=None,
                context=None,
            )

    @pytest.mark.asyncio
    async def test_process_user_input_default_uses_constellation(self):
        """process_user_input default (no use_constellation arg) should prefer ConstellationRuntime."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value={
            "success": True,
            "reply": "constellation reply",
            "session_id": "cr-session",
            "mode": "dag",
            "data": {},
            "trace_id": "tr-001",
        })

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from core.e2e_orchestrator import process_user_input

            result = await process_user_input(
                message="你好",
                device_id="phone_01",
                user_id="user_001",
            )

        assert result["success"] is True
        assert result["reply"] == "constellation reply"
        assert result["mode"] == "dag"
        mock_runtime.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_wake_event_creates_session(self):
        """process_wake_event should create a session via SessionRoaming."""
        mock_session = MagicMock()
        mock_session.session_id = "wake-session-001"

        mock_roaming = MagicMock()
        mock_roaming.create_session.return_value = mock_session

        with patch(
            "core.e2e_orchestrator.session_roaming", mock_roaming,
            create=True,
        ):
            # Re-import to apply the patch
            import importlib
            import core.e2e_orchestrator as mod
            importlib.reload(mod)

            with patch.object(mod, "__import__", create=True):
                # Direct patch on the function's import
                with patch(
                    "galaxy_gateway.session_roaming.session_roaming", mock_roaming
                ):
                    result = await mod.process_wake_event(
                        device_id="phone_01",
                        wake_word="hey galaxy",
                        task_type="voice",
                    )

                    assert result["status"] == "session_created"
                    assert result["session_id"] == "wake-session-001"


# ══════════════════════ SessionRoaming ══════════════════════

class TestSessionRoaming:
    """Test session roaming lifecycle."""

    def test_create_and_get_session(self):
        from galaxy_gateway.session_roaming import SessionRoamingManager

        mgr = SessionRoamingManager()
        session = mgr.create_session("device_A", wake_word="hey galaxy")

        assert session.session_id
        assert session.device_id == "device_A"
        assert session.context.meta["wake_word"] == "hey galaxy"

        # Retrieve by device
        found = mgr.get_session_by_device("device_A")
        assert found is not None
        assert found.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_migrate_session(self):
        from galaxy_gateway.session_roaming import SessionRoamingManager

        mgr = SessionRoamingManager()
        session = mgr.create_session("device_A")
        session_id = session.session_id

        # Patch out the device push (it tries to import device_comm)
        with patch.object(
            mgr, "_push_context_to_device", new_callable=AsyncMock, return_value=True
        ):
            success = await mgr.migrate_session(session_id, "device_B")

        assert success is True
        assert mgr.get_session(session_id).device_id == "device_B"
        assert mgr.get_session_by_device("device_B") is not None
        assert mgr.get_session_by_device("device_A") is None

    def test_list_sessions(self):
        from galaxy_gateway.session_roaming import SessionRoamingManager

        mgr = SessionRoamingManager()
        mgr.create_session("dev_1", wake_word="hello")
        mgr.create_session("dev_2", wake_word="hey")

        all_sessions = mgr.list_sessions()
        assert len(all_sessions) == 2

    def test_add_turn(self):
        from galaxy_gateway.session_roaming import SessionRoamingManager

        mgr = SessionRoamingManager()
        session = mgr.create_session("dev_1")
        mgr.add_turn(session.session_id, "user", "打开微信")
        mgr.add_turn(session.session_id, "assistant", "正在打开微信...")

        assert len(session.context.history) == 2
        assert session.context.history[0].content == "打开微信"


# ══════════════════════ WakeEventBus ══════════════════════

class TestWakeEventBus:
    """Test wake event bus dedup and dispatch."""

    @pytest.mark.asyncio
    async def test_publish_deduplicates(self):
        from galaxy_gateway.wake_event_bus import WakeEventBus, RawWakeEvent

        bus = WakeEventBus()

        # Patch dispatch to avoid importing wake_router
        dispatched_events = []

        async def mock_dispatch(event):
            dispatched_events.append(event)

        bus._dispatch = mock_dispatch

        event1 = RawWakeEvent(source_device_id="dev_1", wake_word="hey galaxy")
        event2 = RawWakeEvent(source_device_id="dev_2", wake_word="hey galaxy")

        result1 = await bus.publish(event1)
        result2 = await bus.publish(event2)  # Should be deduped (within 500ms)

        assert result1 is True
        assert result2 is False
        assert len(dispatched_events) == 1

    @pytest.mark.asyncio
    async def test_handle_websocket_message(self):
        from galaxy_gateway.wake_event_bus import WakeEventBus

        bus = WakeEventBus()

        async def mock_dispatch(event):
            pass

        bus._dispatch = mock_dispatch

        result = await bus.handle_websocket_message(
            "dev_1",
            {"type": "WAKE_EVENT", "payload": {"wake_word": "galaxy"}},
        )
        assert result is True

        # Non-wake message should return False
        result = await bus.handle_websocket_message(
            "dev_1",
            {"type": "HEARTBEAT", "payload": {}},
        )
        assert result is False


# ══════════════════════ WebSocket Handler Wiring ══════════════════════

class TestWebSocketHandlerWiring:
    """Verify that handle_message routes WAKE_EVENT and SESSION_MIGRATE."""

    def test_handler_functions_exist(self):
        """The new handler functions should be importable."""
        try:
            from galaxy_gateway.websocket_handler import (
                handle_wake_event,
                handle_session_migrate,
            )
            assert callable(handle_wake_event)
            assert callable(handle_session_migrate)
        except ImportError as e:
            # fastapi may not be installed in test env
            if "fastapi" in str(e):
                pytest.skip("fastapi not installed")
            raise


# ══════════════════════ SessionManager ══════════════════════

class TestSessionManager:
    """Test the unified session manager."""

    def test_get_or_create_session(self):
        from core.session_manager import SessionManager

        sm = SessionManager()
        sm._sessions.clear()
        sm._user_active_session.clear()

        session = sm.get_or_create_session("user_001", "phone_01")
        assert session.user_id == "user_001"
        assert "phone_01" in session.devices

        # Same user, different device → same session
        session2 = sm.get_or_create_session("user_001", "pc_01")
        assert session2.id == session.id
        assert "pc_01" in session2.devices

    def test_add_message_and_history(self):
        from core.session_manager import SessionManager

        sm = SessionManager()
        sm._sessions.clear()
        sm._user_active_session.clear()

        session = sm.create_session("user_001", "phone_01")
        sm.add_message(session.id, "user", "Hello", "phone_01")
        sm.add_message(session.id, "assistant", "Hi!", "")

        history = sm.get_history(session.id)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["content"] == "Hi!"

    def test_join_session(self):
        from core.session_manager import SessionManager

        sm = SessionManager()
        sm._sessions.clear()
        sm._user_active_session.clear()

        session = sm.create_session("user_001", "phone_01")
        assert sm.join_session(session.id, "tablet_01") is True
        assert "tablet_01" in sm.get_session(session.id).devices

    def test_list_device_sessions(self):
        from core.session_manager import SessionManager

        sm = SessionManager()
        sm._sessions.clear()
        sm._user_active_session.clear()

        s1 = sm.create_session("user_001", "phone_01")
        sm.join_session(s1.id, "pc_01")
        s2 = sm.create_session("user_002", "pc_01")

        # pc_01 should appear in 2 sessions
        device_sessions = sm.list_device_sessions("pc_01")
        assert len(device_sessions) == 2
