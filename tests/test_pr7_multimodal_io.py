"""Tests for PR-7: multimodal I/O pipeline — audio capture service,
WebRTC session manager, runtime events, and transport router integration.

Validates:
1. MultimodalEvent schema and field defaults.
2. AudioCaptureService lifecycle and event emission.
3. WebRTCSessionManager lifecycle, reconnect, and event emission.
4. SmartTransportRouter fallback event integration.
5. config.json PR-7 flags.
6. core.multimodal package exports.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from typing import List
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from core.multimodal.multimodal_events import (
    AudioQualityDegradedEvent,
    AudioStreamErrorEvent,
    AudioStreamStartedEvent,
    AudioStreamStoppedEvent,
    MultimodalEvent,
    MultimodalEventType,
    TransportFallbackEvent,
    WebRTCQualityMetricsEvent,
    WebRTCReconnectingEvent,
    WebRTCSessionErrorEvent,
    WebRTCSessionStartedEvent,
    WebRTCSessionStoppedEvent,
)

# Re-import from the correct modules for service classes
from core.multimodal.audio_capture_service import (
    AudioCaptureConfig,
    AudioCaptureService,
)
from core.multimodal.webrtc_session_manager import (
    WebRTCManagerConfig,
    WebRTCSessionManager,
)
from core.multimodal.signal_quality import QualityFlag, SignalQuality


# ===========================================================================
# Helpers
# ===========================================================================

def _collect_events(service) -> List[MultimodalEvent]:
    """Wire an event listener to *service* and return the shared list."""
    received: List[MultimodalEvent] = []
    service.add_event_listener(received.append)
    return received


# ===========================================================================
# 1. MultimodalEvent schema
# ===========================================================================


class TestMultimodalEventSchema:
    """Verify event dataclass defaults and required fields."""

    def test_event_has_unique_id(self):
        e1 = AudioStreamStartedEvent()
        e2 = AudioStreamStartedEvent()
        assert e1.event_id != e2.event_id

    def test_event_timestamp_is_positive(self):
        e = AudioStreamStartedEvent()
        assert e.timestamp > 0

    def test_event_type_enum_values(self):
        assert MultimodalEventType.AUDIO_STREAM_STARTED == "audio.stream.started"
        assert MultimodalEventType.WEBRTC_SESSION_STARTED == "webrtc.session.started"
        assert MultimodalEventType.TRANSPORT_FALLBACK == "transport.fallback"

    def test_trace_id_and_session_id_propagated(self):
        e = AudioStreamStartedEvent(
            trace_id="trace-123",
            runtime_session_id="session-456",
        )
        assert e.trace_id == "trace-123"
        assert e.runtime_session_id == "session-456"

    def test_audio_started_event_fields(self):
        e = AudioStreamStartedEvent(sample_rate=22050, chunk_duration_ms=50)
        assert e.event_type == MultimodalEventType.AUDIO_STREAM_STARTED
        assert e.sample_rate == 22050
        assert e.chunk_duration_ms == 50

    def test_audio_stopped_event_fields(self):
        e = AudioStreamStoppedEvent(total_chunks_processed=42, total_duration_s=4.2)
        assert e.event_type == MultimodalEventType.AUDIO_STREAM_STOPPED
        assert e.total_chunks_processed == 42

    def test_audio_error_event_fields(self):
        e = AudioStreamErrorEvent(error="mic gone", recoverable=False)
        assert e.event_type == MultimodalEventType.AUDIO_STREAM_ERROR
        assert e.error == "mic gone"
        assert not e.recoverable

    def test_audio_quality_degraded_event_fields(self):
        e = AudioQualityDegradedEvent(latency_ms=250.0, quality_flag="degraded")
        assert e.event_type == MultimodalEventType.AUDIO_QUALITY_DEGRADED
        assert e.latency_ms == 250.0

    def test_webrtc_session_started_event_fields(self):
        e = WebRTCSessionStartedEvent(session_id="s1", has_video=True)
        assert e.event_type == MultimodalEventType.WEBRTC_SESSION_STARTED
        assert e.has_video

    def test_webrtc_session_stopped_event_fields(self):
        e = WebRTCSessionStoppedEvent(session_id="s1", total_reconnect_attempts=3)
        assert e.event_type == MultimodalEventType.WEBRTC_SESSION_STOPPED
        assert e.total_reconnect_attempts == 3

    def test_webrtc_session_error_event_fields(self):
        e = WebRTCSessionErrorEvent(session_id="s1", error="ICE fail", recoverable=True)
        assert e.event_type == MultimodalEventType.WEBRTC_SESSION_ERROR
        assert e.recoverable

    def test_webrtc_reconnecting_event_fields(self):
        e = WebRTCReconnectingEvent(session_id="s1", attempt=2, max_attempts=5)
        assert e.event_type == MultimodalEventType.WEBRTC_RECONNECTING
        assert e.attempt == 2

    def test_webrtc_quality_metrics_event_fields(self):
        e = WebRTCQualityMetricsEvent(
            session_id="s1", bitrate_kbps=512.0, packet_loss_pct=0.5, rtt_ms=32.0
        )
        assert e.event_type == MultimodalEventType.WEBRTC_QUALITY_METRICS
        assert e.rtt_ms == 32.0

    def test_transport_fallback_event_fields(self):
        e = TransportFallbackEvent(
            from_method="webrtc", to_method="http", reason="unavailable", device_id="d1"
        )
        assert e.event_type == MultimodalEventType.TRANSPORT_FALLBACK
        assert e.device_id == "d1"


# ===========================================================================
# 2. AudioCaptureService lifecycle
# ===========================================================================


class TestAudioCaptureService:
    """AudioCaptureService must emit lifecycle events and respect config."""

    def test_is_available_reflects_pipeline(self):
        svc = AudioCaptureService()
        # Availability matches underlying sounddevice availability — just
        # check the property exists and returns a bool.
        assert isinstance(svc.is_available, bool)

    def test_add_asr_callback(self):
        svc = AudioCaptureService()
        cb = MagicMock()
        svc.add_asr_callback(cb)
        assert cb in svc._asr_callbacks

    def test_add_event_listener(self):
        svc = AudioCaptureService()
        listener = MagicMock()
        svc.add_event_listener(listener)
        assert listener in svc._event_listeners

    def test_get_latest_returns_tuple(self):
        svc = AudioCaptureService()
        result = svc.get_latest()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_start_emits_started_event_when_available(self):
        svc = AudioCaptureService()
        received: List[MultimodalEvent] = _collect_events(svc)

        with patch.object(type(svc), "is_available", new_callable=PropertyMock, return_value=True):
            # Patch pipeline.run to be a no-op coroutine
            async def _noop():
                pass

            with patch.object(svc._pipeline, "run", side_effect=_noop):
                asyncio.get_running_loop().run_until_complete(svc.start())

        started = [e for e in received if e.event_type == MultimodalEventType.AUDIO_STREAM_STARTED]
        assert len(started) >= 1

    def test_start_noop_when_unavailable(self):
        svc = AudioCaptureService()
        received: List[MultimodalEvent] = _collect_events(svc)

        with patch.object(type(svc), "is_available", new_callable=PropertyMock, return_value=False):
            asyncio.get_running_loop().run_until_complete(svc.start())

        started = [e for e in received if e.event_type == MultimodalEventType.AUDIO_STREAM_STARTED]
        assert len(started) == 0

    def test_stop_emits_stopped_event(self):
        svc = AudioCaptureService()
        received: List[MultimodalEvent] = _collect_events(svc)
        asyncio.get_running_loop().run_until_complete(svc.stop())
        stopped = [e for e in received if e.event_type == MultimodalEventType.AUDIO_STREAM_STOPPED]
        assert len(stopped) >= 1

    def test_asr_callback_invoked_on_chunk(self):
        """_on_audio_chunk forwards state to registered ASR callbacks."""
        svc = AudioCaptureService()
        asr_calls: list = []
        svc.add_asr_callback(lambda s, q: asr_calls.append((s, q)))

        from core.multimodal.audio_features import AudioState

        fake_state = AudioState(
            energy=0.5,
            speaking_ratio=0.6,
            pause_density=0.1,
            noise_level=0.2,
            audio_freshness_ms=50.0,
            is_speaking=True,
        )
        fake_quality = SignalQuality.ok(freshness_ms=10.0)
        svc._on_audio_chunk(fake_state, fake_quality)

        assert len(asr_calls) == 1
        assert asr_calls[0][0] is fake_state

    def test_latency_warning_emits_quality_degraded_event(self):
        """High-latency chunk triggers AudioQualityDegradedEvent."""
        cfg = AudioCaptureConfig(latency_warning_ms=50.0)
        svc = AudioCaptureService(config=cfg)
        received: List[MultimodalEvent] = _collect_events(svc)

        from core.multimodal.audio_features import AudioState

        fake_state = AudioState(
            energy=0.1, speaking_ratio=0.0, pause_density=0.0,
            noise_level=0.0, audio_freshness_ms=300.0, is_speaking=False,
        )
        # Quality with freshness_ms > threshold
        fake_quality = SignalQuality.ok(freshness_ms=300.0)
        svc._on_audio_chunk(fake_state, fake_quality)

        degraded = [
            e for e in received
            if e.event_type == MultimodalEventType.AUDIO_QUALITY_DEGRADED
        ]
        assert len(degraded) == 1
        assert degraded[0].latency_ms == 300.0

    def test_trace_id_propagated_to_events(self):
        cfg = AudioCaptureConfig(
            trace_id="trace-abc", runtime_session_id="sess-xyz"
        )
        svc = AudioCaptureService(config=cfg)
        received: List[MultimodalEvent] = _collect_events(svc)
        asyncio.get_running_loop().run_until_complete(svc.stop())
        for event in received:
            assert event.trace_id == "trace-abc"
            assert event.runtime_session_id == "sess-xyz"

    def test_idempotent_start(self):
        """Calling start() twice must not create duplicate tasks."""
        svc = AudioCaptureService()

        async def _noop():
            await asyncio.sleep(0.05)

        with patch.object(type(svc), "is_available", new_callable=PropertyMock, return_value=True):
            with patch.object(svc._pipeline, "run", side_effect=_noop):
                async def _double_start():
                    await svc.start()
                    task1 = svc._task
                    await svc.start()  # should be no-op
                    task2 = svc._task
                    assert task1 is task2
                    await svc.stop()

                asyncio.get_running_loop().run_until_complete(_double_start())


# ===========================================================================
# 3. WebRTCSessionManager lifecycle
# ===========================================================================


class TestWebRTCSessionManager:
    """WebRTCSessionManager must manage lifecycle and emit events."""

    def test_is_available_returns_bool(self):
        mgr = WebRTCSessionManager()
        assert isinstance(mgr.is_available, bool)

    def test_session_id_is_set(self):
        mgr = WebRTCSessionManager()
        assert mgr.session_id

    def test_add_event_listener(self):
        mgr = WebRTCSessionManager()
        listener = MagicMock()
        mgr.add_event_listener(listener)
        assert listener in mgr._event_listeners

    def test_add_frame_callback(self):
        mgr = WebRTCSessionManager()
        cb = MagicMock()
        mgr.add_frame_callback(cb)
        assert cb in mgr._frame_callbacks
        assert cb in mgr._session._frame_callbacks

    def test_get_latest_frame_returns_tuple(self):
        mgr = WebRTCSessionManager()
        result = mgr.get_latest_frame()
        assert isinstance(result, tuple) and len(result) == 2

    def test_connect_emits_error_when_unavailable(self):
        mgr = WebRTCSessionManager()
        received: List[MultimodalEvent] = _collect_events(mgr)

        with patch.object(type(mgr), "is_available", new_callable=PropertyMock, return_value=False):
            result = asyncio.get_running_loop().run_until_complete(mgr.connect("fake-sdp"))

        assert result is None
        errors = [e for e in received if e.event_type == MultimodalEventType.WEBRTC_SESSION_ERROR]
        assert len(errors) == 1
        assert not errors[0].recoverable

    def test_close_emits_stopped_event(self):
        mgr = WebRTCSessionManager()
        received: List[MultimodalEvent] = _collect_events(mgr)
        asyncio.get_running_loop().run_until_complete(mgr.close())
        stopped = [e for e in received if e.event_type == MultimodalEventType.WEBRTC_SESSION_STOPPED]
        assert len(stopped) >= 1

    def test_connect_success_emits_started_event(self):
        """Successful connect() emits WebRTCSessionStartedEvent."""
        mgr = WebRTCSessionManager()
        received: List[MultimodalEvent] = _collect_events(mgr)

        with patch.object(type(mgr), "is_available", new_callable=PropertyMock, return_value=True):
            with patch.object(
                mgr._session, "connect", new_callable=AsyncMock, return_value="answer-sdp"
            ):
                answer = asyncio.get_running_loop().run_until_complete(mgr.connect("offer"))

        assert answer == "answer-sdp"
        started = [e for e in received if e.event_type == MultimodalEventType.WEBRTC_SESSION_STARTED]
        assert len(started) == 1

    def test_connect_failure_emits_error_event(self):
        """connect() returning None emits WebRTCSessionErrorEvent."""
        mgr = WebRTCSessionManager()
        received: List[MultimodalEvent] = _collect_events(mgr)

        with patch.object(type(mgr), "is_available", new_callable=PropertyMock, return_value=True):
            with patch.object(
                mgr._session, "connect", new_callable=AsyncMock, return_value=None
            ):
                result = asyncio.get_running_loop().run_until_complete(mgr.connect("offer"))

        assert result is None
        errors = [e for e in received if e.event_type == MultimodalEventType.WEBRTC_SESSION_ERROR]
        assert len(errors) == 1

    def test_reconnect_without_prior_offer_returns_none(self):
        mgr = WebRTCSessionManager()
        result = asyncio.get_running_loop().run_until_complete(mgr.reconnect())
        assert result is None

    def test_reconnect_emits_reconnecting_event(self):
        mgr = WebRTCSessionManager(
            config=WebRTCManagerConfig(reconnect_delay_s=0.0, max_reconnects=3)
        )
        mgr._last_offer_sdp = "offer"
        received: List[MultimodalEvent] = _collect_events(mgr)

        with patch.object(
            mgr._session, "connect", new_callable=AsyncMock, return_value="answer"
        ):
            asyncio.get_running_loop().run_until_complete(mgr.reconnect())

        reconnecting = [
            e for e in received if e.event_type == MultimodalEventType.WEBRTC_RECONNECTING
        ]
        assert len(reconnecting) >= 1
        assert reconnecting[0].attempt == 1

    def test_max_reconnects_exhausted_emits_stopped(self):
        mgr = WebRTCSessionManager(
            config=WebRTCManagerConfig(max_reconnects=2, reconnect_delay_s=0.0)
        )
        mgr._last_offer_sdp = "offer"
        mgr._reconnect_attempts = 2  # already at max
        received: List[MultimodalEvent] = _collect_events(mgr)

        result = asyncio.get_running_loop().run_until_complete(mgr.reconnect())

        assert result is None
        stopped = [e for e in received if e.event_type == MultimodalEventType.WEBRTC_SESSION_STOPPED]
        assert len(stopped) >= 1
        assert stopped[0].reason == "max_reconnects_exhausted"

    def test_trace_id_propagated_to_events(self):
        cfg = WebRTCManagerConfig(
            trace_id="trace-xyz", runtime_session_id="sess-abc"
        )
        mgr = WebRTCSessionManager(config=cfg)
        received: List[MultimodalEvent] = _collect_events(mgr)
        asyncio.get_running_loop().run_until_complete(mgr.close())
        for event in received:
            assert event.trace_id == "trace-xyz"
            assert event.runtime_session_id == "sess-abc"


# ===========================================================================
# 4. SmartTransportRouter fallback event integration
# ===========================================================================


class TestTransportRouterFallback:
    """SmartTransportRouter must emit TransportFallbackEvent on WebRTC failure."""

    def test_add_event_listener(self):
        from galaxy_gateway.smart_transport_router import SmartTransportRouter

        router = SmartTransportRouter()
        listener = MagicMock()
        router.add_event_listener(listener)
        assert listener in router._event_listeners

    def test_fallback_event_emitted_when_webrtc_unavailable(self):
        from galaxy_gateway.smart_transport_router import (
            SmartTransportRouter,
            TransportRequest,
        )

        router = SmartTransportRouter()
        router.webrtc_enabled = True  # pretend WebRTC is enabled
        received: List[MultimodalEvent] = []
        router.add_event_listener(received.append)

        req = TransportRequest(
            device_id="dev-1",
            task_type="interactive",
            realtime=True,
        )

        # _is_method_available returns False → fallback should be triggered
        async def _run():
            with patch.object(router, "_is_method_available", return_value=False):
                return await router.route(req)

        resp = asyncio.get_running_loop().run_until_complete(_run())
        assert resp.success

        fallbacks = [e for e in received if e.event_type == MultimodalEventType.TRANSPORT_FALLBACK]
        assert len(fallbacks) == 1
        assert fallbacks[0].from_method == "webrtc"
        assert fallbacks[0].device_id == "dev-1"

    def test_no_fallback_event_when_webrtc_disabled(self):
        """When webrtc_enabled is False no fallback event should be emitted."""
        from galaxy_gateway.smart_transport_router import (
            SmartTransportRouter,
            TransportRequest,
        )

        router = SmartTransportRouter()
        router.webrtc_enabled = False
        received: List[MultimodalEvent] = []
        router.add_event_listener(received.append)

        req = TransportRequest(device_id="dev-2", task_type="interactive")

        asyncio.get_running_loop().run_until_complete(router.route(req))
        fallbacks = [e for e in received if e.event_type == MultimodalEventType.TRANSPORT_FALLBACK]
        assert len(fallbacks) == 0

    def test_no_fallback_when_webrtc_selected(self):
        """When WebRTC is actually selected no fallback event is emitted."""
        from galaxy_gateway.smart_transport_router import (
            SmartTransportRouter,
            TransportMethod,
            TransportRequest,
        )

        router = SmartTransportRouter()
        router.webrtc_enabled = True
        received: List[MultimodalEvent] = []
        router.add_event_listener(received.append)

        req = TransportRequest(
            device_id="dev-3", task_type="interactive", realtime=True
        )

        async def _run():
            with patch.object(router, "_is_method_available", return_value=True):
                return await router.route(req)

        asyncio.get_running_loop().run_until_complete(_run())
        fallbacks = [e for e in received if e.event_type == MultimodalEventType.TRANSPORT_FALLBACK]
        assert len(fallbacks) == 0


# ===========================================================================
# 5. config.json PR-7 flags
# ===========================================================================


class TestPR7ConfigFlags:
    """Required PR-7 configuration keys must be present in config.json."""

    _CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"

    @classmethod
    def _load(cls) -> dict:
        return json.loads(cls._CONFIG_PATH.read_text())

    def test_enable_webrtc_session_manager_present(self):
        assert "enable_webrtc_session_manager" in self._load()

    def test_webrtc_max_reconnects_present(self):
        assert "webrtc_max_reconnects" in self._load()

    def test_webrtc_reconnect_delay_s_present(self):
        assert "webrtc_reconnect_delay_s" in self._load()

    def test_audio_capture_chunk_ms_present(self):
        assert "audio_capture_chunk_ms" in self._load()

    def test_transport_prefer_webrtc_present(self):
        assert "transport_prefer_webrtc" in self._load()

    def test_transport_fallback_to_screenshot_present(self):
        assert "transport_fallback_to_screenshot" in self._load()

    def test_flag_types_valid(self):
        cfg = self._load()
        assert isinstance(cfg["enable_webrtc_session_manager"], bool)
        assert isinstance(cfg["webrtc_max_reconnects"], int)
        assert isinstance(cfg["transport_prefer_webrtc"], bool)


# ===========================================================================
# 6. core.multimodal package exports
# ===========================================================================


class TestMultimodalPackageExports:
    """core.multimodal.__init__ must export all PR-7 symbols."""

    def test_event_exports(self):
        from core.multimodal import (  # noqa: F401
            MultimodalEventType,
            MultimodalEvent,
            AudioStreamStartedEvent,
            AudioStreamStoppedEvent,
            AudioStreamErrorEvent,
            AudioQualityDegradedEvent,
            WebRTCSessionStartedEvent,
            WebRTCSessionStoppedEvent,
            WebRTCSessionErrorEvent,
            WebRTCReconnectingEvent,
            WebRTCQualityMetricsEvent,
            TransportFallbackEvent,
        )

    def test_service_exports(self):
        from core.multimodal import (  # noqa: F401
            AudioCaptureService,
            AudioCaptureConfig,
            WebRTCSessionManager,
            WebRTCManagerConfig,
        )

    def test_existing_exports_still_present(self):
        from core.multimodal import (  # noqa: F401
            SignalQuality,
            QualityFlag,
            PerceptionFrame,
            SystemSignals,
            MultimodalIngressBus,
        )
