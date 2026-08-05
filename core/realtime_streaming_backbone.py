"""Formal Real-Time Streaming Backbone contract for desktop runtime mainline."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

REALTIME_STREAMING_BACKBONE_AUTHORITY = "REALTIME_STREAMING_BACKBONE::DESKTOP_PRESENCE_MULTIMODAL_MAINLINE_AUTHORITY_V1"
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


def collect_realtime_stream_evidence() -> Dict[str, Any]:
    """采集**本进程可证实**的实时流证据（不是声明，是实测）。

    此前本模块的状态只由 source registry 的 mic/cam 计数推导，而真正在流的
    SSE token 流它一路都看不见 —— 于是"真的有一路在流"时状态仍报
    ``discrete_fallback``。这里补上真实证据源。

    实事求是三条铁律：
    1. **只报本进程能证实的**。网关与 core 可能分进程，跨进程的流本进程看不到，
       就明确标 ``cross_process_visibility=False``，绝不把"本进程没有"当成"系统没有"。
    2. **取不到就如实记 unobservable**，而不是当成 0。
    3. 证据只做**叠加**，不覆盖既有 registry 语义（见 build_realtime_stream_runtime_status）。
    """
    evidence: Dict[str, Any] = {
        "scope": "process_local",
        "cross_process_visibility": False,
        "observed": {},
        "unobservable": [],
    }
    try:
        from core.llm_stream import stream_registry_snapshot

        evidence["observed"]["token_streams"] = stream_registry_snapshot()
    except Exception as exc:  # noqa: BLE001
        evidence["unobservable"].append({"source": "token_streams", "reason": str(exc)})
    return evidence


def build_realtime_stream_runtime_status(
    *,
    source_registry_snapshot: Optional[Mapping[str, Any]] = None,
    enable_webrtc_session_manager: bool = False,
    stream_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return runtime-governed stream status and degradation semantics.

    ``stream_evidence``（可选，形如 :func:`collect_realtime_stream_evidence` 的返回值）
    是**叠加**的实测证据：既有 registry 推导的 ``stream_state`` 逐字节不变，
    额外暴露 ``observed_live_streaming`` / ``stream_observability`` 两轴，
    让"本进程确实有 N 路在流"这件事可见，同时明示可观测边界。
    """
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

    # Derived downstream routing signals — consumed by route decision and
    # canonical perception assembly to drive real behaviour differences.
    stream_active_for_routing = stream_state in {"active", "degraded"}
    stream_fallback_required = stream_state in {
        "reconnecting",
        "unavailable",
        "discrete_fallback",
    }
    stream_context_available = stream_state == "active"

    # ── 实测证据轴（叠加，不改上面 registry 推导出的 stream_state 语义）──────
    _ev = dict(stream_evidence or {})
    _observed = dict(_ev.get("observed") or {})
    _tok = dict(_observed.get("token_streams") or {})
    _tok_active = int(_tok.get("active") or 0)
    _has_evidence = bool(_ev)
    _observability = {
        # 没给证据就如实说"没测"，而不是默认成"没有流"。
        "evidence_collected": _has_evidence,
        "scope": _ev.get("scope", "unknown"),
        "cross_process_visibility": bool(_ev.get("cross_process_visibility", False)),
        "unobservable": list(_ev.get("unobservable") or []),
        "token_streams_active": _tok_active,
    }

    return {
        "live_stream_session_exists": has_live_session,
        # 本进程实测到的活跃流（token 流）。为 True 即"确实有流在跑"；为 False
        # 只代表**本进程没观测到**，不代表全系统没有 —— 判读须结合 scope。
        "observed_live_streaming": _tok_active > 0,
        "stream_observability": _observability,
        "stream_provider_total": total_count,
        "stream_provider_active": active_count,
        "stream_provider_degraded": degraded_count,
        "stream_state": stream_state,
        # Stream-driven downstream signals: read by real control points in
        # openclawd._build_canonical_perception_state and
        # openclawd._select_multimodal_route (not metadata-only).
        "stream_active_for_routing": stream_active_for_routing,
        "stream_fallback_required": stream_fallback_required,
        "stream_context_available": stream_context_available,
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
