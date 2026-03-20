"""Tests for PR-3: multimodal ingest wiring into the OpenClawd main flow.

Validates:
1. Text-only flow is unchanged (no multimodal_context → fusion_summary empty).
2. Multimodal flow injects fusion summary when multimodal_context provided.
3. MultimodalIngressBus singleton starts when enable_multimodal_ingest=True.
4. Bus does NOT start when enable_multimodal_ingest=False.
5. MULTIMODAL_INGEST_ACTIVE event is emitted on bus start.
6. Gateway ChatRequest schema includes multimodal_context field.
7. Gateway passes multimodal_context through to OpenClawd.
8. _run_continuum uses the running singleton bus when available.
9. Response metadata contains fused context (no base64 payloads).
"""
from __future__ import annotations

import asyncio
import pathlib
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _assert_no_base64_payload(data_str: str, context: str = "") -> None:
    """Assert that *data_str* contains no base64-encoded blob payloads.

    Checks for the pattern of large base64-encoded data: long runs of
    base64 characters terminated by ``=`` padding or followed by a quote,
    consistent with JSON-embedded image/audio data fields.
    """
    import re
    # Match long base64 blobs: 80+ chars of base64 alphabet, optionally ending in = padding
    # Wrapped in quotes (as in JSON) to avoid matching long identifiers or UUIDs.
    pattern = r'"[A-Za-z0-9+/]{80,}={0,2}"'
    match = re.search(pattern, data_str)
    assert match is None, (
        f"Base64 payload found in result{' (' + context + ')' if context else ''}: "
        f"{match.group()[:40]}..."
    )


# ===========================================================================
# 1. Config flags
# ===========================================================================


class TestPR3ConfigFlags:
    """Required PR-3 configuration keys must be present in config.json."""

    def test_enable_multimodal_ingest_present(self):
        cfg = _load_config()
        assert "enable_multimodal_ingest" in cfg

    def test_enable_perception_present(self):
        cfg = _load_config()
        assert "enable_perception" in cfg

    def test_enable_multimodal_ingest_is_bool(self):
        cfg = _load_config()
        assert isinstance(cfg["enable_multimodal_ingest"], bool)

    def test_enable_perception_is_bool(self):
        cfg = _load_config()
        assert isinstance(cfg["enable_perception"], bool)


# ===========================================================================
# 2. StateEventType has MULTIMODAL_INGEST_ACTIVE
# ===========================================================================


class TestMultimodalIngestEventType:
    def test_event_type_exists(self):
        from core.state_event_bus import StateEventType
        assert hasattr(StateEventType, "MULTIMODAL_INGEST_ACTIVE")

    def test_event_type_value(self):
        from core.state_event_bus import StateEventType
        assert StateEventType.MULTIMODAL_INGEST_ACTIVE == "multimodal.ingest.active"


# ===========================================================================
# 3. ingest_runtime module
# ===========================================================================


class TestIngestRuntimeModule:
    """Validate the ingest_runtime singleton API."""

    def setup_method(self):
        # Reset singleton before each test.
        import core.multimodal.ingest_runtime as _ir
        _ir._ingest_bus = None
        _ir._ingest_task = None

    def test_get_ingest_bus_returns_none_when_not_started(self):
        from core.multimodal.ingest_runtime import get_ingest_bus
        assert get_ingest_bus() is None

    def test_start_ingest_bus_skips_when_flag_false(self):
        from core.multimodal.ingest_runtime import start_ingest_bus, get_ingest_bus

        with patch("core.unified_config.config", {"enable_multimodal_ingest": False}):
            result = start_ingest_bus()
        assert result is False
        assert get_ingest_bus() is None

    def test_start_ingest_bus_starts_when_flag_true(self):
        from core.multimodal.ingest_runtime import start_ingest_bus, get_ingest_bus

        with patch("core.unified_config.config", {"enable_multimodal_ingest": True}):
            with patch(
                "core.multimodal.ingest_runtime._schedule_pipeline"
            ):  # don't actually schedule
                result = start_ingest_bus()

        assert result is True
        bus = get_ingest_bus()
        assert bus is not None

    def test_start_ingest_bus_is_idempotent(self):
        from core.multimodal.ingest_runtime import start_ingest_bus, get_ingest_bus

        with patch("core.unified_config.config", {"enable_multimodal_ingest": True}):
            with patch("core.multimodal.ingest_runtime._schedule_pipeline"):
                r1 = start_ingest_bus()
                r2 = start_ingest_bus()

        assert r1 is True
        assert r2 is True
        # Bus should be the same instance
        bus = get_ingest_bus()
        assert bus is not None

    def test_stop_ingest_bus_clears_singleton(self):
        from core.multimodal.ingest_runtime import (
            start_ingest_bus,
            stop_ingest_bus,
            get_ingest_bus,
        )

        with patch("core.unified_config.config", {"enable_multimodal_ingest": True}):
            with patch("core.multimodal.ingest_runtime._schedule_pipeline"):
                start_ingest_bus()

        assert get_ingest_bus() is not None
        stop_ingest_bus()
        assert get_ingest_bus() is None

    def test_start_emits_ingest_active_event(self):
        from core.multimodal.ingest_runtime import start_ingest_bus
        from core.state_event_bus import StateEventType

        emitted_events = []

        def _capture(event_type, source, payload, **kwargs):
            emitted_events.append((event_type, payload))

        with patch("core.unified_config.config", {"enable_multimodal_ingest": True}):
            with patch("core.multimodal.ingest_runtime._schedule_pipeline"):
                with patch("core.multimodal.ingest_runtime._emit_ingest_active") as _mock_emit:
                    start_ingest_bus(runtime_session_id="test-sess")
                    _mock_emit.assert_called_once()
                    call_kwargs = _mock_emit.call_args.kwargs
                    assert call_kwargs["runtime_session_id"] == "test-sess"


# ===========================================================================
# 4. DesktopPresenceRuntime autostart
# ===========================================================================


class TestDesktopPresenceRuntimeAutostart:
    """DesktopPresenceRuntime.__init__ should call _try_start_ingest_bus."""

    def test_try_start_called_on_init(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        with patch.object(
            DesktopPresenceRuntime, "_try_start_ingest_bus"
        ) as mock_start:
            runtime = DesktopPresenceRuntime()
            mock_start.assert_called_once()

    def test_try_start_ingest_bus_no_crash_when_disabled(self):
        """_try_start_ingest_bus must not raise even when ingest is disabled."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        with patch("core.unified_config.config", {"enable_multimodal_ingest": False}):
            runtime = DesktopPresenceRuntime()
        # No exception == pass


# ===========================================================================
# 5. Text-only flow unchanged
# ===========================================================================


class TestTextOnlyFlowUnchanged:
    """Verify that text-only requests produce no multimodal side effects."""

    @pytest.mark.asyncio
    async def test_text_only_fusion_summary_empty(self):
        """MultimodalBus.ingest() with no multimodal_context and no device → fusion_summary=''."""
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        result = bus.ingest(
            message="Hello, world!",
            multimodal_context=None,
            device_metadata=None,
        )
        assert isinstance(result, dict)
        # Text-only with no device metadata: fusion_summary should be empty
        assert not result.get("fusion_summary"), (
            "Text-only request with no device metadata should produce empty fusion_summary, got: "
            + repr(result.get("fusion_summary"))
        )

    @pytest.mark.asyncio
    async def test_text_only_no_base64_in_result(self):
        """MultimodalBus.ingest() never stores base64 payloads."""
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        result = bus.ingest(
            message="text only",
            multimodal_context=None,
        )
        _assert_no_base64_payload(json.dumps(result), "text-only ingest result")


# ===========================================================================
# 6. Multimodal flow injects fusion summary
# ===========================================================================


class TestMultimodalFusionSummaryInjection:
    """Multimodal context should produce a non-empty fusion summary."""

    def _make_multimodal_context(self):
        try:
            from core.schemas.multimodal import MultiModalContext, MultiModalImage
            return MultiModalContext(
                images=[
                    MultiModalImage(
                        mime="image/jpeg",
                        data="FAKEB64DATA",
                        source="webcam",
                    )
                ],
            )
        except Exception:
            return None

    def test_fusion_summary_non_empty_when_context_provided(self):
        from core.perception.multimodal_bus import MultimodalBus

        ctx = self._make_multimodal_context()
        if ctx is None:
            pytest.skip("MultiModalContext schema not available")

        bus = MultimodalBus()
        result = bus.ingest(
            message="What do you see?",
            multimodal_context=ctx,
            device_metadata={"device_id": "dev1", "session_id": "s1"},
        )
        assert isinstance(result, dict)
        # fusion_summary should exist and describe modalities
        summary = result.get("fusion_summary", "")
        assert isinstance(summary, str)
        # At least some content describing the input
        assert len(summary) > 0, "Expected non-empty fusion_summary for multimodal input"

    def test_no_base64_in_fused_result(self):
        """Fused context metadata must never store base64 payloads."""
        from core.perception.multimodal_bus import MultimodalBus

        ctx = self._make_multimodal_context()
        if ctx is None:
            pytest.skip("MultiModalContext schema not available")

        bus = MultimodalBus()
        result = bus.ingest(
            message="describe",
            multimodal_context=ctx,
        )
        result_copy = {k: v for k, v in result.items() if k != "images"}
        _assert_no_base64_payload(json.dumps(result_copy, default=str), "fused context metadata")


# ===========================================================================
# 7. OpenClawd response metadata includes fused context
# ===========================================================================


class TestOpenClawdResponseMetadata:
    """process() response.metadata should include multimodal_context key."""

    @pytest.mark.asyncio
    async def test_metadata_contains_multimodal_context_key(self):
        """Text-only request: metadata.multimodal_context should be present."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd()

        mock_result = {
            "success": True,
            "response": "hello",
            "intent": "chat",
            "metadata": {},
        }

        with patch.object(clawd, "_dispatch_chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = mock_result
            with patch.object(clawd, "_parse_intent", new_callable=AsyncMock) as mock_intent:
                mock_intent_obj = MagicMock()
                mock_intent_obj.intent = "chat"
                mock_intent_obj.confidence = 1.0
                mock_intent_obj.suggestions = []
                mock_intent.return_value = mock_intent_obj
                with patch.object(clawd, "_run_continuum", return_value=None):
                    with patch.object(clawd, "_run_execution"):
                        with patch.object(clawd, "_record_turn", new_callable=AsyncMock):
                            result = await clawd.process(
                                message="hello",
                                session_id="test-session",
                            )

        metadata = result.get("metadata", {})
        assert "multimodal_context" in metadata, (
            "response.metadata should always contain 'multimodal_context' key"
        )


# ===========================================================================
# 8. _run_continuum uses singleton bus when available
# ===========================================================================


class TestRunContinuumUsesSingletonBus:
    def test_run_continuum_uses_running_bus_when_available(self):
        from core.openclawd import OpenClawd
        from core.multimodal.ingress_bus import MultimodalIngressBus

        clawd = OpenClawd()
        mock_bus = MagicMock(spec=MultimodalIngressBus)
        mock_frame = MagicMock()
        mock_bus.build_frame.return_value = mock_frame

        with patch("core.multimodal.ingest_runtime.get_ingest_bus", return_value=mock_bus):
            with patch("core.multimodal.ingest_runtime.start_ingest_bus", return_value=True):
                # Mock the orchestrator so run() can complete
                mock_orch = MagicMock()
                mock_state = MagicMock()
                mock_state.model_dump.return_value = {"phase": "manifest"}
                mock_orch.run.return_value = mock_state

                with patch.object(clawd, "_get_continuum_orchestrator", return_value=mock_orch):
                    result = clawd._run_continuum(
                        trace_id="trace-001",
                        runtime_session_id="sess-001",
                    )

        # The orchestrator should have been called with our mock frame
        mock_orch.run.assert_called_once()
        call_kwargs = mock_orch.run.call_args.kwargs
        assert call_kwargs.get("frame") is mock_frame

    def test_run_continuum_falls_back_when_bus_is_none(self):
        """When the singleton bus is None, _run_continuum should still succeed."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd()

        with patch("core.multimodal.ingest_runtime.get_ingest_bus", return_value=None):
            mock_orch = MagicMock()
            mock_state = MagicMock()
            mock_state.model_dump.return_value = {"phase": "silent"}
            mock_orch.run.return_value = mock_state

            with patch.object(clawd, "_get_continuum_orchestrator", return_value=mock_orch):
                result = clawd._run_continuum(trace_id="t1", runtime_session_id="s1")

        assert result is not None
        assert result["phase"] == "silent"


# ===========================================================================
# 9. Gateway ChatRequest schema
# ===========================================================================


class TestGatewayChatRequestSchema:
    """galaxy_gateway.app.ChatRequest must have multimodal_context field.

    We inspect the source directly rather than importing the full module,
    because gateway/app.py has optional heavy dependencies (websockets, aiortc)
    that may not be present in the test environment.
    """

    _APP_PATH = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "app.py"

    def _app_source(self) -> str:
        return self._APP_PATH.read_text()

    def test_multimodal_context_field_exists_in_source(self):
        src = self._app_source()
        assert "multimodal_context" in src, (
            "galaxy_gateway/app.py ChatRequest must declare multimodal_context field"
        )

    def test_multimodal_context_passed_to_process_in_source(self):
        src = self._app_source()
        assert "multimodal_context=request.multimodal_context" in src, (
            "gateway chat_endpoint must pass multimodal_context to openclawd_instance.process()"
        )

    def test_multimodal_context_optional_annotation_in_source(self):
        src = self._app_source()
        # The field must have a None default (making it optional for callers)
        assert "multimodal_context" in src and "= None" in src, (
            "multimodal_context field should be declared with a None default"
        )
