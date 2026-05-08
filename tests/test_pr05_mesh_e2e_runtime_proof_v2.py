"""PR-05 (V2 side): mesh E2E runtime proof surfaces and lifecycle validation."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

try:
    from contracts.mesh_session_coordinator import (
        MeshBarrierState,
        MeshBarrierStatus,
        MeshCoordinatorStatus,
        MeshParticipantCoordinationState,
        MeshParticipantStatus,
        from_mesh_session,
    )
    from core.mesh.mesh_runtime_center_state import (
        MeshRuntimeCenterStatus,
        build_mesh_runtime_center_state,
        evaluate_center_runtime_status,
    )

    _PR05_DEPENDENCIES_AVAILABLE = True
except ImportError:
    _PR05_DEPENDENCIES_AVAILABLE = False


def _make_coordinator_state(
    *,
    session_id: str,
    coordinator_status: str,
    barrier_status: str,
    participant_specs: List[Dict[str, Any]],
) -> Any:
    base = from_mesh_session(
        {
            "session_id": session_id,
            "mesh_id": f"mesh_{session_id}",
            "participants": [
                {
                    "device_id": spec["device_id"],
                    "roles": spec.get("roles", ["support"]),
                    "online": spec.get("online", True),
                    "status": spec.get("status", "pending"),
                }
                for spec in participant_specs
            ],
            "multi_device_required": True,
            "barrier_posture": "soft_barrier",
        },
        trace_id=f"trace_{session_id}",
    )
    participants = [
        MeshParticipantCoordinationState(
            device_id=spec["device_id"],
            roles=spec.get("roles", ["support"]),
            online=spec.get("online", True),
            status=MeshParticipantStatus(spec["status"]),
        )
        for spec in participant_specs
    ]
    waiting_device_ids = [spec["device_id"] for spec in participant_specs if spec["status"] == "waiting"]
    barrier = MeshBarrierState(
        status=MeshBarrierStatus(barrier_status),
        released=barrier_status == "released",
        waiting_device_ids=waiting_device_ids,
    )
    return base.model_copy(
        update={
            "status": MeshCoordinatorStatus(coordinator_status),
            "participants": participants,
            "barrier_state": barrier,
        }
    )


@pytest.mark.skipif(not _PR05_DEPENDENCIES_AVAILABLE, reason="required contracts/runtime modules not available")
class TestPR05MeshE2ERuntimeProofV2:
    def test_lifecycle_proof_participation_ready_is_not_runtime_closed(self) -> None:
        coord = _make_coordinator_state(
            session_id="pr05_ready",
            coordinator_status="pending",
            barrier_status="open",
            participant_specs=[
                {"device_id": "d1", "status": "pending"},
                {"device_id": "d2", "status": "pending"},
            ],
        )
        center_state = evaluate_center_runtime_status(coord)
        proof = center_state.to_dict()["lifecycle_proof"]

        assert center_state.status == MeshRuntimeCenterStatus.participation_ready
        assert proof["participation_registered"] is True
        assert proof["participation_ready"] is True
        assert proof["runtime_closed"] is False
        assert proof["closure_classification"] == "participation_ready_not_closed"

    @pytest.mark.parametrize(
        ("session_id", "coordinator_status", "barrier_status", "participant_specs", "expected_status"),
        [
            (
                "pr05_active",
                "active",
                "open",
                [
                    {"device_id": "d1", "status": "working"},
                    {"device_id": "d2", "status": "working"},
                ],
                MeshRuntimeCenterStatus.runtime_active,
            ),
            (
                "pr05_barrier_wait",
                "awaiting_barrier",
                "waiting",
                [
                    {"device_id": "d1", "status": "waiting"},
                    {"device_id": "d2", "status": "waiting"},
                ],
                MeshRuntimeCenterStatus.barrier_active,
            ),
            (
                "pr05_barrier_release",
                "merging",
                "released",
                [
                    {"device_id": "d1", "status": "completed"},
                    {"device_id": "d2", "status": "completed"},
                ],
                MeshRuntimeCenterStatus.barrier_released,
            ),
            (
                "pr05_closed",
                "completed",
                "released",
                [
                    {"device_id": "d1", "status": "completed"},
                    {"device_id": "d2", "status": "completed"},
                ],
                MeshRuntimeCenterStatus.runtime_closed,
            ),
        ],
    )
    def test_lifecycle_proof_tracks_coordination_barrier_completion_matrix(
        self,
        session_id: str,
        coordinator_status: str,
        barrier_status: str,
        participant_specs: List[Dict[str, Any]],
        expected_status: MeshRuntimeCenterStatus,
    ) -> None:
        coord = _make_coordinator_state(
            session_id=session_id,
            coordinator_status=coordinator_status,
            barrier_status=barrier_status,
            participant_specs=participant_specs,
        )
        center_state = evaluate_center_runtime_status(coord)
        proof = center_state.to_dict()["lifecycle_proof"]

        assert center_state.status == expected_status
        assert proof["coordination_activated"] is True
        assert proof["barrier_wait_observed"] is (expected_status == MeshRuntimeCenterStatus.barrier_active)
        assert proof["barrier_release_observed"] is (
            expected_status in (MeshRuntimeCenterStatus.barrier_released, MeshRuntimeCenterStatus.runtime_closed)
        )
        assert proof["completion_observed"] is (
            expected_status in (MeshRuntimeCenterStatus.barrier_released, MeshRuntimeCenterStatus.runtime_closed)
        )

    def test_lifecycle_proof_marks_partial_degraded_path_without_runtime_closure(self) -> None:
        coord = _make_coordinator_state(
            session_id="pr05_partial_degraded",
            coordinator_status="partial",
            barrier_status="released",
            participant_specs=[
                {"device_id": "d1", "status": "completed"},
                {"device_id": "d2", "status": "failed"},
            ],
        )
        center_state = evaluate_center_runtime_status(coord)
        proof = center_state.to_dict()["lifecycle_proof"]

        assert center_state.status == MeshRuntimeCenterStatus.degraded
        assert center_state.is_participation_ready is True
        assert center_state.is_runtime_closed is False
        assert proof["partial_or_degraded_path"] is True
        assert proof["closure_classification"] == "participation_ready_not_closed"

    def test_operator_surface_build_includes_pr05_lifecycle_proof(self) -> None:
        coord = _make_coordinator_state(
            session_id="pr05_operator_surface",
            coordinator_status="pending",
            barrier_status="open",
            participant_specs=[{"device_id": "d1", "status": "pending"}],
        )
        payload = build_mesh_runtime_center_state(coord)
        assert "lifecycle_proof" in payload
        assert payload["lifecycle_proof"]["participation_registered"] is True
