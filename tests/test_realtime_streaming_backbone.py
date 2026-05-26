from __future__ import annotations

from core.realtime_streaming_backbone import (
    REALTIME_STREAMING_BACKBONE_AUTHORITY,
    REALTIME_STREAMING_BACKBONE_SENTINEL,
    build_realtime_stream_runtime_status,
    build_realtime_streaming_backbone_contract,
)
from unittest.mock import MagicMock, patch


def test_backbone_contract_exposes_formal_roles_and_convergence():
    contract = build_realtime_streaming_backbone_contract()
    assert contract["authority"] == REALTIME_STREAMING_BACKBONE_AUTHORITY
    assert contract["sentinel"] == REALTIME_STREAMING_BACKBONE_SENTINEL
    assert "mainline_roles" in contract["formal_roles"]
    assert contract["component_convergence"]["webrtc_session_manager"]["is_mainline_session_manager"] is True
    assert contract["component_convergence"]["vision_sampler"]["is_mainline_stream_authority"] is False


def test_runtime_status_active_when_live_sources_are_present():
    status = build_realtime_stream_runtime_status(
        source_registry_snapshot={"total_count": 2, "active_count": 1, "degraded_count": 0},
        enable_webrtc_session_manager=True,
    )
    assert status["live_stream_session_exists"] is True
    assert status["stream_state"] == "active"


def test_runtime_status_discrete_fallback_without_live_sources():
    status = build_realtime_stream_runtime_status(
        source_registry_snapshot={"total_count": 0, "active_count": 0, "degraded_count": 0},
        enable_webrtc_session_manager=False,
    )
    assert status["live_stream_session_exists"] is False
    assert status["stream_state"] == "discrete_fallback"


def test_runtime_initializes_webrtc_session_manager_when_enabled():
    from core.desktop_presence_runtime import DesktopPresenceRuntime

    runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
    runtime._webrtc_session_manager = None

    with patch("core.unified_config.config", {"enable_webrtc_session_manager": True}), patch(
        "core.multimodal.webrtc_session_manager.WebRTCSessionManager",
        return_value=MagicMock(name="webrtc_manager"),
    ) as mock_manager:
        runtime._try_init_webrtc_session_manager()

    assert mock_manager.called
    assert runtime._webrtc_session_manager is not None


# ---------------------------------------------------------------------------
# Behavioral tests — verify real behavior differences, not field existence
# ---------------------------------------------------------------------------


def test_stream_active_status_produces_routing_signals():
    """stream_active_for_routing and stream_fallback_required must be correct
    for all canonical stream states."""
    active_status = build_realtime_stream_runtime_status(
        source_registry_snapshot={"total_count": 1, "active_count": 1, "degraded_count": 0},
        enable_webrtc_session_manager=True,
    )
    assert active_status["stream_active_for_routing"] is True, (
        "active stream must set stream_active_for_routing=True"
    )
    assert active_status["stream_fallback_required"] is False, (
        "active stream must set stream_fallback_required=False"
    )

    unavailable_status = build_realtime_stream_runtime_status(
        source_registry_snapshot={"total_count": 1, "active_count": 0, "degraded_count": 0},
        enable_webrtc_session_manager=False,
    )
    assert unavailable_status["stream_active_for_routing"] is False, (
        "unavailable stream must set stream_active_for_routing=False"
    )
    assert unavailable_status["stream_fallback_required"] is True, (
        "unavailable stream must set stream_fallback_required=True"
    )


def test_stream_degraded_state_produces_routing_signals():
    """A degraded stream (active but degraded sources) keeps routing active."""
    degraded_status = build_realtime_stream_runtime_status(
        source_registry_snapshot={"total_count": 2, "active_count": 1, "degraded_count": 1},
        enable_webrtc_session_manager=True,
    )
    assert degraded_status["stream_state"] == "degraded"
    assert degraded_status["stream_active_for_routing"] is True, (
        "degraded stream still has live sources: routing should remain active"
    )
    assert degraded_status["stream_fallback_required"] is False, (
        "degraded stream should not force fallback; fallback happens on unavailable/reconnecting/discrete"
    )


def test_reconnecting_state_requires_fallback():
    """Reconnecting stream must force discrete fallback."""
    reconnecting_status = build_realtime_stream_runtime_status(
        source_registry_snapshot={"total_count": 1, "active_count": 0, "degraded_count": 0},
        enable_webrtc_session_manager=True,
    )
    assert reconnecting_status["stream_state"] == "reconnecting"
    assert reconnecting_status["stream_fallback_required"] is True, (
        "reconnecting state must set stream_fallback_required=True"
    )
    assert reconnecting_status["stream_active_for_routing"] is False, (
        "reconnecting state must not show stream as active for routing"
    )


def test_manager_initialization_sets_stream_runtime_ready():
    """stream_runtime_ready must be True when webrtc session manager is initialized,
    and False when it is not — verifying that the signal reflects real manager state."""
    from core.desktop_presence_runtime import DesktopPresenceRuntime

    # No manager — stream_runtime_ready should be False
    runtime_no_mgr = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
    runtime_no_mgr._webrtc_session_manager = None
    assert runtime_no_mgr.stream_runtime_ready is False, (
        "stream_runtime_ready must be False when no manager is initialized"
    )

    # Manager initialized — stream_runtime_ready should be True
    runtime_with_mgr = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
    runtime_with_mgr._webrtc_session_manager = MagicMock(name="webrtc_manager")
    assert runtime_with_mgr.stream_runtime_ready is True, (
        "stream_runtime_ready must be True once a manager has been initialized"
    )


def test_continuous_stream_enters_canonical_perception_when_stream_active():
    """continuous_stream must appear in active_modalities in canonical perception
    when stream_active_for_routing is True — not just when ingress backbone says so."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)

    stream_active_status = {
        "stream_state": "active",
        "stream_active_for_routing": True,
        "stream_fallback_required": False,
    }
    perception = clawd._build_canonical_perception_state(
        runtime_session_id="test-session",
        trace_id="test-trace",
        stream_runtime_status=stream_active_status,
    )
    assert perception is not None
    assert "continuous_stream" in perception.get("active_modalities", []), (
        "continuous_stream must appear in active_modalities when stream_active_for_routing=True"
    )
    assert perception.get("stream_active_for_routing") is True, (
        "stream_active_for_routing flag must be surfaced in canonical perception"
    )

    # With no active stream — continuous_stream must NOT be injected
    stream_fallback_status = {
        "stream_state": "discrete_fallback",
        "stream_active_for_routing": False,
        "stream_fallback_required": True,
    }
    perception_no_stream = clawd._build_canonical_perception_state(
        runtime_session_id="test-session-2",
        trace_id="test-trace-2",
        stream_runtime_status=stream_fallback_status,
    )
    assert perception_no_stream is not None
    assert "continuous_stream" not in perception_no_stream.get("active_modalities", []), (
        "continuous_stream must NOT be in active_modalities when stream is not active for routing"
    )


def test_stream_fallback_required_signal_changes_route_decision():
    """Behavioral test: when stream_fallback_required is True and the ingress
    backbone has continuous_stream present, the route must be forced to text_only.
    When stream is active, the ingress guidance reflects the stream signal."""
    from core.openclawd import OpenClawd

    clawd = OpenClawd.__new__(OpenClawd)
    clawd._router = None  # avoid full OpenClawd __init__

    # Ingress backbone with continuous_stream modality active
    ingress_with_stream = {
        "modalities": {
            "continuous_stream": {"is_present": True},
        },
        "presence_mode_coupling": {},
    }

    # Case 1: stream unavailable -> stream_fallback_required=True -> text_only forced
    stream_unavailable_status = {
        "stream_state": "unavailable",
        "stream_active_for_routing": False,
        "stream_fallback_required": True,
    }
    route_fallback = clawd._select_multimodal_route(
        canonical_perception={
            "requires_native_multimodal": False,
            "active_modalities": ["continuous_stream"],
        },
        stream_runtime_status=stream_unavailable_status,
        desktop_native_ingress_backbone=ingress_with_stream,
    )
    assert route_fallback["route_type"] == "text_only", (
        "route must be text_only when stream is unavailable (stream_fallback_required=True)"
    )
    assert route_fallback.get("stream_fallback_required") is True, (
        "stream_fallback_required signal must appear in the returned route decision"
    )

    # Case 2: stream active -> ingress guidance promotes continuous_stream signal
    # (no forced fallback; route_bias reflects stream awareness).
    stream_active_status = {
        "stream_state": "active",
        "stream_active_for_routing": True,
        "stream_fallback_required": False,
    }
    ingress_guidance = OpenClawd._derive_desktop_native_ingress_route_guidance(
        desktop_native_ingress_backbone=ingress_with_stream,
        stream_runtime_status=stream_active_status,
    )
    # Active stream must not signal fallback and must set continuous_stream signals
    assert ingress_guidance["continuous_stream_present"] is True, (
        "active stream ingress must be detected as present"
    )
    assert ingress_guidance["stream_state"] == "active"
    assert ingress_guidance["route_bias"] == "continuous_stream_aware", (
        "active stream must set continuous_stream_aware route bias"
    )
    assert ingress_guidance["context_strategy_hint"]["continuous_stream_assisted"] is True, (
        "active stream must set continuous_stream_assisted=True in context strategy"
    )
