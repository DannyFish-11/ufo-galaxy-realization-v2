"""Formal Real-Time Streaming Backbone contract for desktop runtime mainline."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

REALTIME_STREAMING_BACKBONE_AUTHORITY = (
    "REALTIME_STREAMING_BACKBONE::DESKTOP_PRESENCE_MULTIMODAL_MAINLINE_AUTHORITY_V1"
)
REALTIME_STREAMING_BACKBONE_SENTINEL = "REALTIME_STREAMING_BACKBONE::FORMAL_CONVERGENCE_PASS_V1"


def build_realtime_streaming_backbone_contract() -> Dict[str, Any]:
    """Return formal roles, boundaries, and converged component relationships."""
    return {
        "authority": REALTIME_STREAMING_BACKBONE_AUTHORITY,
        "sentinel": REALTIME_STREAMING_BACKBONE_SENTINEL,
        "contract_version": 1,
        "formal_roles": {
            "mainline_roles": [
                "desktop_continuous_sensing_substrate",
                "multimodal_continuous_live_stream_ingress_branch",
                "cross_device_and_remote_presence_stream_substrate",
                "manifest_action_feedback_and_result_confirmation_stream",
            ],
            "auxiliary_roles": [
                "operator_observation_and_monitoring_view",
                "session_level_live_interaction_support",
            ],
            "derived_roles": [
                "vision_sampler_frame_pull_bridge",
                "snapshot_fallback_from_continuous_stream",
            ],
        },
        "desktop_presence_mapping": {
            "static": {
                "low_intensity_continuous_stream_sensing_allowed": True,
                "stream_role": "ambient_background_sensing",
                "stream_presentation_role": "minimal_presence_presentation",
            },
            "liminal": {
                "stream_role": "ambient_board_threshold_and_transition_signals",
                "supports_presence_transitions": True,
                "stream_presentation_role": "liminal_gradient_and_readiness_feedback",
            },
            "manifest": {
                "stream_role": "action_observation_feedback_and_result_confirmation",
                "supports_execution_observation": True,
                "stream_presentation_role": "operator_visible_execution_trace",
            },
        },
        "multimodal_ingress_mapping": {
            "unified_backbone": "desktop_native_multimodal_ingress",
            "discrete_ingress_branch": ["text", "image", "file", "screen_context", "foreground_context"],
            "continuous_live_stream_ingress_branch": [
                "webrtc_video_stream",
                "remote_device_stream",
                "runtime_host_continuous_perception_stream",
            ],
            "integration_rule": "continuous_stream_must_enter_session_context_task_planning_backbone",
        },
        "component_convergence": {
            "gateway_proxy": {
                "module": "galaxy_gateway.webrtc_proxy",
                "role": "mainline_signaling_and_forwarding_gateway",
            },
            "node95_bridge": {
                "authority": "NODE_95_URL",
                "role": "strongly_coupled_external_stream_receiver_bridge",
                "position": "formal_backend_bridge_component",
            },
            "vision_sampler": {
                "module": "core.services.vision_sampler",
                "role": "derived_snapshot_bridge_from_continuous_stream",
                "is_mainline_stream_authority": False,
            },
            "webrtc_session_manager": {
                "module": "core.multimodal.WebRTCSessionManager",
                "role": "core_stream_session_lifecycle_manager",
                "is_mainline_session_manager": True,
            },
            "runtime_shell": {
                "module": "core.desktop_presence_runtime",
                "role": "stream_state_governance_source_of_truth",
                "governs_presence_and_multimodal_coupling": True,
            },
            "android_cross_device_streams": {
                "role": "aligned_with_desktop_stream_backbone",
                "alignment_rule": "same_session_presence_and_ingress_governance",
            },
        },
        "switch_and_degradation_policy": {
            "mainline_capability": "realtime_streaming_backbone",
            "switches": {
                "enable_webrtc_session_manager": "mainline_stream_session_switch",
                "enable_multimodal_ingest": "continuous_sensing_substrate_switch",
            },
            "degradation_states": ["active", "degraded", "reconnecting", "unavailable", "discrete_fallback"],
            "discrete_fallback_rule": "absence_of_live_stream_requires_discrete_sensing_fallback",
            "source_of_truth_authority": "DesktopPresenceRuntime.source_registry_and_session_state",
        },
    }


def build_realtime_stream_runtime_status(
    *,
    source_registry_snapshot: Optional[Mapping[str, Any]] = None,
    enable_webrtc_session_manager: bool = False,
) -> Dict[str, Any]:
    """Return runtime-governed stream status and degradation semantics."""
    snap = dict(source_registry_snapshot or {})
    total_count = int(snap.get("total_count") or 0)
    active_count = int(snap.get("active_count") or 0)
    degraded_count = int(snap.get("degraded_count") or 0)
    has_live_session = active_count > 0

    if has_live_session and degraded_count <= 0:
        stream_state = "active"
    elif has_live_session and degraded_count > 0:
        stream_state = "degraded"
    elif enable_webrtc_session_manager and total_count > 0:
        stream_state = "reconnecting"
    elif total_count > 0:
        stream_state = "unavailable"
    else:
        stream_state = "discrete_fallback"

    return {
        "live_stream_session_exists": has_live_session,
        "stream_provider_total": total_count,
        "stream_provider_active": active_count,
        "stream_provider_degraded": degraded_count,
        "stream_state": stream_state,
        "stream_usage_governance": {
            "presence": True,
            "perception": True,
            "operator_view": True,
            "device_bridge": True,
            "action_verification": True,
        },
        "degradation_policy": {
            "on_stream_failure": "degrade_to_discrete_sensing_and_mark_presence_stream_state",
            "on_recovery": "reenter_presence_and_multimodal_stream_branch_with_revalidated_state",
        },
    }
