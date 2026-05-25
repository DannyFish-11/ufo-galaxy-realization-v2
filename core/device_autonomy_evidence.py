"""Evidence-based Android autonomy classification."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.android_device_state_store import (
    get_device_state_snapshot,
    list_device_state_snapshots,
    list_recent_execution_events,
)
from core.android_network_participation import get_participation_state_for_device
from core.android_runtime_host import build_android_runtime_host_identity
from core.canonical_cross_repo_evidence_pipeline import (
    PipelineVerdict,
    build_canonical_cross_repo_evidence_report,
)
from core.canonical_task import get_canonical_task_runtime
from core.delegated_runtime_execution_tracker import build_execution_tracking_snapshot
from core.device_operational_support import get_device_operational_support

DEVICE_AUTONOMY_EVIDENCE_AUTHORITY: str = (
    "DEVICE_AUTONOMY_EVIDENCE_AUTHORITY::"
    "core.device_autonomy_evidence classifies stronger autonomy only from "
    "cross-repo runtime evidence plus accepted execution, result return, and "
    "canonical closure continuity."
)

AUTONOMY_POSTURE_ALONE_NEVER_PROMOTES_POLICY: str = (
    "POLICY::AUTONOMY_POSTURE_ALONE_NEVER_PROMOTES: "
    "Registration posture, runtime flags, or participation hints alone are not "
    "sufficient for strong autonomy classes. Cross-repo evidence and actual "
    "execution closure are required."
)

AUTONOMY_STRONG_CLASSES_REQUIRE_CROSS_REPO_EVIDENCE_POLICY: str = (
    "POLICY::AUTONOMY_STRONG_CLASSES_REQUIRE_CROSS_REPO_EVIDENCE: "
    "Meaningful and semi-autonomous runtime classes require a complete "
    "cross-repo evidence report plus fresh execution/result/closure evidence."
)

_AUTONOMY_STALE_SECONDS: float = 900.0


def _safe_timestamp(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _build_allocation_evidence(device_id: str) -> Dict[str, Any]:
    records = [
        record.to_dict()
        for record in get_canonical_task_runtime().list_allocation_records(limit=2048)
        if str(
            record.selected_executor or record.execution_location or ""
        ).strip()
        == device_id
    ]
    accepted = [
        record for record in records if str(record.get("accepted_allocation") or "") == "accepted"
    ]
    closed = [record for record in records if bool(record.get("canonical_closed"))]
    latest_closed_at = max(
        [
            _safe_timestamp(record.get("closed_at"))
            or _safe_timestamp(record.get("updated_at"))
            or _safe_timestamp(record.get("accepted_at"))
            for record in closed
        ]
        or [0.0]
    )
    earliest_accepted_at = min(
        [
            _safe_timestamp(record.get("accepted_at"))
            or _safe_timestamp(record.get("updated_at"))
            for record in accepted
            if (
                _safe_timestamp(record.get("accepted_at"))
                or _safe_timestamp(record.get("updated_at"))
            )
            > 0.0
        ]
        or [0.0]
    )
    return {
        "accepted_tasks": len(accepted),
        "closed_tasks": len(closed),
        "fallback_count": len([record for record in records if bool(record.get("fallback_used"))]),
        "latest_closed_at": latest_closed_at or None,
        "continuity_span_seconds": max(0.0, latest_closed_at - earliest_accepted_at)
        if latest_closed_at and earliest_accepted_at
        else 0.0,
    }


def _build_tracker_evidence(device_id: str) -> Dict[str, Any]:
    snapshot = build_execution_tracking_snapshot()
    records = [record for record in snapshot.records if record.identity.device_id == device_id]
    latest_updated_at = max([_safe_timestamp(record.updated_at) for record in records] or [0.0])
    return {
        "tracking_records": len(records),
        "completed_results": len([record for record in records if record.phase.value == "completed"]),
        "failed_results": len([record for record in records if record.phase.value == "failed"]),
        "recovered_unrevalidated": len(
            [record for record in records if record.recovery_status == "recovered_unrevalidated"]
        ),
        "recovered_stale": len(
            [record for record in records if record.recovery_status == "recovered_stale"]
        ),
        "latest_updated_at": latest_updated_at or None,
        "runtime_snapshot": {
            "recovered_unrevalidated_count": snapshot.recovered_unrevalidated_count,
            "recovered_stale_count": snapshot.recovered_stale_count,
            "durable_state_path": snapshot.durable_state_path,
        },
    }


def _build_event_evidence(device_id: str) -> Dict[str, Any]:
    events = list_recent_execution_events(device_id=device_id, limit=500)
    latest_event_at = max(
        [_safe_timestamp(event.event_ts) or _safe_timestamp(event.absorbed_at) for event in events]
        or [0.0]
    )
    return {
        "event_count": len(events),
        "completed_events": len([event for event in events if event.phase == "completed"]),
        "terminal_events": len(
            [event for event in events if event.phase in {"completed", "failed", "stagnation", "gate_decision"}]
        ),
        "latest_event_at": latest_event_at or None,
    }


def classify_device_autonomy(device_id: str) -> Dict[str, Any]:
    now = time.time()
    snapshot = get_device_state_snapshot(device_id)
    participation = get_participation_state_for_device(device_id)
    support = get_device_operational_support(device_id=device_id).to_dict()
    try:
        from core.unified.device_manager import get_unified_device_manager

        device_record = get_unified_device_manager().get_device(device_id)
    except Exception:
        device_record = None
    host_identity = build_android_runtime_host_identity(device_record or {"device_id": device_id})
    cross_repo_report = build_canonical_cross_repo_evidence_report()
    allocation = _build_allocation_evidence(device_id)
    tracker = _build_tracker_evidence(device_id)
    events = _build_event_evidence(device_id)

    latest_evidence_at = max(
        [
            _safe_timestamp(allocation.get("latest_closed_at")),
            _safe_timestamp(tracker.get("latest_updated_at")),
            _safe_timestamp(events.get("latest_event_at")),
        ]
        or [0.0]
    )
    evidence_stale = bool(latest_evidence_at and (now - latest_evidence_at) > _AUTONOMY_STALE_SECONDS)
    cross_repo_complete = cross_repo_report.pipeline_verdict == PipelineVerdict.complete
    stable_runtime_host_posture = (
        host_identity.source_runtime_posture == "join_runtime"
        and host_identity.role.value == "full_runtime_host"
    )
    readiness_satisfied = bool(getattr(participation, "readiness_satisfied", False))
    dispatch_gate_passed = bool(getattr(participation, "dispatch_gate_passed", False))
    accepted_execution = allocation["accepted_tasks"] >= 1
    actual_local_execution = events["event_count"] >= 1 or tracker["tracking_records"] >= 1
    result_returned = (
        events["terminal_events"] >= 1
        or tracker["completed_results"] >= 1
        or allocation["closed_tasks"] >= 1
    )
    closure_integrated = allocation["closed_tasks"] >= 1
    repeated_continuity = allocation["closed_tasks"] >= 3 and allocation["accepted_tasks"] >= 3
    evidence_inconsistent = (
        tracker["recovered_unrevalidated"] > 0
        or tracker["recovered_stale"] > 0
        or allocation["fallback_count"] > allocation["closed_tasks"]
    )

    demotion_reasons: List[str] = []
    if not support["dispatch_target_capable"]:
        demotion_reasons.append("device_type_not_operationally_supported")
    if not cross_repo_complete:
        demotion_reasons.append(
            f"cross_repo_evidence_{cross_repo_report.pipeline_verdict.value}"
        )
    if not stable_runtime_host_posture:
        demotion_reasons.append("runtime_host_posture_not_stably_join_runtime")
    if not readiness_satisfied:
        demotion_reasons.append("readiness_not_satisfied")
    if not dispatch_gate_passed:
        demotion_reasons.append("dispatch_gate_not_passed")
    if evidence_stale:
        demotion_reasons.append("execution_evidence_stale")
    if evidence_inconsistent:
        demotion_reasons.append("execution_evidence_inconsistent_or_unrevalidated")

    if (
        support["dispatch_target_capable"]
        and cross_repo_complete
        and stable_runtime_host_posture
        and readiness_satisfied
        and dispatch_gate_passed
        and accepted_execution
        and actual_local_execution
        and result_returned
        and closure_integrated
        and repeated_continuity
        and not evidence_stale
        and not evidence_inconsistent
    ):
        autonomy_class = "meaningfully_autonomous_runtime_capable"
    elif (
        support["dispatch_target_capable"]
        and cross_repo_complete
        and stable_runtime_host_posture
        and readiness_satisfied
        and dispatch_gate_passed
        and accepted_execution
        and actual_local_execution
        and result_returned
        and closure_integrated
        and not evidence_stale
        and not evidence_inconsistent
    ):
        autonomy_class = "semi_autonomous_runtime_capable"
    elif (
        getattr(participation, "active_session_count", 0) > 0
        or accepted_execution
        or actual_local_execution
    ):
        autonomy_class = "participant_capable"
    elif getattr(participation, "websocket_connected", False):
        autonomy_class = "observable_only"
    else:
        autonomy_class = "connected_only"

    return {
        "device_id": device_id,
        "autonomy_class": autonomy_class,
        "cross_repo_pipeline_verdict": cross_repo_report.pipeline_verdict.value,
        "cross_repo_report_complete": cross_repo_report.is_complete,
        "stable_runtime_host_posture": stable_runtime_host_posture,
        "evidence": {
            "support": support,
            "participation_tier": getattr(getattr(participation, "tier", None), "value", "local_only"),
            "websocket_connected": bool(getattr(participation, "websocket_connected", False)),
            "active_session_count": int(getattr(participation, "active_session_count", 0) or 0),
            "readiness_satisfied": readiness_satisfied,
            "dispatch_gate_passed": dispatch_gate_passed,
            "snapshot_present": snapshot is not None,
            "allocation": allocation,
            "tracker": tracker,
            "events": events,
            "accepted_execution": accepted_execution,
            "actual_local_execution": actual_local_execution,
            "result_returned": result_returned,
            "closure_integrated": closure_integrated,
            "repeated_continuity": repeated_continuity,
            "latest_evidence_at": latest_evidence_at or None,
            "evidence_stale": evidence_stale,
            "evidence_inconsistent": evidence_inconsistent,
            "demotion_reasons": demotion_reasons,
        },
        "authority": DEVICE_AUTONOMY_EVIDENCE_AUTHORITY,
    }


def build_device_autonomy_report(device_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    known_ids = set(device_ids or [])
    if not known_ids:
        known_ids.update(snapshot.device_id for snapshot in list_device_state_snapshots() if snapshot.device_id)
    if not known_ids:
        try:
            from core.unified.device_manager import get_unified_device_manager

            known_ids.update(device.device_id for device in get_unified_device_manager().list_devices())
        except Exception:
            pass
    classes = [classify_device_autonomy(device_id) for device_id in sorted(known_ids)]
    return {
        "authority": DEVICE_AUTONOMY_EVIDENCE_AUTHORITY,
        "policy": [
            AUTONOMY_POSTURE_ALONE_NEVER_PROMOTES_POLICY,
            AUTONOMY_STRONG_CLASSES_REQUIRE_CROSS_REPO_EVIDENCE_POLICY,
        ],
        "autonomy_classification": classes,
    }

