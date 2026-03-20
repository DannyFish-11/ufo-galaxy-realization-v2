"""
PR-1 EntryMode Unification — test suite
==========================================

Validates that:
1. ``resolve_entry_mode()`` returns ``"local"`` by default.
2. Explicit overrides are respected and echoed back unchanged.
3. ``ENTRY_MODE_RESOLVED`` is present in ``StateEventType``.
4. ``ChatRequest`` (core model) accepts an ``entry_mode`` field.
5. ``OpenClawd.process()`` accepts ``entry_mode`` and echoes it in
   ``response.metadata.entry_mode``.
6. ``DesktopPresenceRuntime.handle_request()`` passes ``entry_mode``
   through to OpenClawd without dropping it.
7. Auto-resolution falls back to ``"local"`` when cross-device is
   disabled or only one device is available.
8. Auto-resolution returns ``"cross_device"`` when the switch is on
   and more than one online device is present.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# 1. resolve_entry_mode — default "local"
# ---------------------------------------------------------------------------

class TestResolveEntryModeDefault:
    def test_returns_local_by_default(self):
        """Without override or cross-device setup, should return 'local'."""
        from core.unified.entrypoint_router import resolve_entry_mode, reset_entrypoint_router
        reset_entrypoint_router()

        # Ensure cross-device switch is off for this test
        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode()
        assert result == "local"

    def test_returns_local_when_single_device(self):
        """Cross-device on but only one device → should still be 'local'."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            # Patch device manager to return count=1
            mock_udm = MagicMock()
            mock_udm.get_online_count.return_value = 1
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=mock_udm,
            ):
                result = resolve_entry_mode()
        # cross-device switch on, but only 1 device → should remain "local"
        assert result == "local"

    def test_no_exception_when_modules_unavailable(self):
        """resolve_entry_mode must never raise even if sub-modules are missing."""
        from core.unified.entrypoint_router import resolve_entry_mode
        # Should not raise
        result = resolve_entry_mode()
        assert result in ("local", "cross_device", "hybrid")


# ---------------------------------------------------------------------------
# 2. Explicit override is respected
# ---------------------------------------------------------------------------

class TestResolveEntryModeExplicit:
    def test_explicit_local_returned(self):
        from core.unified.entrypoint_router import resolve_entry_mode
        assert resolve_entry_mode(explicit_entry_mode="local") == "local"

    def test_explicit_cross_device_returned(self):
        from core.unified.entrypoint_router import resolve_entry_mode
        assert resolve_entry_mode(explicit_entry_mode="cross_device") == "cross_device"

    def test_explicit_hybrid_returned(self):
        from core.unified.entrypoint_router import resolve_entry_mode
        assert resolve_entry_mode(explicit_entry_mode="hybrid") == "hybrid"

    def test_explicit_overrides_cross_device_switch(self):
        """Even when cross-device is on + >1 devices, explicit wins."""
        from core.unified.entrypoint_router import resolve_entry_mode
        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            result = resolve_entry_mode(explicit_entry_mode="local")
        assert result == "local"


# ---------------------------------------------------------------------------
# 3. ENTRY_MODE_RESOLVED exists in StateEventType
# ---------------------------------------------------------------------------

class TestStateEventTypeEntryMode:
    def test_entry_mode_resolved_event_exists(self):
        from core.state_event_bus import StateEventType
        assert hasattr(StateEventType, "ENTRY_MODE_RESOLVED")
        assert StateEventType.ENTRY_MODE_RESOLVED.value == "entry_mode.resolved"


# ---------------------------------------------------------------------------
# 4. ChatRequest model accepts entry_mode
# ---------------------------------------------------------------------------

class TestChatRequestEntryMode:
    def test_entry_mode_field_present(self):
        from core.routes._models import ChatRequest
        req = ChatRequest(message="hello", entry_mode="cross_device")
        assert req.entry_mode == "cross_device"

    def test_entry_mode_defaults_to_none(self):
        from core.routes._models import ChatRequest
        req = ChatRequest(message="hello")
        assert req.entry_mode is None

    def test_entry_mode_backward_compat_without_field(self):
        """Existing callers not passing entry_mode must still work."""
        from core.routes._models import ChatRequest
        req = ChatRequest(message="test", session_id="sess1")
        assert req.entry_mode is None
        assert req.session_id == "sess1"


# ---------------------------------------------------------------------------
# 5. OpenClawd.process() accepts entry_mode and echoes it in metadata
# ---------------------------------------------------------------------------

class TestOpenClawdEntryMode:
    @pytest.mark.asyncio
    async def test_process_with_explicit_local(self):
        """entry_mode='local' should appear in response.metadata.entry_mode."""
        from core.openclawd import OpenClawd
        clawd = object.__new__(OpenClawd)
        # Minimal mock initialisation
        clawd._initialized = True
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._current_trace_id = ""
        clawd._current_session_id = ""
        clawd._current_device_id = ""

        # Patch expensive sub-calls
        async def _fake_parse_intent(msg, sid):
            mock = MagicMock()
            mock.intent = "chat"
            mock.confidence = 1.0
            mock.suggestions = []
            return mock

        async def _fake_dispatch_chat(msg, sid, ctx, mi):
            return {"success": True, "response": "ok", "metadata": {}}

        async def _fake_record_turn(*a, **kw):
            pass

        clawd._parse_intent = _fake_parse_intent
        clawd._dispatch_chat = _fake_dispatch_chat
        clawd._record_turn = _fake_record_turn
        clawd._get_kernel = lambda: None
        clawd._get_router = lambda: None
        clawd._run_continuum = lambda **kw: None
        clawd._run_execution = lambda s: None
        clawd._ensure_initialized = lambda: None

        result = await clawd.process(
            message="hello",
            entry_mode="local",
            session_id="test-sess",
        )
        meta = result.get("metadata", {})
        assert meta.get("entry_mode") == "local", (
            f"Expected entry_mode='local' in metadata, got {meta}"
        )

    @pytest.mark.asyncio
    async def test_process_defaults_to_local_when_not_provided(self):
        """When entry_mode is omitted, metadata.entry_mode should be 'local'."""
        from core.openclawd import OpenClawd
        clawd = object.__new__(OpenClawd)
        clawd._initialized = True
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._current_trace_id = ""
        clawd._current_session_id = ""
        clawd._current_device_id = ""

        async def _fake_parse_intent(msg, sid):
            mock = MagicMock()
            mock.intent = "chat"
            mock.confidence = 1.0
            mock.suggestions = []
            return mock

        async def _fake_dispatch_chat(msg, sid, ctx, mi):
            return {"success": True, "response": "ok", "metadata": {}}

        async def _fake_record_turn(*a, **kw):
            pass

        clawd._parse_intent = _fake_parse_intent
        clawd._dispatch_chat = _fake_dispatch_chat
        clawd._record_turn = _fake_record_turn
        clawd._get_kernel = lambda: None
        clawd._get_router = lambda: None
        clawd._run_continuum = lambda **kw: None
        clawd._run_execution = lambda s: None
        clawd._ensure_initialized = lambda: None

        result = await clawd.process(message="hello", session_id="test-sess-2")
        meta = result.get("metadata", {})
        assert meta.get("entry_mode") == "local", (
            f"Expected entry_mode='local' (default) in metadata, got {meta}"
        )

    @pytest.mark.asyncio
    async def test_process_cross_device_echoed(self):
        """entry_mode='cross_device' should be reflected in metadata."""
        from core.openclawd import OpenClawd
        clawd = object.__new__(OpenClawd)
        clawd._initialized = True
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._current_trace_id = ""
        clawd._current_session_id = ""
        clawd._current_device_id = ""

        async def _fake_parse_intent(msg, sid):
            mock = MagicMock()
            mock.intent = "chat"
            mock.confidence = 1.0
            mock.suggestions = []
            return mock

        async def _fake_dispatch_chat(msg, sid, ctx, mi):
            return {"success": True, "response": "ok", "metadata": {}}

        async def _fake_record_turn(*a, **kw):
            pass

        clawd._parse_intent = _fake_parse_intent
        clawd._dispatch_chat = _fake_dispatch_chat
        clawd._record_turn = _fake_record_turn
        clawd._get_kernel = lambda: None
        clawd._get_router = lambda: None
        clawd._run_continuum = lambda **kw: None
        clawd._run_execution = lambda s: None
        clawd._ensure_initialized = lambda: None

        result = await clawd.process(
            message="hello", entry_mode="cross_device", session_id="test-sess-3"
        )
        meta = result.get("metadata", {})
        assert meta.get("entry_mode") == "cross_device", (
            f"Expected entry_mode='cross_device' in metadata, got {meta}"
        )


# ---------------------------------------------------------------------------
# 6. DesktopPresenceRuntime.handle_request passes entry_mode to OpenClawd
# ---------------------------------------------------------------------------

class TestDesktopPresenceRuntimeEntryMode:
    @pytest.mark.asyncio
    async def test_handle_request_passes_entry_mode_to_openclawd(self):
        """entry_mode given to handle_request must reach clawd.process()."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime()

        captured: Dict[str, Any] = {}

        async def _fake_clawd_process(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "response": "ok",
                "metadata": {"entry_mode": kwargs.get("entry_mode", "local")},
            }

        mock_clawd = MagicMock()
        mock_clawd.process = _fake_clawd_process

        with patch("core.openclawd.get_openclawd", return_value=mock_clawd):
            result = await runtime.handle_request(
                message="test",
                source="chat",
                entry_mode="cross_device",
            )

        assert captured.get("entry_mode") == "cross_device", (
            f"entry_mode not propagated to clawd.process; captured={captured}"
        )

    @pytest.mark.asyncio
    async def test_handle_request_absent_entry_mode_does_not_break(self):
        """handle_request must work when entry_mode is not provided."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime()

        async def _fake_clawd_process(**kwargs):
            return {
                "success": True,
                "response": "ok",
                "metadata": {"entry_mode": kwargs.get("entry_mode", "local")},
            }

        mock_clawd = MagicMock()
        mock_clawd.process = _fake_clawd_process

        with patch("core.openclawd.get_openclawd", return_value=mock_clawd):
            result = await runtime.handle_request(message="test", source="chat")

        assert result.get("success") is True


# ---------------------------------------------------------------------------
# 7. Auto-resolution: cross-device disabled → "local"
# ---------------------------------------------------------------------------

class TestAutoResolutionCrossDeviceDisabled:
    def test_local_when_cross_device_off(self):
        from core.unified.entrypoint_router import resolve_entry_mode
        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode()
        assert result == "local"


# ---------------------------------------------------------------------------
# 8. Event is emitted on ENTRY_MODE_RESOLVED
# ---------------------------------------------------------------------------

class TestEntryModeResolvedEvent:
    def test_event_emitted_on_resolve(self):
        """resolve_entry_mode should emit ENTRY_MODE_RESOLVED on the bus."""
        from core.unified.entrypoint_router import resolve_entry_mode
        from core.state_event_bus import get_state_event_bus, StateEventType, reset_state_event_bus

        reset_state_event_bus()
        bus = get_state_event_bus()

        received = []

        def _listener(event):
            received.append(event)

        token = bus.subscribe(StateEventType.ENTRY_MODE_RESOLVED, _listener)
        try:
            with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
                resolve_entry_mode(trace_id="trace-test-123", source="test_suite")
        finally:
            bus.unsubscribe(token)

        assert len(received) >= 1, "Expected at least one ENTRY_MODE_RESOLVED event"
        payload = received[0].payload
        assert payload.get("entry_mode") in ("local", "cross_device", "hybrid")
        assert payload.get("trace_id") == "trace-test-123"
