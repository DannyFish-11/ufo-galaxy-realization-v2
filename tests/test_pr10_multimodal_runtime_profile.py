"""PR-10: multimodal runtime profile classification tests."""

from __future__ import annotations


def test_default_root_config_resolves_safe_default_profile() -> None:
    from core.multimodal_runtime_profile import (
        MultimodalRuntimeProfile,
        resolve_multimodal_runtime_profile,
    )

    snapshot = resolve_multimodal_runtime_profile(
        config={
            "enable_multimodal_ingest": False,
            "enable_webrtc_session_manager": False,
            "debug_desktop_presence_runtime": False,
            "state_event_bus_log_all": False,
        },
        env={},
    )

    assert snapshot.profile == MultimodalRuntimeProfile.SAFE_DEFAULT
    assert snapshot.enable_multimodal_ingest is False
    assert snapshot.enable_webrtc_session_manager is False


def test_enabled_runtime_features_resolve_full_deployment() -> None:
    from core.multimodal_runtime_profile import (
        MultimodalRuntimeProfile,
        resolve_multimodal_runtime_profile,
    )

    snapshot = resolve_multimodal_runtime_profile(
        config={
            "enable_multimodal_ingest": True,
            "enable_webrtc_session_manager": True,
        },
        env={},
    )

    assert snapshot.profile == MultimodalRuntimeProfile.FULL_DEPLOYMENT


def test_debug_flags_resolve_debug_enhanced() -> None:
    from core.multimodal_runtime_profile import (
        MultimodalRuntimeProfile,
        resolve_multimodal_runtime_profile,
    )

    snapshot = resolve_multimodal_runtime_profile(
        config={
            "enable_multimodal_ingest": False,
            "enable_webrtc_session_manager": False,
            "debug_desktop_presence_runtime": True,
            "state_event_bus_log_all": False,
        },
        env={},
    )

    assert snapshot.profile == MultimodalRuntimeProfile.DEBUG_ENHANCED


def test_explicit_profile_override_wins() -> None:
    from core.multimodal_runtime_profile import (
        MultimodalRuntimeProfile,
        resolve_multimodal_runtime_profile,
    )

    snapshot = resolve_multimodal_runtime_profile(
        config={
            "enable_multimodal_ingest": False,
            "enable_webrtc_session_manager": False,
        },
        env={"GALAXY_MULTIMODAL_RUNTIME_PROFILE": "full_deployment"},
    )

    assert snapshot.profile == MultimodalRuntimeProfile.FULL_DEPLOYMENT
    assert snapshot.explicit_profile_override == "full_deployment"


def test_production_baseline_summary_embeds_runtime_profile() -> None:
    from core.production_baseline import build_production_baseline_summary

    summary = build_production_baseline_summary()
    assert "multimodal_runtime_profile" in summary
    assert "profile" in summary["multimodal_runtime_profile"]
