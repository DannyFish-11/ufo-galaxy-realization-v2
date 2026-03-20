"""
PR-5 Cross-Device Mode Unification — test suite
=================================================

Validates the unified cross-device takeover conditions in
``resolve_entry_mode`` (``core/unified/entrypoint_router.py``):

1. Explicit ``entry_mode`` override always wins over auto-detection.
2. Cross-device disabled (``GALAXY_CROSS_DEVICE_ENABLED=0``) → ``"local"``.
3. Cross-device enabled + >=2 online devices → ``"cross_device"``.
4. Cross-device enabled + explicit ``target_device`` → ``"cross_device"``
   (even with 0 or 1 online devices).
5. Cross-device enabled + 1 device + no target_device → ``"local"``.
6. Observability event payload includes ``device_count`` and ``trace_id``.
7. ``process_user_input`` (e2e_orchestrator) accepts and forwards
   ``target_device`` to ``resolve_entry_mode``.
8. ``ChatRequest`` (core/_models) accepts ``target_device`` field.
9. ``galaxy_gateway/app.py`` ChatRequest accepts ``target_device`` field.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a patched UDM returning a given device count
# ---------------------------------------------------------------------------

def _mock_udm(count: int) -> MagicMock:
    m = MagicMock()
    m.get_online_count.return_value = count
    return m


# ---------------------------------------------------------------------------
# 1. Explicit override wins
# ---------------------------------------------------------------------------

class TestExplicitOverrideWins:
    """Explicit entry_mode must always be returned unchanged."""

    def test_explicit_local_wins_over_two_devices(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(5),
            ):
                result = resolve_entry_mode(explicit_entry_mode="local")
        assert result == "local"

    def test_explicit_cross_device_wins_over_disabled_flag(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode(explicit_entry_mode="cross_device")
        assert result == "cross_device"

    def test_explicit_hybrid_preserved(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode(explicit_entry_mode="hybrid")
        assert result == "hybrid"

    def test_empty_string_not_treated_as_explicit(self):
        """An empty string for explicit_entry_mode should fall through to auto."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode(explicit_entry_mode="")
        assert result == "local"


# ---------------------------------------------------------------------------
# 2. Cross-device disabled → "local"
# ---------------------------------------------------------------------------

class TestCrossDeviceDisabledToLocal:

    def test_disabled_flag_returns_local(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode()
        assert result == "local"

    def test_disabled_flag_ignores_device_count(self):
        """Even with many devices, disabled switch → local."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(10),
            ):
                result = resolve_entry_mode()
        assert result == "local"

    def test_disabled_flag_ignores_target_device(self):
        """Even with target_device, disabled switch → local."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode(target_device="device-xyz")
        assert result == "local"


# ---------------------------------------------------------------------------
# 3. >=2 devices and enabled → "cross_device"
# ---------------------------------------------------------------------------

class TestAutoResolutionTwoDevices:

    def test_two_devices_returns_cross_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(2),
            ):
                result = resolve_entry_mode()
        assert result == "cross_device"

    def test_many_devices_returns_cross_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(7),
            ):
                result = resolve_entry_mode()
        assert result == "cross_device"

    def test_one_device_returns_local(self):
        """Exactly 1 device is not sufficient for cross_device auto."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(1),
            ):
                result = resolve_entry_mode()
        assert result == "local"

    def test_zero_devices_returns_local(self):
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(0),
            ):
                result = resolve_entry_mode()
        assert result == "local"


# ---------------------------------------------------------------------------
# 4. Explicit target_device → "cross_device" (when enabled)
# ---------------------------------------------------------------------------

class TestTargetDeviceForcesCrossDevice:

    def test_target_device_with_zero_online_devices(self):
        """target_device alone (no other online devices) → cross_device."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(0),
            ):
                result = resolve_entry_mode(target_device="phone-001")
        assert result == "cross_device"

    def test_target_device_with_one_online_device(self):
        """target_device + only 1 online device → cross_device."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(1),
            ):
                result = resolve_entry_mode(target_device="tablet-002")
        assert result == "cross_device"

    def test_empty_target_device_not_treated_as_explicit(self):
        """An empty target_device string should not trigger cross_device."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(1),
            ):
                result = resolve_entry_mode(target_device="")
        assert result == "local"

    def test_whitespace_target_device_not_treated_as_explicit(self):
        """A whitespace-only target_device should not trigger cross_device."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
            with patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=_mock_udm(1),
            ):
                result = resolve_entry_mode(target_device="   ")
        assert result == "local"

    def test_target_device_disabled_flag_returns_local(self):
        """target_device + disabled flag → still local."""
        from core.unified.entrypoint_router import resolve_entry_mode

        with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
            result = resolve_entry_mode(target_device="phone-001")
        assert result == "local"


# ---------------------------------------------------------------------------
# 5. Observability: event payload includes device_count and trace_id
# ---------------------------------------------------------------------------

class TestObservabilityEventPayload:

    def test_event_payload_has_device_count(self):
        from core.unified.entrypoint_router import resolve_entry_mode
        from core.state_event_bus import get_state_event_bus, StateEventType, reset_state_event_bus

        reset_state_event_bus()
        bus = get_state_event_bus()
        received: list = []

        def _listener(event):
            received.append(event)

        token = bus.subscribe(StateEventType.ENTRY_MODE_RESOLVED, _listener)
        try:
            with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
                with patch(
                    "core.unified.device_manager.get_unified_device_manager",
                    return_value=_mock_udm(3),
                ):
                    resolve_entry_mode(trace_id="trace-obs-001", source="test")
        finally:
            bus.unsubscribe(token)

        assert len(received) >= 1, "Expected at least one ENTRY_MODE_RESOLVED event"
        payload = received[0].payload
        assert "device_count" in payload, f"device_count missing from payload: {payload}"
        assert payload["device_count"] == 3
        assert payload["trace_id"] == "trace-obs-001"
        assert payload["entry_mode"] == "cross_device"

    def test_event_payload_has_target_device(self):
        from core.unified.entrypoint_router import resolve_entry_mode
        from core.state_event_bus import get_state_event_bus, StateEventType, reset_state_event_bus

        reset_state_event_bus()
        bus = get_state_event_bus()
        received: list = []

        def _listener(event):
            received.append(event)

        token = bus.subscribe(StateEventType.ENTRY_MODE_RESOLVED, _listener)
        try:
            with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "1"}):
                with patch(
                    "core.unified.device_manager.get_unified_device_manager",
                    return_value=_mock_udm(0),
                ):
                    resolve_entry_mode(
                        target_device="device-abc",
                        trace_id="trace-obs-002",
                        source="test",
                    )
        finally:
            bus.unsubscribe(token)

        assert len(received) >= 1
        payload = received[0].payload
        assert payload.get("target_device") == "device-abc"
        assert payload.get("entry_mode") == "cross_device"

    def test_event_payload_local_has_zero_device_count(self):
        """In local mode the device_count in the event should still be present."""
        from core.unified.entrypoint_router import resolve_entry_mode
        from core.state_event_bus import get_state_event_bus, StateEventType, reset_state_event_bus

        reset_state_event_bus()
        bus = get_state_event_bus()
        received: list = []

        def _listener(event):
            received.append(event)

        token = bus.subscribe(StateEventType.ENTRY_MODE_RESOLVED, _listener)
        try:
            with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
                resolve_entry_mode(trace_id="trace-local-001", source="test")
        finally:
            bus.unsubscribe(token)

        assert len(received) >= 1
        payload = received[0].payload
        assert "device_count" in payload, f"device_count missing from payload: {payload}"
        assert payload["entry_mode"] == "local"


# ---------------------------------------------------------------------------
# 6. process_user_input accepts target_device
# ---------------------------------------------------------------------------

class TestE2EOrchestratorTargetDevice:

    @pytest.mark.asyncio
    async def test_target_device_forwarded_to_resolve_entry_mode(self):
        """process_user_input must pass target_device to resolve_entry_mode."""
        from core.e2e_orchestrator import process_user_input

        captured_kwargs: Dict[str, Any] = {}

        def _fake_resolve(explicit_entry_mode=None, *, target_device=None,
                          trace_id="", source=""):
            captured_kwargs["explicit_entry_mode"] = explicit_entry_mode
            captured_kwargs["target_device"] = target_device
            return "cross_device"

        with patch(
            "core.unified.entrypoint_router.resolve_entry_mode", side_effect=_fake_resolve
        ):
            # Mock DesktopPresenceRuntime so we don't need the full stack
            mock_runtime = MagicMock()
            mock_runtime.handle_request = MagicMock(
                return_value={"success": True, "response": "ok", "metadata": {}}
            )

            async def _fake_handle(**kw):
                return {"success": True, "response": "ok", "metadata": {}}

            mock_runtime.handle_request = _fake_handle

            with patch(
                "core.desktop_presence_runtime.get_desktop_presence_runtime",
                return_value=mock_runtime,
            ):
                await process_user_input(
                    message="open chrome on tablet",
                    target_device="tablet-001",
                )

        assert captured_kwargs.get("target_device") == "tablet-001", (
            f"target_device not forwarded; captured={captured_kwargs}"
        )

    @pytest.mark.asyncio
    async def test_no_target_device_does_not_break(self):
        """process_user_input without target_device must still work."""
        from core.e2e_orchestrator import process_user_input

        async def _fake_handle(**kw):
            return {"success": True, "response": "ok", "metadata": {}}

        mock_runtime = MagicMock()
        mock_runtime.handle_request = _fake_handle

        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=mock_runtime,
        ):
            with patch.dict(os.environ, {"GALAXY_CROSS_DEVICE_ENABLED": "0"}):
                result = await process_user_input(message="hello")
        assert result.get("success") is True


# ---------------------------------------------------------------------------
# 7. ChatRequest model accepts target_device
# ---------------------------------------------------------------------------

class TestChatRequestTargetDevice:

    def test_core_chat_request_has_target_device(self):
        from core.routes._models import ChatRequest
        req = ChatRequest(message="test", target_device="phone-001")
        assert req.target_device == "phone-001"

    def test_core_chat_request_target_device_defaults_none(self):
        from core.routes._models import ChatRequest
        req = ChatRequest(message="test")
        assert req.target_device is None

    def test_core_chat_request_backward_compat(self):
        """Existing callers without target_device must still work."""
        from core.routes._models import ChatRequest
        req = ChatRequest(message="hello", session_id="sess1", entry_mode="local")
        assert req.target_device is None
        assert req.entry_mode == "local"

    def test_gateway_chat_request_has_target_device(self):
        gw_app = pytest.importorskip(
            "galaxy_gateway.app",
            reason="galaxy_gateway.app not importable (missing deps)",
        )
        GatewayChatRequest = gw_app.ChatRequest
        req = GatewayChatRequest(message="test", target_device="desktop-002")
        assert req.target_device == "desktop-002"

    def test_gateway_chat_request_target_device_defaults_none(self):
        gw_app = pytest.importorskip(
            "galaxy_gateway.app",
            reason="galaxy_gateway.app not importable (missing deps)",
        )
        GatewayChatRequest = gw_app.ChatRequest
        req = GatewayChatRequest(message="test")
        assert req.target_device is None
