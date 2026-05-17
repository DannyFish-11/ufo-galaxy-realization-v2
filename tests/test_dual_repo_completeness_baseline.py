"""双仓完整性基线快照测试。"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest


@pytest.fixture(autouse=True)
def _reset_state():
    from core.android_acceptance_evidence_store import clear_device_acceptance_evidence
    from core.device_lifecycle_state import reset_lifecycle_store
    from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store

    clear_device_acceptance_evidence()
    reset_lifecycle_store()
    reset_android_mesh_lifecycle_store()
    yield
    clear_device_acceptance_evidence()
    reset_lifecycle_store()
    reset_android_mesh_lifecycle_store()


def _build_truth_payload(device_id: str) -> Dict[str, Any]:
    return {
        "startup_readiness": {
            "ready_to_route": True,
            "dispatch_mode": "cross_device",
            "readiness_notes": [],
        },
        "runtime_decision_reasoning": {
            "selected_device": device_id,
            "selected_device_id": device_id,
        },
        "shared_execution_visibility": {
            "result_closure_established": True,
            "completion_state": "closed",
            "surface_execution_stage": "result_returned",
            "surface_summary": "result closed",
        },
        "participation_truth_consumption": {
            "selected_device_id": device_id,
            "participation_tier": "dispatch_eligible",
            "dispatch_eligible": True,
        },
    }


def test_baseline_exposes_stage_attribution_and_capability_matrix():
    from core.dual_repo_completeness_baseline import (
        CAPABILITY_CLASS_FULLY_WIRED,
        build_dual_repo_completeness_baseline,
    )

    payload = build_dual_repo_completeness_baseline()
    assert payload["overall_status"] == "failed"
    assert "device_ingress_auth" in payload["blocking_stage_ids"]
    assert payload["stage_order"] == [
        "clone",
        "setup",
        "config",
        "startup",
        "device_ingress_auth",
        "registration",
        "dispatch_participation",
        "mesh",
        "result_return",
        "truth_panel_surface",
    ]
    assert payload["classification_counts"][CAPABILITY_CLASS_FULLY_WIRED] >= 0
    assert sum(payload["classification_counts"].values()) == len(payload["capability_inventory"])
    assert payload["explicit_gaps"], "Explicit gaps must be exposed when baseline fails"


def test_baseline_can_close_cross_repo_chain_with_seeded_runtime_evidence():
    from core.android_acceptance_evidence_store import ingest_device_acceptance_report
    from core.device_lifecycle_state import (
        DeviceLifecycleTransitionEvent,
        transition_device_lifecycle,
    )
    from core.dual_repo_completeness_baseline import (
        CAPABILITY_CLASS_FULLY_WIRED,
        build_dual_repo_completeness_baseline,
    )
    from core.mesh.android_mesh_lifecycle_store import (
        record_mesh_join,
        record_mesh_leave,
        record_mesh_result,
    )

    device_id = f"baseline-{uuid.uuid4().hex[:8]}"
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    transition_device_lifecycle(
        device_id,
        DeviceLifecycleTransitionEvent.register_ack_sent,
        websocket_connected=True,
        registration_ack_success=True,
    )
    transition_device_lifecycle(
        device_id,
        DeviceLifecycleTransitionEvent.registration_fully_attached,
        registration_fully_attached=True,
        capability_visible=True,
    )
    transition_device_lifecycle(
        device_id,
        DeviceLifecycleTransitionEvent.readiness_satisfied,
        readiness_satisfied=True,
        dispatch_gate_passed=True,
    )

    record_mesh_join(device_id=device_id, session_id=session_id)
    record_mesh_result(device_id=device_id, session_id=session_id, payload={"result": {"status": "ok"}})
    record_mesh_leave(device_id=device_id, session_id=session_id)
    ingest_device_acceptance_report(
        device_id=device_id,
        payload={"acceptance_tag": "device_accepted_for_graduation"},
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
    )

    truth_payload = _build_truth_payload(device_id)
    board_payload = {
        "shared_execution_visibility": dict(truth_payload["shared_execution_visibility"]),
        "participation_truth_consumption": dict(truth_payload["participation_truth_consumption"]),
    }
    payload = build_dual_repo_completeness_baseline(
        truth_payload=truth_payload,
        board_payload=board_payload,
    )
    assert payload["overall_status"] == "passed"
    assert payload["blocking_stage_ids"] == []
    assert payload["acceptance_chain"]["overall_status"] == "passed"
    assert payload["classification_counts"][CAPABILITY_CLASS_FULLY_WIRED] >= 4


def test_projection_helper_exposes_dual_repo_completeness_baseline():
    from core.routes.projection import _build_dual_repo_completeness_baseline_projection

    device_id = f"projection-{uuid.uuid4().hex[:8]}"
    truth_payload = _build_truth_payload(device_id)
    board_payload = {
        "shared_execution_visibility": dict(truth_payload["shared_execution_visibility"]),
        "participation_truth_consumption": dict(truth_payload["participation_truth_consumption"]),
    }
    projection = _build_dual_repo_completeness_baseline_projection(
        truth_payload=truth_payload,
        board_payload=board_payload,
    )
    assert projection["stage_count"] == 10
    assert "capability_inventory" in projection
