"""PR-20: 跨仓 Android→V2 验收链阶段化验证。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _v3(msg_type: str, device_id: str, **extra: Any) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


@pytest.fixture(autouse=True)
def _reset_cross_repo_state():
    from core.android_acceptance_evidence_store import clear_device_acceptance_evidence
    from core.android_device_state_store import reset_android_device_state_store
    from core.device_lifecycle_state import reset_lifecycle_store
    from core.mesh.android_mesh_lifecycle_store import reset_android_mesh_lifecycle_store
    from galaxy_gateway.android.handlers.registration import clear_registration_gaps

    clear_device_acceptance_evidence()
    reset_android_device_state_store()
    reset_lifecycle_store()
    reset_android_mesh_lifecycle_store()
    clear_registration_gaps()
    yield
    clear_device_acceptance_evidence()
    reset_android_device_state_store()
    reset_lifecycle_store()
    reset_android_mesh_lifecycle_store()
    clear_registration_gaps()


def _build_truth_payload(device_id: str) -> Dict[str, Any]:
    from core.routes.projection import (
        _build_participation_truth_consumption,
        _derive_shared_execution_visibility,
    )

    truth_payload: Dict[str, Any] = {
        "tri_state_phase": "manifest",
        "continuum": {"runtime_domain": "cross_device"},
        "runtime_decision_reasoning": {
            "selected_device": device_id,
            "participation_tier": "dispatch_eligible",
            "unified_mode_model": {
                "participation_layer": "dispatch_eligible",
                "execution_location": "android_delegated",
                "governance_state": "delegated_execution",
                "participation_semantics": {
                    "dispatch_gate_passed": True,
                    "mode_semantics": {
                        "local_mode_active": False,
                        "constrained": False,
                    },
                },
            },
            "closure_basis": {
                "task_completed": True,
                "is_fully_closed": True,
                "acceptance_verdict": "accepted",
            },
        },
        "operational_state_board": {
            "task_execution_visibility": {
                "task_initiated": True,
                "result_closure_established": True,
            },
            "dependencies_and_blockers": {
                "blocked": False,
                "incomplete": False,
                "waiting_dependencies": [],
            },
        },
    }
    truth_payload["shared_execution_visibility"] = _derive_shared_execution_visibility(truth_payload)
    truth_payload["participation_truth_consumption"] = _build_participation_truth_consumption(
        truth_payload
    )
    return truth_payload


class TestCrossRepoAcceptanceChain:
    @pytest.mark.asyncio
    async def test_representative_chain_is_stage_attributable_and_regression_ready(self):
        from core.cross_repo_acceptance_chain import build_cross_repo_acceptance_chain
        from core.device_lifecycle_state import (
            DeviceLifecycleTransitionEvent,
            transition_device_lifecycle,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        device_id = f"pr20-{uuid.uuid4().hex[:8]}"
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        bridge = AndroidBridge()
        ws = _make_ws()

        reg_ack = await bridge.handle_message(ws, _v3("device_register", device_id))
        assert reg_ack is not None
        assert reg_ack["type"] == "device_register_ack"

        transition_device_lifecycle(
            device_id,
            DeviceLifecycleTransitionEvent.registration_fully_attached,
            registration_fully_attached=True,
            capability_visible=True,
        )

        with patch("core.android_mode_gate_policy.evaluate_android_mode_readiness") as mock_gate:
            mock_gate.return_value = MagicMock(
                is_dispatch_eligible=True,
                is_takeover_eligible=False,
            )
            state_ack = await bridge.handle_message(
                ws,
                _v3(
                    "device_state_snapshot",
                    device_id,
                    payload={
                        "model_ready": True,
                        "accessibility_ready": True,
                        "local_loop_ready": True,
                        "local_loop_config": {"cross_device_enabled": True},
                    },
                ),
            )
        assert state_ack is not None
        assert state_ack["type"] == "device_state_snapshot_ack"

        exec_ack = await bridge.handle_message(
            ws,
            _v3(
                "device_execution_event",
                device_id,
                payload={
                    "flow_id": f"flow-{uuid.uuid4().hex[:6]}",
                    "task_id": f"task-{uuid.uuid4().hex[:6]}",
                    "phase": "execution",
                    "step_index": 1,
                },
            ),
        )
        assert exec_ack is not None
        assert exec_ack["type"] == "device_execution_event_ack"

        join_ack = await bridge.handle_message(
            ws,
            _v3("mesh_join", device_id, payload={"session_id": session_id}),
        )
        result_ack = await bridge.handle_message(
            ws,
            _v3(
                "mesh_result",
                device_id,
                payload={"session_id": session_id, "result": {"status": "ok"}},
            ),
        )
        leave_ack = await bridge.handle_message(
            ws,
            _v3("mesh_leave", device_id, payload={"session_id": session_id}),
        )
        acceptance_ack = await bridge.handle_message(
            ws,
            _v3(
                "device_acceptance_report",
                device_id,
                payload={
                    "acceptance_tag": "device_accepted_for_graduation",
                    "snapshot_id": "snap-pr20",
                },
            ),
        )

        assert join_ack["type"] == "mesh_join_ack"
        assert result_ack["type"] == "mesh_result_ack"
        assert leave_ack["type"] == "mesh_leave_ack"
        assert acceptance_ack["type"] == "device_acceptance_report_ack"

        truth_payload = _build_truth_payload(device_id)
        board_payload = {
            "shared_execution_visibility": dict(truth_payload["shared_execution_visibility"]),
            "participation_truth_consumption": dict(
                truth_payload["participation_truth_consumption"]
            ),
        }
        snapshot = build_cross_repo_acceptance_chain(
            device_id=device_id,
            session_id=session_id,
            truth_payload=truth_payload,
            board_payload=board_payload,
        )

        assert snapshot["overall_status"] == "passed"
        assert snapshot["regression_ready"] is True
        assert snapshot["failure_boundaries"] == []
        assert [stage["status"] for stage in snapshot["stages"]] == ["passed"] * 6

    def test_mesh_gap_is_attributed_to_mesh_stage_not_generic_failure(self):
        from core.android_acceptance_evidence_store import ingest_device_acceptance_report
        from core.cross_repo_acceptance_chain import build_cross_repo_acceptance_chain
        from core.device_lifecycle_state import (
            DeviceLifecycleTransitionEvent,
            transition_device_lifecycle,
        )

        device_id = f"pr20-gap-{uuid.uuid4().hex[:8]}"
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
        transition_device_lifecycle(
            device_id,
            DeviceLifecycleTransitionEvent.execution_session_started,
            execution_active=True,
        )
        ingest_device_acceptance_report(
            device_id=device_id,
            payload={"acceptance_tag": "device_accepted_for_graduation"},
            message_id="msg-gap",
        )

        truth_payload = _build_truth_payload(device_id)
        board_payload = {
            "shared_execution_visibility": dict(truth_payload["shared_execution_visibility"]),
            "participation_truth_consumption": dict(
                truth_payload["participation_truth_consumption"]
            ),
        }
        snapshot = build_cross_repo_acceptance_chain(
            device_id=device_id,
            truth_payload=truth_payload,
            board_payload=board_payload,
        )

        assert snapshot["overall_status"] == "failed"
        assert snapshot["failing_stage"] == "mesh_lifecycle"
        assert snapshot["failure_boundaries"][0]["boundary"] == "mesh_lifecycle"
        mesh_stage = next(
            (stage for stage in snapshot["stages"] if stage["stage"] == "mesh_lifecycle"),
            None,
        )
        assert mesh_stage is not None
        assert "mesh 生命周期缺口" in mesh_stage["summary"]
