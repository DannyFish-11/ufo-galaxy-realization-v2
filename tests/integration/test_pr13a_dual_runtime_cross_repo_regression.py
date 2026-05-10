"""PR-13A dual-runtime cross-repo regression entry points (V2-side)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple
from unittest.mock import AsyncMock, MagicMock

from core.android_device_state_store import (
    get_device_state_snapshot,
    list_recent_execution_events,
    reset_android_device_state_store,
)
from core.closed_loop_governance_consolidation import get_closed_loop_audit_record
from core.execution_governance_audit_authority import get_governance_audit_summary
from core.unified_dispatch_readiness_gate import evaluate_dispatch_readiness
from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    _clear_execution_governance_runtime_state,
    _register_active_execution,
    notify_execution_completed,
    record_execution_lifecycle_event,
    record_state_uplink,
)
from core.unified_governance_semantics import build_unified_governance_state
from galaxy_gateway.android_bridge import AndroidBridge

from ._dual_runtime_cross_repo_harness import (
    extract_canonical_android_runtime_messages,
    evidence_declares_real_android_runtime,
    evidence_declares_v2_runtime_participation,
    load_evidence_or_skip,
)


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


def _derive_execution_id_and_terminal_phase(
    messages: list[Dict[str, Any]],
    device_id: str,
) -> Tuple[str, ExecutionLifecyclePhase]:
    execution_msg = next((m for m in messages if m.get("type") == "device_execution_event"), None)
    assert execution_msg is not None, (
        "Dual-runtime evidence replay must include a canonical device_execution_event "
        "message to drive canonical closure/audit validation."
    )
    payload = execution_msg.get("payload") if isinstance(execution_msg, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    execution_id = str(
        payload.get("flow_id")
        or payload.get("flowId")
        or payload.get("execution_id")
        or payload.get("executionId")
        or payload.get("task_id")
        or payload.get("taskId")
        or f"dual_runtime_{device_id}"
    )
    if execution_id == f"dual_runtime_{device_id}":
        raise AssertionError(
            "device_execution_event payload must include flow_id/task_id/execution_id "
            "for canonical governance closure/audit validation."
        )
    phase = str(payload.get("phase") or "").strip().lower()
    if phase in {"failed", "failure", "error"}:
        return execution_id, ExecutionLifecyclePhase.failed
    if phase in {"cancelled", "canceled", "aborted"}:
        return execution_id, ExecutionLifecyclePhase.cancelled
    if phase in {"timed_out", "timeout"}:
        return execution_id, ExecutionLifecyclePhase.timed_out
    if phase in {"interrupted", "interrupt"}:
        return execution_id, ExecutionLifecyclePhase.interrupted
    return execution_id, ExecutionLifecyclePhase.succeeded


def test_cross_repo_evidence_declares_true_dual_runtime_participation() -> None:
    evidence = load_evidence_or_skip()
    assert evidence_declares_real_android_runtime(evidence), (
        "Cross-repo dual-runtime evidence must declare real Android runtime "
        "participation (real_device marker or equivalent)."
    )
    assert evidence_declares_v2_runtime_participation(evidence), (
        "Cross-repo dual-runtime evidence must also prove V2 runtime participation "
        "(explicit dual-runtime marker or V2 ACK evidence)."
    )


async def _replay_canonical_messages(
    bridge: AndroidBridge, ws: Any, messages: list[Dict[str, Any]]
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    acks: Dict[str, Dict[str, Any]] = {}
    device_id = ""
    for msg in messages:
        device_id = str(msg["device_id"])
        response = await bridge.handle_message(ws, msg)
        if response is not None:
            acks[msg["type"]] = response
    return device_id, acks


def test_cross_repo_evidence_replays_canonical_android_paths_against_v2_runtime() -> None:
    evidence = load_evidence_or_skip()
    messages = extract_canonical_android_runtime_messages(evidence)

    reset_android_device_state_store()
    try:
        bridge = AndroidBridge()
        ws = _make_ws()
        device_id, acks = asyncio.run(_replay_canonical_messages(bridge, ws, messages))

        assert acks["device_register"]["type"] == "device_register_ack"
        assert acks["capability_report"]["type"] == "capability_report_ack"
        assert acks["device_state_snapshot"]["type"] == "device_state_snapshot_ack"
        assert acks["device_execution_event"]["type"] == "device_execution_event_ack"

        state_snapshot = get_device_state_snapshot(device_id)
        assert state_snapshot is not None, (
            "Canonical dual-runtime replay must populate android_device_state_store "
            "with Android-originated runtime snapshot."
        )

        execution_events = list_recent_execution_events(device_id=device_id, limit=1)
        assert execution_events, (
            "Canonical dual-runtime replay must absorb Android execution events "
            "into V2 runtime state."
        )
    finally:
        reset_android_device_state_store()


def test_cross_repo_dual_runtime_evidence_exercises_closure_audit_readiness_and_diagnosis() -> None:
    evidence = load_evidence_or_skip()
    messages = extract_canonical_android_runtime_messages(evidence)

    reset_android_device_state_store()
    _clear_execution_governance_runtime_state()
    try:
        bridge = AndroidBridge()
        ws = _make_ws()
        device_id, _ = asyncio.run(_replay_canonical_messages(bridge, ws, messages))
        execution_id, terminal_phase = _derive_execution_id_and_terminal_phase(messages, device_id)

        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.admitted,
        )
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            payload={"source": "real_android_dual_runtime_replay"},
        )
        _register_active_execution(device_id, ExecutionType.delegated_execution, execution_id)
        notify_execution_completed(
            device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            execution_id=execution_id,
            completion_phase=terminal_phase,
        )

        closed_loop = get_closed_loop_audit_record(execution_id, device_id)
        assert closed_loop["closed_loop_view"]["stage"] == "completion"
        assert closed_loop["closed_loop_view"]["loop_is_coherent"] is True

        audit_summary = get_governance_audit_summary(execution_id, device_id)
        for required_key in (
            "canonical_truth_provenance",
            "canonical_truth_source_trust_level",
            "canonical_truth_freshness_state",
            "canonical_truth_freshness_reason",
        ):
            assert required_key in audit_summary
        assert isinstance(audit_summary.get("cross_repo_truth_pipeline_verdict"), str)
        assert "cross_repo_truth_source_provenance" in audit_summary

        readiness = evaluate_dispatch_readiness(device_id)
        assert readiness.registered is True
        assert readiness.status != "not_registered"

        governance_state = build_unified_governance_state(device_ids=[device_id])
        device_view = next((d for d in governance_state["devices"] if d["device_id"] == device_id), None)
        assert device_view is not None, (
            "Replayed dual-runtime Android participant must appear in unified governance state."
        )
        delegated = device_view["governance_precedence"]["delegated_execution"]
        causality = delegated["decision_causality"]
        diagnosis = causality["android_originated_canonical_diagnosis"]
        assert isinstance(diagnosis, dict)
        for key in ("runtime", "capability", "recovery", "takeover", "mesh"):
            assert key in diagnosis
    finally:
        _clear_execution_governance_runtime_state()
        reset_android_device_state_store()
