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

    with patch.object(DesktopPresenceRuntime, "_try_start_ingest_bus"):
        runtime = DesktopPresenceRuntime()
    runtime._webrtc_session_manager = None

    with patch("core.unified_config.config", {"enable_webrtc_session_manager": True}), patch(
        "core.multimodal.webrtc_session_manager.WebRTCSessionManager",
        return_value=MagicMock(name="webrtc_manager"),
    ) as mock_manager:
        runtime._try_init_webrtc_session_manager()

    assert mock_manager.called
    assert runtime._webrtc_session_manager is not None
