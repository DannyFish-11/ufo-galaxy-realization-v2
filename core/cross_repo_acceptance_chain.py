"""跨仓 Android→V2 端到端验收链快照构建器。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

CROSS_REPO_ACCEPTANCE_CHAIN_AUTHORITY = (
    "CROSS_REPO_ACCEPTANCE_CHAIN_AUTHORITY::"
    "core.cross_repo_acceptance_chain.build_cross_repo_acceptance_chain "
    "是 Android(ufo-galaxy-android) → V2(ufo-galaxy-realization-v2) "
    "代表性验收链阶段化诊断快照的规范构建入口。"
)

ANDROID_REPO_COORDINATION_ASSUMPTIONS = (
    "device_register",
    "device_state_snapshot",
    "device_execution_event",
    "mesh_join",
    "mesh_result",
    "mesh_leave",
    "device_acceptance_report",
)

_READY_LIFECYCLE_STAGES = {"ready", "participating", "takeover_eligible"}
_REGISTERED_LIFECYCLE_STAGES = _READY_LIFECYCLE_STAGES | {"registered", "connected"}


def build_cross_repo_acceptance_chain(
    *,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    truth_payload: Optional[Dict[str, Any]] = None,
    board_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建一个具备阶段边界的跨仓端到端验收链快照。"""
    truth_payload = dict(truth_payload or {})
    board_payload = dict(board_payload or {})
    resolved_device_id = _resolve_device_id(
        explicit_device_id=device_id,
        truth_payload=truth_payload,
        board_payload=board_payload,
    )
    resolved_session = _resolve_mesh_session(
        device_id=resolved_device_id,
        explicit_session_id=session_id,
    )
    resolved_session_id = resolved_session.get("session_id")

    stages = [
        _build_android_entry_stage(resolved_device_id, resolved_session_id),
        _build_registration_stage(resolved_device_id),
        _build_participation_stage(resolved_device_id),
        _build_mesh_stage(resolved_device_id, resolved_session),
        _build_result_backflow_stage(resolved_device_id),
        _build_surface_visibility_stage(
            device_id=resolved_device_id,
            session_id=resolved_session_id,
            truth_payload=truth_payload,
            board_payload=board_payload,
        ),
    ]

    failed_stages = [stage for stage in stages if stage["status"] == "failed"]
    overall_status = "passed" if not failed_stages else "failed"
    current_stage = failed_stages[0]["stage"] if failed_stages else stages[-1]["stage"]

    return {
        "chain_id": f"cross_repo_acceptance_{uuid.uuid4().hex[:12]}",
        "authority": CROSS_REPO_ACCEPTANCE_CHAIN_AUTHORITY,
        "device_id": resolved_device_id,
        "session_id": resolved_session_id,
        "overall_status": overall_status,
        "regression_ready": overall_status == "passed",
        "current_stage": current_stage,
        "stage_count": len(stages),
        "passed_stage_count": sum(1 for stage in stages if stage["status"] == "passed"),
        "failing_stage": failed_stages[0]["stage"] if failed_stages else None,
        "failure_boundaries": [
            {
                "stage": stage["stage"],
                "boundary": stage["failure_boundary"],
                "summary": stage["summary"],
            }
            for stage in failed_stages
        ],
        "summary": _build_chain_summary(
            overall_status=overall_status,
            device_id=resolved_device_id,
            session_id=resolved_session_id,
            stages=stages,
        ),
        "android_repo_coordination_assumptions": list(ANDROID_REPO_COORDINATION_ASSUMPTIONS),
        "stages": stages,
        "_source": "core.cross_repo_acceptance_chain.build_cross_repo_acceptance_chain",
        "_timestamp": time.time(),
    }


def _build_android_entry_stage(
    device_id: Optional[str],
    session_id: Optional[str],
) -> Dict[str, Any]:
    passed = bool(device_id)
    summary = (
        f"已解析 Android 参与入口 device_id={device_id} session_id={session_id}"
        if passed
        else "未解析到 Android 参与入口设备，链路尚未进入可归因状态"
    )
    return _stage(
        "android_entry",
        passed=passed,
        failure_boundary="android_ingress",
        summary=summary,
        details={
            "device_id": device_id,
            "session_id": session_id,
            "accepted_message_types": list(ANDROID_REPO_COORDINATION_ASSUMPTIONS),
        },
    )


def _build_registration_stage(device_id: Optional[str]) -> Dict[str, Any]:
    lifecycle_stage = "unregistered"
    gaps: List[str] = []
    if device_id:
        try:
            from core.device_lifecycle_state import get_lifecycle_record

            lifecycle_record = get_lifecycle_record(str(device_id))
            lifecycle_stage = getattr(getattr(lifecycle_record, "stage", None), "value", "unregistered")
        except Exception:
            lifecycle_stage = "unregistered"
        try:
            from galaxy_gateway.android.handlers.registration import get_registration_gaps

            gaps = list(get_registration_gaps(str(device_id)) or [])
        except Exception:
            gaps = []

    passed = bool(device_id) and lifecycle_stage in _REGISTERED_LIFECYCLE_STAGES
    summary = (
        f"registration 可见：lifecycle_stage={lifecycle_stage} registration_gaps={gaps}"
        if passed
        else f"registration 未闭合：lifecycle_stage={lifecycle_stage} registration_gaps={gaps}"
    )
    return _stage(
        "registration",
        passed=passed,
        failure_boundary="registration",
        summary=summary,
        details={
            "device_id": device_id,
            "lifecycle_stage": lifecycle_stage,
            "registration_gaps": gaps,
            "registration_visible": lifecycle_stage in _REGISTERED_LIFECYCLE_STAGES,
        },
    )


def _build_participation_stage(device_id: Optional[str]) -> Dict[str, Any]:
    lifecycle_stage = "unregistered"
    if device_id:
        try:
            from core.device_lifecycle_state import get_lifecycle_record

            lifecycle_record = get_lifecycle_record(str(device_id))
            lifecycle_stage = getattr(getattr(lifecycle_record, "stage", None), "value", "unregistered")
        except Exception:
            lifecycle_stage = "unregistered"
    passed = bool(device_id) and lifecycle_stage in _READY_LIFECYCLE_STAGES
    summary = (
        f"参与/可派发阶段已推进到 {lifecycle_stage}"
        if passed
        else f"参与/可派发阶段未达 ready：当前 lifecycle_stage={lifecycle_stage}"
    )
    return _stage(
        "participation_dispatchability",
        passed=passed,
        failure_boundary="participation_dispatchability",
        summary=summary,
        details={
            "device_id": device_id,
            "lifecycle_stage": lifecycle_stage,
            "dispatchable_lifecycle_stages": sorted(_READY_LIFECYCLE_STAGES),
        },
    )


def _build_mesh_stage(
    device_id: Optional[str],
    session_record: Dict[str, Any],
) -> Dict[str, Any]:
    result_count = int(session_record.get("result_count") or 0)
    join_present = bool(session_record.get("join_event"))
    leave_present = bool(session_record.get("leave_event"))
    session_id = session_record.get("session_id")
    passed = bool(device_id) and bool(session_id) and join_present and result_count > 0 and leave_present
    missing_segments = [
        name
        for name, ok in (
            ("mesh_join", join_present),
            ("mesh_result", result_count > 0),
            ("mesh_leave", leave_present),
        )
        if not ok
    ]
    summary = (
        f"mesh 生命周期闭合：session_id={session_id} result_count={result_count}"
        if passed
        else f"mesh 生命周期缺口：session_id={session_id} missing={missing_segments}"
    )
    return _stage(
        "mesh_lifecycle",
        passed=passed,
        failure_boundary="mesh_lifecycle",
        summary=summary,
        details={
            "device_id": device_id,
            "session_id": session_id,
            "mesh_status": session_record.get("status"),
            "result_count": result_count,
            "missing_segments": missing_segments,
        },
    )


def _build_result_backflow_stage(device_id: Optional[str]) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {}
    if device_id:
        try:
            from core.android_acceptance_evidence_store import (
                get_latest_device_acceptance_evidence_dict,
            )

            evidence = dict(get_latest_device_acceptance_evidence_dict(str(device_id)) or {})
        except Exception:
            evidence = {}
    passed = bool(device_id) and bool(
        evidence.get("acceptance_tag")
        or evidence.get("mapped_android_proof_class")
        or evidence.get("message_id")
    )
    summary = (
        "结果回流已落入 acceptance 证据面"
        if passed
        else "结果回流未形成 acceptance 证据，需检查 Android 上报与 V2 摄取边界"
    )
    return _stage(
        "result_backflow",
        passed=passed,
        failure_boundary="result_backflow",
        summary=summary,
        details={
            "device_id": device_id,
            "acceptance_tag": evidence.get("acceptance_tag"),
            "mapped_android_proof_class": evidence.get("mapped_android_proof_class"),
            "mapped_evidence_trust_level": evidence.get("mapped_evidence_trust_level"),
            "message_id": evidence.get("message_id"),
            "snapshot_id": evidence.get("snapshot_id"),
        },
    )


def _build_surface_visibility_stage(
    *,
    device_id: Optional[str],
    session_id: Optional[str],
    truth_payload: Dict[str, Any],
    board_payload: Dict[str, Any],
) -> Dict[str, Any]:
    truth_visibility = _ensure_dict(truth_payload.get("shared_execution_visibility"))
    truth_participation = _ensure_dict(truth_payload.get("participation_truth_consumption"))
    board_visibility = _ensure_dict(board_payload.get("shared_execution_visibility"))
    board_participation = _ensure_dict(board_payload.get("participation_truth_consumption"))
    runtime_truth_visible = bool(truth_visibility) and bool(truth_participation)
    board_visible = bool(board_visibility) and bool(board_participation)
    closure_visible = bool(
        truth_visibility.get("result_closure_established")
        or board_visibility.get("result_closure_established")
        or truth_visibility.get("completion_state") == "closed"
        or board_visibility.get("completion_state") == "closed"
    )
    passed = bool(device_id) and runtime_truth_visible and board_visible and closure_visible
    summary = (
        f"最终态已进入 truth/panel：device_id={device_id} session_id={session_id}"
        if passed
        else "最终态尚未同时进入 truth 与 panel，需检查 surface 组装/闭合可见性"
    )
    return _stage(
        "surface_visibility",
        passed=passed,
        failure_boundary="surface_visibility",
        summary=summary,
        details={
            "device_id": device_id,
            "session_id": session_id,
            "runtime_truth_visible": runtime_truth_visible,
            "board_visible": board_visible,
            "closure_visible": closure_visible,
            "runtime_truth_completion_state": truth_visibility.get("completion_state"),
            "board_completion_state": board_visibility.get("completion_state"),
            "runtime_truth_selected_device_id": truth_participation.get("selected_device_id"),
            "board_selected_device_id": board_participation.get("selected_device_id"),
        },
    )


def _resolve_device_id(
    *,
    explicit_device_id: Optional[str],
    truth_payload: Dict[str, Any],
    board_payload: Dict[str, Any],
) -> Optional[str]:
    for candidate in (
        explicit_device_id,
        _ensure_dict(truth_payload.get("participation_truth_consumption")).get("selected_device_id"),
        _ensure_dict(board_payload.get("participation_truth_consumption")).get("selected_device_id"),
        _ensure_dict(truth_payload.get("runtime_decision_reasoning")).get("selected_device"),
        _ensure_dict(truth_payload.get("runtime_decision_reasoning")).get("selected_device_id"),
    ):
        if candidate not in (None, ""):
            return str(candidate)

    try:
        from core.android_acceptance_evidence_store import list_device_acceptance_evidence_dicts

        evidence_records = list_device_acceptance_evidence_dicts()
        if evidence_records:
            return str(evidence_records[-1].get("device_id") or "") or None
    except Exception:
        pass

    try:
        from core.mesh.android_mesh_lifecycle_store import get_android_mesh_lifecycle_store

        sessions = get_android_mesh_lifecycle_store().get_all_sessions()
        if sessions:
            latest_session = sorted(sessions, key=_session_timestamp_key)[-1]
            return str(getattr(latest_session, "device_id", "") or "") or None
    except Exception:
        pass
    return None


def _resolve_mesh_session(
    *,
    device_id: Optional[str],
    explicit_session_id: Optional[str],
) -> Dict[str, Any]:
    if explicit_session_id:
        try:
            from core.mesh.android_mesh_lifecycle_store import get_android_mesh_lifecycle_store

            record = get_android_mesh_lifecycle_store().get_session(str(explicit_session_id))
            if record is not None:
                return record.to_dict()
        except Exception:
            pass
        return {"session_id": explicit_session_id}

    if not device_id:
        return {}

    try:
        from core.mesh.android_mesh_lifecycle_store import get_sessions_for_device

        sessions = get_sessions_for_device(str(device_id), include_terminal=True)
        if not sessions:
            return {}
        latest = sorted(sessions, key=_session_timestamp_key)[-1]
        return latest.to_dict()
    except Exception:
        return {}


def _stage(
    stage: str,
    *,
    passed: bool,
    failure_boundary: str,
    summary: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "stage": stage,
        "status": "passed" if passed else "failed",
        "failure_boundary": failure_boundary,
        "summary": summary,
        "details": details,
    }


def _build_chain_summary(
    *,
    overall_status: str,
    device_id: Optional[str],
    session_id: Optional[str],
    stages: List[Dict[str, Any]],
) -> str:
    stage_summary = ", ".join(f"{stage['stage']}={stage['status']}" for stage in stages)
    return (
        f"overall={overall_status}; device_id={device_id}; session_id={session_id}; "
        f"stages=[{stage_summary}]"
    )


def _session_timestamp_key(value: Any) -> tuple[float, float]:
    return (
        float(getattr(value, "updated_at", 0.0) or 0.0),
        float(getattr(value, "created_at", 0.0) or 0.0),
    )


def _ensure_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "ANDROID_REPO_COORDINATION_ASSUMPTIONS",
    "CROSS_REPO_ACCEPTANCE_CHAIN_AUTHORITY",
    "build_cross_repo_acceptance_chain",
]
