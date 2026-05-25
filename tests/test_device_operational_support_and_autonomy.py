from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.canonical_cross_repo_evidence_pipeline import PipelineVerdict
from core.device_autonomy_evidence import classify_device_autonomy
from core.device_operational_support import (
    OperationalSupportTier,
    classify_device_operational_support,
)
from core.unified_dispatch_readiness_gate import (
    DispatchReadinessStatus,
    evaluate_dispatch_readiness,
)


def test_operational_support_demotes_declared_non_peer_device_types():
    android = classify_device_operational_support("android")
    drone = classify_device_operational_support("drone")

    assert android.support_tier == OperationalSupportTier.near_peer_operational
    assert android.dispatch_target_capable is True
    assert drone.support_tier == OperationalSupportTier.declared_non_operational
    assert drone.dispatch_target_capable is False


def test_dispatch_readiness_blocks_unsupported_operational_device_type():
    with (
        patch(
            "core.unified_dispatch_readiness_gate._check_registration_gaps",
            return_value=[],
        ),
        patch(
            "core.unified_dispatch_readiness_gate._check_udm_registration",
            return_value={"registered": True, "online": True, "device_type": "drone"},
        ),
        patch(
            "core.unified_dispatch_readiness_gate._check_device_operational_support",
            return_value={
                "device_type": "drone",
                "support_tier": "declared_non_operational",
                "dispatch_target_capable": False,
                "reason": "Drone is declared but not an operational near-peer.",
            },
        ),
    ):
        result = evaluate_dispatch_readiness("drone-01")

    assert result.status == DispatchReadinessStatus.BLOCKED_OPERATIONAL_SUPPORT.value
    assert result.dispatch_ready is False
    assert result.operational_support_status == "declared_non_operational"


def test_autonomy_requires_complete_cross_repo_runtime_evidence_for_strong_class():
    complete_report = SimpleNamespace(
        pipeline_verdict=PipelineVerdict.complete,
        is_complete=True,
    )
    participation = SimpleNamespace(
        tier=SimpleNamespace(value="dispatch_eligible"),
        readiness_satisfied=True,
        dispatch_gate_passed=True,
        active_session_count=1,
        websocket_connected=True,
    )
    host_identity = SimpleNamespace(
        source_runtime_posture="join_runtime",
        role=SimpleNamespace(value="full_runtime_host"),
    )
    support_verdict = SimpleNamespace(
        to_dict=lambda: classify_device_operational_support("android").to_dict()
    )

    with (
        patch(
            "core.device_autonomy_evidence.build_canonical_cross_repo_evidence_report",
            return_value=complete_report,
        ),
        patch(
            "core.device_autonomy_evidence.get_participation_state_for_device",
            return_value=participation,
        ),
        patch(
            "core.device_autonomy_evidence.build_android_runtime_host_identity",
            return_value=host_identity,
        ),
        patch(
            "core.device_autonomy_evidence.get_device_operational_support",
            return_value=support_verdict,
        ),
        patch(
            "core.device_autonomy_evidence.get_device_state_snapshot",
            return_value=object(),
        ),
        patch(
            "core.device_autonomy_evidence._build_allocation_evidence",
            return_value={
                "accepted_tasks": 3,
                "closed_tasks": 3,
                "fallback_count": 0,
                "latest_closed_at": 1000.0,
                "continuity_span_seconds": 30.0,
            },
        ),
        patch(
            "core.device_autonomy_evidence._build_tracker_evidence",
            return_value={
                "tracking_records": 3,
                "completed_results": 3,
                "failed_results": 0,
                "recovered_unrevalidated": 0,
                "recovered_stale": 0,
                "latest_updated_at": 1000.0,
                "runtime_snapshot": {},
            },
        ),
        patch(
            "core.device_autonomy_evidence._build_event_evidence",
            return_value={
                "event_count": 3,
                "completed_events": 3,
                "terminal_events": 3,
                "latest_event_at": 1000.0,
            },
        ),
        patch("core.device_autonomy_evidence.time.time", return_value=1005.0),
    ):
        verdict = classify_device_autonomy("android-01")

    assert verdict["autonomy_class"] == "meaningfully_autonomous_runtime_capable"
    assert verdict["cross_repo_pipeline_verdict"] == "complete"


def test_autonomy_demotes_when_cross_repo_evidence_is_not_complete():
    partial_report = SimpleNamespace(
        pipeline_verdict=PipelineVerdict.partial,
        is_complete=False,
    )
    participation = SimpleNamespace(
        tier=SimpleNamespace(value="dispatch_eligible"),
        readiness_satisfied=True,
        dispatch_gate_passed=True,
        active_session_count=1,
        websocket_connected=True,
    )
    host_identity = SimpleNamespace(
        source_runtime_posture="join_runtime",
        role=SimpleNamespace(value="full_runtime_host"),
    )
    support_verdict = SimpleNamespace(
        to_dict=lambda: classify_device_operational_support("android").to_dict()
    )

    with (
        patch(
            "core.device_autonomy_evidence.build_canonical_cross_repo_evidence_report",
            return_value=partial_report,
        ),
        patch(
            "core.device_autonomy_evidence.get_participation_state_for_device",
            return_value=participation,
        ),
        patch(
            "core.device_autonomy_evidence.build_android_runtime_host_identity",
            return_value=host_identity,
        ),
        patch(
            "core.device_autonomy_evidence.get_device_operational_support",
            return_value=support_verdict,
        ),
        patch(
            "core.device_autonomy_evidence.get_device_state_snapshot",
            return_value=object(),
        ),
        patch(
            "core.device_autonomy_evidence._build_allocation_evidence",
            return_value={
                "accepted_tasks": 3,
                "closed_tasks": 3,
                "fallback_count": 0,
                "latest_closed_at": 1000.0,
                "continuity_span_seconds": 30.0,
            },
        ),
        patch(
            "core.device_autonomy_evidence._build_tracker_evidence",
            return_value={
                "tracking_records": 3,
                "completed_results": 3,
                "failed_results": 0,
                "recovered_unrevalidated": 0,
                "recovered_stale": 0,
                "latest_updated_at": 1000.0,
                "runtime_snapshot": {},
            },
        ),
        patch(
            "core.device_autonomy_evidence._build_event_evidence",
            return_value={
                "event_count": 3,
                "completed_events": 3,
                "terminal_events": 3,
                "latest_event_at": 1000.0,
            },
        ),
        patch("core.device_autonomy_evidence.time.time", return_value=1005.0),
    ):
        verdict = classify_device_autonomy("android-01")

    assert verdict["autonomy_class"] == "participant_capable"
    assert "cross_repo_evidence_partial" in verdict["evidence"]["demotion_reasons"]
