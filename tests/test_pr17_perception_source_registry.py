"""tests/test_pr17_perception_source_registry.py — PR-17: Perception Source Registry

Validates:
1. Microphone source registration
2. Local camera (webcam) source registration
3. WebRTC source registration / update lifecycle
4. External/remote stream source registration and degraded-placeholder handling
5. Primary audio source selection
6. Primary video source selection
7. Degraded/unavailable source reporting
8. Registry snapshot serialisation (JSON-safe)
9. Shell ownership boundary — registry lives on DesktopPresenceRuntime, not OpenClawd
"""
from __future__ import annotations

import json
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry():
    from core.multimodal.perception_source_registry import PerceptionSourceRegistry
    return PerceptionSourceRegistry()


def _mic_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import PerceptionSourceType, SourceModality
    base = dict(
        source_type=PerceptionSourceType.MICROPHONE,
        modality=SourceModality.AUDIO,
        display_name="Test Microphone",
        device_id="hw:0,0",
        transport="local",
        priority=10,
    )
    base.update(overrides)
    return base


def _webcam_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import PerceptionSourceType, SourceModality
    base = dict(
        source_type=PerceptionSourceType.WEBCAM,
        modality=SourceModality.VIDEO,
        display_name="Local Webcam",
        device_id="/dev/video0",
        transport="local",
        priority=10,
    )
    base.update(overrides)
    return base


def _webrtc_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import PerceptionSourceType, SourceModality
    base = dict(
        source_type=PerceptionSourceType.WEBRTC,
        modality=SourceModality.VIDEO,
        display_name="Remote WebRTC Camera",
        transport="webrtc",
        priority=50,
    )
    base.update(overrides)
    return base


def _external_stream_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import (
        PerceptionSourceType,
        SourceModality,
        SourceHealthStatus,
    )
    base = dict(
        source_type=PerceptionSourceType.EXTERNAL_STREAM,
        modality=SourceModality.VIDEO,
        display_name="RTSP External Stream",
        transport="rtsp",
        priority=80,
        health=SourceHealthStatus.UNKNOWN,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Microphone source registration
# ---------------------------------------------------------------------------


class TestMicrophoneRegistration:
    def test_register_returns_source_id(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_registered_record_has_correct_type(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        assert record is not None
        assert record.source_type == PerceptionSourceType.MICROPHONE

    def test_registered_record_has_audio_modality(self):
        from core.multimodal.perception_source_registry import SourceModality
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        assert record.modality == SourceModality.AUDIO

    def test_registered_record_preserves_device_id(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs(device_id="hw:1,0"))
        record = registry.get(sid)
        assert record.device_id == "hw:1,0"

    def test_registered_record_preserves_transport(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        assert record.transport == "local"

    def test_initial_is_active_false(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        assert record.is_active is False

    def test_mark_active_sets_active_flag(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        record = registry.get(sid)
        assert record.is_active is True

    def test_mark_active_updates_last_seen_at(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        record = registry.get(sid)
        assert record.last_seen_at is not None

    def test_idempotent_register_with_same_source_id(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="mic-fixed"))
        sid2 = registry.register(**_mic_kwargs(source_id="mic-fixed"))
        assert sid1 == sid2
        assert len(registry.all_sources()) == 1

    def test_sources_by_type_returns_microphone(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType
        registry = _make_registry()
        registry.register(**_mic_kwargs())
        registry.register(**_webcam_kwargs())
        mics = registry.sources_by_type(PerceptionSourceType.MICROPHONE)
        assert len(mics) == 1
        assert mics[0].source_type == PerceptionSourceType.MICROPHONE


# ---------------------------------------------------------------------------
# 2. Local camera (webcam) source registration
# ---------------------------------------------------------------------------


class TestWebcamRegistration:
    def test_register_webcam_returns_source_id(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        assert isinstance(sid, str)

    def test_webcam_type_is_webcam(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        record = registry.get(sid)
        assert record.source_type == PerceptionSourceType.WEBCAM

    def test_webcam_modality_is_video(self):
        from core.multimodal.perception_source_registry import SourceModality
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        record = registry.get(sid)
        assert record.modality == SourceModality.VIDEO

    def test_webcam_device_id_preserved(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs(device_id="/dev/video1"))
        record = registry.get(sid)
        assert record.device_id == "/dev/video1"

    def test_webcam_sources_by_modality(self):
        from core.multimodal.perception_source_registry import SourceModality
        registry = _make_registry()
        registry.register(**_mic_kwargs())
        registry.register(**_webcam_kwargs())
        video_sources = registry.sources_by_modality(SourceModality.VIDEO)
        assert len(video_sources) == 1
        from core.multimodal.perception_source_registry import PerceptionSourceType
        assert video_sources[0].source_type == PerceptionSourceType.WEBCAM


# ---------------------------------------------------------------------------
# 3. WebRTC source registration / update lifecycle
# ---------------------------------------------------------------------------


class TestWebRTCSourceLifecycle:
    def test_register_webrtc_source(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        record = registry.get(sid)
        assert record is not None
        assert record.source_type == PerceptionSourceType.WEBRTC

    def test_webrtc_transport_is_webrtc(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        record = registry.get(sid)
        assert record.transport == "webrtc"

    def test_webrtc_mark_active_on_connect(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_active(sid)
        assert registry.get(sid).is_active is True

    def test_webrtc_update_quality(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_active(sid)
        registry.update_quality(sid, quality_score=0.85, latency_ms=42.0)
        record = registry.get(sid)
        assert record.quality_score == pytest.approx(0.85)
        assert record.latency_ms == pytest.approx(42.0)

    def test_webrtc_quality_score_clamped_to_0_1(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.update_quality(sid, quality_score=1.5)
        assert registry.get(sid).quality_score == pytest.approx(1.0)
        registry.update_quality(sid, quality_score=-0.3)
        assert registry.get(sid).quality_score == pytest.approx(0.0)

    def test_webrtc_mark_inactive_on_disconnect(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_active(sid)
        registry.mark_inactive(sid, reason="peer disconnected")
        record = registry.get(sid)
        assert record.is_active is False
        assert "peer disconnected" in record.degradation_reasons

    def test_webrtc_remove_clears_record(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        result = registry.remove(sid)
        assert result is True
        assert registry.get(sid) is None

    def test_webrtc_remove_nonexistent_returns_false(self):
        registry = _make_registry()
        assert registry.remove("no-such-id") is False

    def test_webrtc_active_sources_after_deactivation(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_active(sid)
        assert len(registry.active_sources()) == 1
        registry.mark_inactive(sid)
        assert len(registry.active_sources()) == 0


# ---------------------------------------------------------------------------
# 4. External/remote stream source registration and degraded placeholder
# ---------------------------------------------------------------------------


class TestExternalStreamSource:
    def test_register_external_stream(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType
        registry = _make_registry()
        sid = registry.register(**_external_stream_kwargs())
        record = registry.get(sid)
        assert record is not None
        assert record.source_type == PerceptionSourceType.EXTERNAL_STREAM

    def test_external_stream_transport_preserved(self):
        registry = _make_registry()
        sid = registry.register(**_external_stream_kwargs(transport="rtsp"))
        assert registry.get(sid).transport == "rtsp"

    def test_external_stream_can_be_marked_unavailable(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus
        registry = _make_registry()
        sid = registry.register(**_external_stream_kwargs())
        registry.mark_unavailable(sid, reason="stream endpoint unreachable")
        record = registry.get(sid)
        assert record.health == SourceHealthStatus.UNAVAILABLE
        assert "stream endpoint unreachable" in record.degradation_reasons

    def test_unavailable_source_stays_in_registry(self):
        """An unavailable source must remain registered for diagnostics."""
        registry = _make_registry()
        sid = registry.register(**_external_stream_kwargs())
        registry.mark_unavailable(sid, reason="no route to host")
        # Record still in registry
        assert registry.get(sid) is not None
        assert len(registry.all_sources()) == 1

    def test_external_stream_remote_camera_type(self):
        from core.multimodal.perception_source_registry import (
            PerceptionSourceType,
            SourceModality,
        )
        registry = _make_registry()
        sid = registry.register(
            source_type=PerceptionSourceType.REMOTE_CAMERA,
            modality=SourceModality.VIDEO,
            transport="rtsp",
            display_name="Remote RTSP Camera",
        )
        record = registry.get(sid)
        assert record.source_type == PerceptionSourceType.REMOTE_CAMERA


# ---------------------------------------------------------------------------
# 5. Primary audio source selection
# ---------------------------------------------------------------------------


class TestPrimaryAudioSelection:
    def test_set_primary_audio_succeeds_for_audio_source(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        result = registry.set_primary_audio(sid)
        assert result is True

    def test_set_primary_audio_marks_record(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.set_primary_audio(sid)
        assert registry.get(sid).is_primary_audio is True

    def test_primary_audio_id_reflects_selection(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.set_primary_audio(sid)
        assert registry.primary_audio_id == sid

    def test_primary_audio_method_returns_record(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.set_primary_audio(sid)
        record = registry.primary_audio()
        assert record is not None
        assert record.source_id == sid

    def test_switching_primary_audio_clears_previous(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="mic-1", device_id="hw:0,0"))
        sid2 = registry.register(**_mic_kwargs(source_id="mic-2", device_id="hw:1,0"))
        registry.set_primary_audio(sid1)
        registry.set_primary_audio(sid2)
        assert registry.get(sid1).is_primary_audio is False
        assert registry.get(sid2).is_primary_audio is True
        assert registry.primary_audio_id == sid2

    def test_set_primary_audio_fails_for_video_source(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        result = registry.set_primary_audio(sid)
        assert result is False
        assert registry.primary_audio_id is None

    def test_set_primary_audio_fails_for_unknown_id(self):
        registry = _make_registry()
        result = registry.set_primary_audio("nonexistent")
        assert result is False

    def test_clear_primary_audio(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.set_primary_audio(sid)
        registry.clear_primary_audio()
        assert registry.primary_audio_id is None
        assert registry.get(sid).is_primary_audio is False

    def test_remove_primary_audio_source_clears_selection(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.set_primary_audio(sid)
        registry.remove(sid)
        assert registry.primary_audio_id is None

    def test_multi_modality_source_can_be_primary_audio(self):
        from core.multimodal.perception_source_registry import (
            PerceptionSourceType,
            SourceModality,
        )
        registry = _make_registry()
        sid = registry.register(
            source_type=PerceptionSourceType.WEBRTC,
            modality=SourceModality.MULTI,
            display_name="WebRTC A/V",
        )
        result = registry.set_primary_audio(sid)
        assert result is True


# ---------------------------------------------------------------------------
# 6. Primary video source selection
# ---------------------------------------------------------------------------


class TestPrimaryVideoSelection:
    def test_set_primary_video_succeeds_for_video_source(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        result = registry.set_primary_video(sid)
        assert result is True

    def test_set_primary_video_marks_record(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.set_primary_video(sid)
        assert registry.get(sid).is_primary_video is True

    def test_primary_video_id_reflects_selection(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.set_primary_video(sid)
        assert registry.primary_video_id == sid

    def test_primary_video_method_returns_record(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.set_primary_video(sid)
        record = registry.primary_video()
        assert record is not None
        assert record.source_id == sid

    def test_switching_primary_video_clears_previous(self):
        from core.multimodal.perception_source_registry import PerceptionSourceType, SourceModality
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="cam-1"))
        sid2 = registry.register(**_webrtc_kwargs(source_id="cam-webrtc"))
        registry.set_primary_video(sid1)
        registry.set_primary_video(sid2)
        assert registry.get(sid1).is_primary_video is False
        assert registry.get(sid2).is_primary_video is True
        assert registry.primary_video_id == sid2

    def test_set_primary_video_fails_for_audio_source(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        result = registry.set_primary_video(sid)
        assert result is False
        assert registry.primary_video_id is None

    def test_set_primary_video_fails_for_unknown_id(self):
        registry = _make_registry()
        result = registry.set_primary_video("ghost")
        assert result is False

    def test_clear_primary_video(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.set_primary_video(sid)
        registry.clear_primary_video()
        assert registry.primary_video_id is None
        assert registry.get(sid).is_primary_video is False

    def test_remove_primary_video_source_clears_selection(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.set_primary_video(sid)
        registry.remove(sid)
        assert registry.primary_video_id is None


# ---------------------------------------------------------------------------
# 7. Degraded / unavailable source reporting
# ---------------------------------------------------------------------------


class TestDegradedUnavailableReporting:
    def test_mark_unavailable_sets_health_unavailable(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, reason="hardware missing")
        assert registry.get(sid).health == SourceHealthStatus.UNAVAILABLE

    def test_mark_unavailable_populates_degradation_reasons(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, reason="hardware missing")
        assert "hardware missing" in registry.get(sid).degradation_reasons

    def test_mark_degraded_sets_health_degraded(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_degraded(sid, reason="high packet loss")
        assert registry.get(sid).health == SourceHealthStatus.DEGRADED

    def test_multiple_degradation_reasons_accumulate(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_degraded(sid, reason="high latency")
        registry.mark_degraded(sid, reason="packet loss")
        record = registry.get(sid)
        assert "high latency" in record.degradation_reasons
        assert "packet loss" in record.degradation_reasons

    def test_degradation_reason_not_duplicated(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, reason="no device")
        registry.mark_unavailable(sid, reason="no device")
        assert registry.get(sid).degradation_reasons.count("no device") == 1

    def test_degraded_sources_query(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus
        registry = _make_registry()
        sid_mic = registry.register(**_mic_kwargs(source_id="mic-ok"))
        sid_cam = registry.register(**_webcam_kwargs(source_id="cam-deg"))
        registry.mark_active(sid_mic)
        registry.mark_degraded(sid_cam, reason="no camera")
        degraded = registry.degraded_sources()
        assert len(degraded) == 1
        assert degraded[0].source_id == sid_cam

    def test_unavailable_included_in_degraded_sources_query(self):
        registry = _make_registry()
        sid = registry.register(**_external_stream_kwargs())
        registry.mark_unavailable(sid, reason="timeout")
        degraded = registry.degraded_sources()
        assert any(r.source_id == sid for r in degraded)

    def test_unavailable_source_not_in_active_sources(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, reason="missing")
        assert not any(r.source_id == sid for r in registry.active_sources())

    def test_mark_inactive_without_reason_sets_active_false(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.mark_inactive(sid)
        assert registry.get(sid).is_active is False


# ---------------------------------------------------------------------------
# 8. Registry snapshot serialisation
# ---------------------------------------------------------------------------


class TestRegistrySnapshot:
    def test_snapshot_returns_dict(self):
        registry = _make_registry()
        snap = registry.snapshot()
        assert isinstance(snap, dict)

    def test_snapshot_is_json_serialisable(self):
        registry = _make_registry()
        registry.register(**_mic_kwargs())
        registry.register(**_webcam_kwargs())
        snap = registry.snapshot()
        # Must not raise
        json_str = json.dumps(snap)
        assert isinstance(json_str, str)

    def test_snapshot_contains_expected_keys(self):
        registry = _make_registry()
        snap = registry.snapshot()
        for key in (
            "snapshot_at",
            "total_count",
            "active_count",
            "degraded_count",
            "primary_audio_id",
            "primary_video_id",
            "sources",
        ):
            assert key in snap, f"Missing key: {key}"

    def test_snapshot_counts_are_accurate(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus
        registry = _make_registry()
        sid_mic = registry.register(**_mic_kwargs(source_id="mic"))
        sid_cam = registry.register(**_webcam_kwargs(source_id="cam"))
        sid_ext = registry.register(**_external_stream_kwargs(source_id="ext"))

        registry.mark_active(sid_mic)
        registry.mark_degraded(sid_cam, reason="no feed")
        registry.mark_unavailable(sid_ext, reason="offline")

        snap = registry.snapshot()
        assert snap["total_count"] == 3
        assert snap["active_count"] == 1
        assert snap["degraded_count"] == 2

    def test_snapshot_primary_ids_set_correctly(self):
        registry = _make_registry()
        mic_id = registry.register(**_mic_kwargs())
        cam_id = registry.register(**_webcam_kwargs())
        registry.set_primary_audio(mic_id)
        registry.set_primary_video(cam_id)
        snap = registry.snapshot()
        assert snap["primary_audio_id"] == mic_id
        assert snap["primary_video_id"] == cam_id

    def test_snapshot_sources_list_length(self):
        registry = _make_registry()
        for i in range(3):
            registry.register(**_mic_kwargs(source_id=f"mic-{i}"))
        snap = registry.snapshot()
        assert len(snap["sources"]) == 3

    def test_snapshot_source_dict_has_required_fields(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        snap = registry.snapshot()
        source_dict = snap["sources"][0]
        required = {
            "source_id",
            "source_type",
            "modality",
            "display_name",
            "device_id",
            "transport",
            "is_active",
            "is_primary_audio",
            "is_primary_video",
            "priority",
            "health",
            "degradation_reasons",
            "quality_score",
            "latency_ms",
            "registered_at",
            "last_seen_at",
            "extra",
        }
        for field in required:
            assert field in source_dict, f"Missing field in source dict: {field}"

    def test_snapshot_with_quality_and_latency(self):
        registry = _make_registry()
        sid = registry.register(**_webrtc_kwargs())
        registry.mark_active(sid)
        registry.update_quality(sid, quality_score=0.72, latency_ms=35.5)
        snap = registry.snapshot()
        source = snap["sources"][0]
        assert source["quality_score"] == pytest.approx(0.72)
        assert source["latency_ms"] == pytest.approx(35.5)

    def test_empty_registry_snapshot_is_valid(self):
        registry = _make_registry()
        snap = registry.snapshot()
        assert snap["total_count"] == 0
        assert snap["sources"] == []
        json.dumps(snap)  # must be JSON-safe


# ---------------------------------------------------------------------------
# 9. Shell ownership boundary
# ---------------------------------------------------------------------------


class TestShellOwnershipBoundary:
    def test_runtime_has_source_registry_attribute(self):
        """DesktopPresenceRuntime must own the registry (not OpenClawd)."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        assert hasattr(runtime, "source_registry")
        assert hasattr(runtime, "snapshot_source_registry")

    def test_source_registry_is_perception_source_registry_instance(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.multimodal.perception_source_registry import PerceptionSourceRegistry
        runtime = DesktopPresenceRuntime()
        assert isinstance(runtime.source_registry, PerceptionSourceRegistry)

    def test_snapshot_source_registry_returns_dict(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        snap = runtime.snapshot_source_registry()
        assert isinstance(snap, dict)
        assert "sources" in snap

    def test_snapshot_source_registry_is_json_serialisable(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        snap = runtime.snapshot_source_registry()
        # Must not raise
        json.dumps(snap)

    def test_openclawd_does_not_own_source_registry(self):
        """OpenClawd must not have a source_registry attribute."""
        from core.openclawd import OpenClawd
        clawd = OpenClawd()
        assert not hasattr(clawd, "source_registry"), (
            "OpenClawd must not own the perception source registry — "
            "source governance belongs to the runtime shell."
        )

    def test_registry_mutated_on_shell_not_on_core(self):
        """Mutations to the shell registry do not affect OpenClawd state."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.multimodal.perception_source_registry import (
            PerceptionSourceType,
            SourceModality,
        )
        runtime = DesktopPresenceRuntime()
        registry = runtime.source_registry
        sid = registry.register(
            source_type=PerceptionSourceType.MICROPHONE,
            modality=SourceModality.AUDIO,
            display_name="Boundary Test Mic",
        )
        registry.mark_active(sid)
        # The record exists only on the shell registry
        assert registry.get(sid) is not None
        # OpenClawd has no corresponding state — this just checks no exception
        from core.openclawd import get_openclawd
        clawd = get_openclawd()
        assert not hasattr(clawd, "source_registry")

    def test_two_runtime_instances_have_independent_registries(self):
        """Each DesktopPresenceRuntime instance gets its own registry.

        (In production a singleton is used; this tests isolation for correctness.)
        """
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.multimodal.perception_source_registry import (
            PerceptionSourceType,
            SourceModality,
        )
        r1 = DesktopPresenceRuntime()
        r2 = DesktopPresenceRuntime()
        r1.source_registry.register(
            source_type=PerceptionSourceType.MICROPHONE,
            modality=SourceModality.AUDIO,
            source_id="shared-id-test",
        )
        # r2 must not see r1's source
        assert r2.source_registry.get("shared-id-test") is None

    def test_registry_not_exposed_on_openclawd_module(self):
        """The perception_source_registry module must not be imported by openclawd."""
        import core.openclawd as _oc_module
        import sys
        # perception_source_registry should not be an attribute of the module
        assert not hasattr(_oc_module, "PerceptionSourceRegistry"), (
            "PerceptionSourceRegistry must not be imported at the OpenClawd module level."
        )
