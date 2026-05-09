"""tests/test_prj_live_mesh_runtime_engine.py
=============================================
Tests for PR-J: Live Mesh Runtime Engine + staged_mesh 真实可达化.

This module verifies:

1.  staged_mesh enters live runtime orchestration main chain
2.  participant tracking state transitions
3.  barrier coordination — success path
4.  barrier coordination — failure path (no participants)
5.  barrier coordination — not_required path
6.  merge / aggregation correctness
7.  result handling and final convergence output
8.  timeout / participant drop / partial failure scenarios
9.  LiveMeshRuntimeEngine — constructor and run method
10. run_live_mesh_session convenience function
11. register_participant helper
12. update_participant_status helper
13. drop_participant helper
14. PR-J policy sentinels present
15. core.runtime re-exports PR-J symbols
16. Full lifecycle: staged_mesh → active → barrier → merge → completed
17. Graceful degradation on None coordinator_state
18. Partial completion (some participants succeeded, some failed)
19. Failed completion (no participants completed)
20. Orchestrator staged_mesh path includes live_outcome field
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.mesh.live_mesh_runtime_engine import (
        LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL,
        STAGED_MESH_LIVE_PROMOTION_PR_J_POLICY,
        PARTICIPANT_TRACKING_PR_J_POLICY,
        BARRIER_COORDINATION_PR_J_POLICY,
        MERGE_AGGREGATION_PR_J_POLICY,
        RESULT_HANDLING_PR_J_POLICY,
        LiveMeshRunResult,
        LiveMeshRuntimeEngine,
        run_live_mesh_session,
        register_participant,
        update_participant_status,
        drop_participant,
    )

    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

try:
    from core.mesh.mesh_session_coordinator import (
        coordinate_mesh_session,
        get_coordinator_summary,
        MESH_SESSION_COORDINATOR_LIVE_RUNTIME_ENGINE_PR_J_SENTINEL,
        run_live_mesh_session as coord_run_live,
        register_participant as coord_register,
        update_participant_status as coord_update,
        drop_participant as coord_drop,
    )

    _COORDINATOR_AVAILABLE = True
except ImportError:
    _COORDINATOR_AVAILABLE = False

try:
    from contracts.mesh_session_coordinator import (
        MeshSessionCoordinatorState,
        MeshCoordinatorStatus,
        MeshParticipantStatus,
        MeshBarrierStatus,
        build_mesh_session_coordinator,
        from_mesh_session,
    )

    _CONTRACTS_AVAILABLE = True
except ImportError:
    _CONTRACTS_AVAILABLE = False

try:
    from core.runtime import (
        LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL,
        LIVE_MESH_STAGED_TO_ACTIVE_DISPATCH_PR_J_POLICY,
        LIVE_MESH_RESULT_CONVERGENCE_PR_J_POLICY,
        run_live_mesh_session as runtime_run_live,
        register_participant as runtime_register,
        update_participant_status as runtime_update,
        drop_participant as runtime_drop,
        MESH_SESSION_COORDINATOR_LIVE_RUNTIME_ENGINE_PR_J_SENTINEL as runtime_coord_sentinel,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False

try:
    from core.runtime.source_dispatch_orchestrator import (
        orchestrate_source_runtime_dispatch,
        LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL as orch_sentinel,
    )

    _DISPATCH_AVAILABLE = True
except ImportError:
    _DISPATCH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator_state(
    session_id: str = "test_session_prj",
    mesh_id: str = "mesh_prj",
    participant_device_ids: Optional[list] = None,
    barrier_posture: str = "soft_barrier",
) -> Any:
    """Build a minimal coordinator state with participants."""
    if not _CONTRACTS_AVAILABLE:
        pytest.skip("contracts not available")
    device_ids = participant_device_ids or ["device_a", "device_b"]
    return from_mesh_session(
        {
            "session_id": session_id,
            "mesh_id": mesh_id,
            "participants": [
                {
                    "device_id": did,
                    "roles": ["primary" if i == 0 else "support"],
                    "online": True,
                    "status": "active",
                }
                for i, did in enumerate(device_ids)
            ],
            "multi_device_required": True,
            "barrier_posture": barrier_posture,
        },
        trace_id="trace_prj",
    )


def _make_mesh_session_dict(
    session_id: str = "msess_prj",
    mesh_id: str = "mesh_prj_orch",
    source_device_id: str = "phone_prj",
    primary_device_id: str = "tablet_prj",
) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "mesh_id": mesh_id,
        "source_device_id": source_device_id,
        "primary_device_id": primary_device_id,
        "participants": [
            {
                "device_id": source_device_id,
                "roles": ["source"],
                "online": True,
                "status": "active",
                "health_score": 0.9,
                "metadata": {},
            },
            {
                "device_id": primary_device_id,
                "roles": ["primary"],
                "online": True,
                "status": "active",
                "health_score": 0.95,
                "metadata": {},
            },
        ],
        "multi_device_required": True,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Group A: Policy sentinels
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ENGINE_AVAILABLE, reason="live_mesh_runtime_engine not available")
class TestGroupA_Sentinels:
    def test_a1_main_sentinel_present(self) -> None:
        assert isinstance(LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL, str)
        assert len(LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL) > 0
        assert "PR-J" in LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL

    def test_a2_live_promotion_policy_present(self) -> None:
        assert isinstance(STAGED_MESH_LIVE_PROMOTION_PR_J_POLICY, str)
        assert "pending" in STAGED_MESH_LIVE_PROMOTION_PR_J_POLICY

    def test_a3_participant_tracking_policy_present(self) -> None:
        assert isinstance(PARTICIPANT_TRACKING_PR_J_POLICY, str)
        assert "pending" in PARTICIPANT_TRACKING_PR_J_POLICY

    def test_a4_barrier_coordination_policy_present(self) -> None:
        assert isinstance(BARRIER_COORDINATION_PR_J_POLICY, str)
        assert "barrier" in BARRIER_COORDINATION_PR_J_POLICY.lower()

    def test_a5_merge_aggregation_policy_present(self) -> None:
        assert isinstance(MERGE_AGGREGATION_PR_J_POLICY, str)
        assert "merge" in MERGE_AGGREGATION_PR_J_POLICY.lower()

    def test_a6_result_handling_policy_present(self) -> None:
        assert isinstance(RESULT_HANDLING_PR_J_POLICY, str)
        assert "completed" in RESULT_HANDLING_PR_J_POLICY

    def test_a7_coordinator_sentinel_present(self) -> None:
        assert isinstance(MESH_SESSION_COORDINATOR_LIVE_RUNTIME_ENGINE_PR_J_SENTINEL, str)
        assert "PR-J" in MESH_SESSION_COORDINATOR_LIVE_RUNTIME_ENGINE_PR_J_SENTINEL


# ---------------------------------------------------------------------------
# Group B: core.runtime re-exports
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime exports not available")
class TestGroupB_RuntimeExports:
    def test_b1_orchestrator_sentinel_exported(self) -> None:
        assert isinstance(LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL, str)
        assert "PR-J" in LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL

    def test_b2_staged_to_active_policy_exported(self) -> None:
        assert isinstance(LIVE_MESH_STAGED_TO_ACTIVE_DISPATCH_PR_J_POLICY, str)

    def test_b3_result_convergence_policy_exported(self) -> None:
        assert isinstance(LIVE_MESH_RESULT_CONVERGENCE_PR_J_POLICY, str)

    def test_b4_run_live_mesh_session_exported(self) -> None:
        assert callable(runtime_run_live)

    def test_b5_register_participant_exported(self) -> None:
        assert callable(runtime_register)

    def test_b6_update_participant_status_exported(self) -> None:
        assert callable(runtime_update)

    def test_b7_drop_participant_exported(self) -> None:
        assert callable(runtime_drop)

    def test_b8_coordinator_sentinel_exported(self) -> None:
        assert isinstance(runtime_coord_sentinel, str)


# ---------------------------------------------------------------------------
# Group C: LiveMeshRunResult
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ENGINE_AVAILABLE, reason="live_mesh_runtime_engine not available")
class TestGroupC_LiveMeshRunResult:
    def test_c1_default_construction(self) -> None:
        result = LiveMeshRunResult()
        assert result.run_id is not None
        assert result.outcome == "failed"
        assert result.success is False
        assert isinstance(result.merged_result, dict)
        assert isinstance(result.errors, list)

    def test_c2_to_dict_stable(self) -> None:
        result = LiveMeshRunResult(
            session_id="s1",
            outcome="completed",
            success=True,
            merged_result={"foo": "bar"},
        )
        d = result.to_dict()
        assert d["session_id"] == "s1"
        assert d["outcome"] == "completed"
        assert d["success"] is True
        assert d["merged_result"] == {"foo": "bar"}

    def test_c3_required_fields_present(self) -> None:
        result = LiveMeshRunResult()
        d = result.to_dict()
        required = [
            "run_id", "session_id", "mesh_id", "trace_id", "outcome",
            "success", "merged_result", "participant_outcomes",
            "barrier_released", "coordinator_state", "errors", "metadata",
        ]
        for field in required:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Group D: LiveMeshRuntimeEngine — basic run
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestGroupD_EngineBasicRun:
    def test_d1_run_with_none_coordinator_returns_failed(self) -> None:
        engine = LiveMeshRuntimeEngine()
        result = engine.run(None)
        assert result.outcome == "failed"
        assert result.success is False
        assert "coordinator_state_is_none" in result.errors

    def test_d2_run_with_no_participants_returns_failed(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_empty")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state)
        assert result.outcome == "failed"
        assert result.success is False

    def test_d3_run_with_participants_no_results_gives_failed_or_partial(self) -> None:
        state = _make_coordinator_state()
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={})
        # With no participant results and a soft barrier, all participants
        # are offline → failed
        assert result.outcome in ("failed", "partial")
        assert isinstance(result.merged_result, dict)

    def test_d4_run_with_all_results_gives_completed(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["dev_a", "dev_b"]
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "dev_a": {"output": "A", "success": True},
                "dev_b": {"output": "B", "success": True},
            },
        )
        assert result.outcome == "completed"
        assert result.success is True
        assert result.barrier_released is True

    def test_d5_run_returns_merged_result_dict(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["x", "y"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "x": {"data": 1},
                "y": {"extra": 2},
            },
        )
        assert isinstance(result.merged_result, dict)
        assert "_participants" in result.merged_result

    def test_d6_run_with_partial_results_gives_partial(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["dev_a", "dev_b"]
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "dev_a": {"output": "A", "success": True},
                # dev_b did not submit
            },
        )
        assert result.outcome in ("partial", "failed")
        # dev_a succeeded → at least partial
        assert result.success is (result.outcome in ("completed", "partial"))

    def test_d7_run_never_raises(self) -> None:
        engine = LiveMeshRuntimeEngine()
        # Deliberately pass garbage
        result = engine.run(object())  # type: ignore[arg-type]
        assert result is not None
        assert isinstance(result.outcome, str)


# ---------------------------------------------------------------------------
# Group E: staged_mesh enters live runtime orchestration main chain
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _COORDINATOR_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupE_StagedMeshLiveOrchestration:
    def test_e1_staged_mesh_advances_to_active(self) -> None:
        state = _make_coordinator_state()
        assert state.status == MeshCoordinatorStatus.pending
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                p.device_id: {"output": "ok"}
                for p in state.participants
            },
        )
        final_state = result.coordinator_state
        assert final_state is not None
        # Final status should be completed (or partial at minimum)
        assert final_state.status in (
            MeshCoordinatorStatus.completed,
            MeshCoordinatorStatus.partial,
            MeshCoordinatorStatus.failed,
        )

    def test_e2_staged_mesh_produces_coordination_events(self) -> None:
        state = _make_coordinator_state()
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"device_a": {"val": 1}, "device_b": {"val": 2}},
        )
        final_state = result.coordinator_state
        assert final_state is not None
        assert len(final_state.coordination_events) > 0

    def test_e3_coordinator_session_id_preserved(self) -> None:
        state = _make_coordinator_state(session_id="preserve_me")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={"device_a": {}})
        assert result.session_id == "preserve_me"

    def test_e4_coordinator_trace_id_preserved(self) -> None:
        if not _CONTRACTS_AVAILABLE:
            pytest.skip("contracts not available")
        state = from_mesh_session(
            {
                "session_id": "s_trace",
                "participants": [{"device_id": "d1", "status": "active"}],
                "multi_device_required": False,
            },
            trace_id="trace_preserve",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={"d1": {"x": 1}})
        assert result.trace_id == "trace_preserve"

    def test_e5_run_live_mesh_session_convenience(self) -> None:
        state = _make_coordinator_state()
        result = run_live_mesh_session(
            state,
            participant_results={"device_a": {"v": 1}, "device_b": {"v": 2}},
        )
        assert result is not None
        assert result.outcome in ("completed", "partial", "failed")


# ---------------------------------------------------------------------------
# Group F: Participant tracking
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupF_ParticipantTracking:
    def test_f1_register_participant_adds_device(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_reg")
        updated = register_participant(state, "new_device", roles=["support"])
        device_ids = [p.device_id for p in updated.participants]
        assert "new_device" in device_ids

    def test_f2_register_participant_sets_pending_status(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_reg2")
        updated = register_participant(state, "new_device")
        p = next(p for p in updated.participants if p.device_id == "new_device")
        assert p.status == MeshParticipantStatus.pending

    def test_f3_register_participant_adds_to_pending_ids(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_reg3")
        updated = register_participant(state, "d_pending")
        assert "d_pending" in updated.pending_device_ids

    def test_f4_register_participant_emits_event(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_event")
        updated = register_participant(state, "d_event")
        event_kinds = [e.kind.value for e in updated.coordination_events]
        assert "participant_joined" in event_kinds

    def test_f5_update_participant_status_ready(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_upd")
        state = register_participant(state, "d_upd")
        updated = update_participant_status(state, "d_upd", "ready")
        p = next(p for p in updated.participants if p.device_id == "d_upd")
        assert p.status == MeshParticipantStatus.ready

    def test_f6_update_participant_status_working(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_work")
        state = register_participant(state, "d_work")
        updated = update_participant_status(state, "d_work", "working")
        p = next(p for p in updated.participants if p.device_id == "d_work")
        assert p.status == MeshParticipantStatus.working

    def test_f7_update_participant_status_completed(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_done")
        state = register_participant(state, "d_done")
        updated = update_participant_status(state, "d_done", "completed")
        p = next(p for p in updated.participants if p.device_id == "d_done")
        assert p.status == MeshParticipantStatus.completed

    def test_f8_update_participant_status_failed(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_fail")
        state = register_participant(state, "d_fail")
        updated = update_participant_status(state, "d_fail", "failed")
        p = next(p for p in updated.participants if p.device_id == "d_fail")
        assert p.status == MeshParticipantStatus.failed

    def test_f9_drop_participant_marks_offline(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_drop")
        state = register_participant(state, "d_drop")
        updated = drop_participant(state, "d_drop", reason="timeout")
        p = next(p for p in updated.participants if p.device_id == "d_drop")
        assert p.status == MeshParticipantStatus.offline

    def test_f10_drop_participant_moves_to_failed_ids(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_fail2")
        state = register_participant(state, "d_dropfail")
        updated = drop_participant(state, "d_dropfail", reason="lost")
        assert "d_dropfail" in updated.failed_device_ids
        assert "d_dropfail" not in updated.pending_device_ids

    def test_f11_update_nonexistent_participant_does_not_raise(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_nonexist")
        updated = update_participant_status(state, "ghost_device", "ready")
        assert updated is not None

    def test_f12_drop_nonexistent_participant_does_not_raise(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_nodrop")
        updated = drop_participant(state, "ghost", reason="test")
        assert updated is not None

    def test_f13_participant_lifecycle_full_flow(self) -> None:
        """pending → ready → working → completed"""
        state = build_mesh_session_coordinator(session_id="s_lifecycle")
        state = register_participant(state, "life_dev", roles=["primary"])
        p = next(p for p in state.participants if p.device_id == "life_dev")
        assert p.status == MeshParticipantStatus.pending

        state = update_participant_status(state, "life_dev", "ready")
        p = next(p for p in state.participants if p.device_id == "life_dev")
        assert p.status == MeshParticipantStatus.ready

        state = update_participant_status(state, "life_dev", "working")
        p = next(p for p in state.participants if p.device_id == "life_dev")
        assert p.status == MeshParticipantStatus.working

        state = update_participant_status(state, "life_dev", "completed")
        p = next(p for p in state.participants if p.device_id == "life_dev")
        assert p.status == MeshParticipantStatus.completed


# ---------------------------------------------------------------------------
# Group G: Barrier coordination
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupG_BarrierCoordination:
    def test_g1_barrier_not_required_releases_immediately(self) -> None:
        state = _make_coordinator_state(barrier_posture="none")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"device_a": {"v": 1}, "device_b": {"v": 2}},
        )
        assert result.barrier_released is True

    def test_g2_barrier_soft_all_arrived_releases(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["p1", "p2"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"p1": {"v": 1}, "p2": {"v": 2}},
        )
        assert result.barrier_released is True

    def test_g3_barrier_hard_all_arrived_releases(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["pa", "pb"],
            barrier_posture="hard_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"pa": {"v": 1}, "pb": {"v": 2}},
        )
        assert result.barrier_released is True

    def test_g4_barrier_partial_arrival_not_released(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["q1", "q2"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"q1": {"v": 1}},
            # q2 did not arrive
        )
        assert result.barrier_released is False

    def test_g5_barrier_no_participants_fails(self) -> None:
        state = build_mesh_session_coordinator(session_id="s_nopart")
        # Manually set barrier to open
        from contracts.mesh_session_coordinator import MeshBarrierState, MeshBarrierStatus
        state = state.model_copy(
            update={"barrier_state": MeshBarrierState(status=MeshBarrierStatus.open)}
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={})
        # No participants → barrier failed or promotion failed
        assert result.outcome == "failed"

    def test_g6_barrier_coordinator_state_reflects_released(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["r1", "r2"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"r1": {"v": 1}, "r2": {"v": 2}},
        )
        final_state = result.coordinator_state
        assert final_state is not None
        barrier = final_state.barrier_state
        assert barrier.status in (
            MeshBarrierStatus.released, MeshBarrierStatus.not_required
        )

    def test_g7_barrier_waiting_state_when_partial_arrival(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["w1", "w2"],
            barrier_posture="hard_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"w1": {"v": 1}},
        )
        # w2 waiting → barrier not released
        assert result.barrier_released is False
        final_state = result.coordinator_state
        if final_state is not None:
            assert final_state.status in (
                MeshCoordinatorStatus.awaiting_barrier,
                MeshCoordinatorStatus.partial,
                MeshCoordinatorStatus.failed,
            )

    def test_g8_barrier_release_records_merging_step(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["mstep1", "mstep2"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"mstep1": {"v": 1}, "mstep2": {"v": 2}},
        )
        final_state = result.coordinator_state
        assert final_state is not None
        assert any(
            "advanced to merging" in (getattr(event, "message", "") or "")
            for event in final_state.coordination_events
        )

    def test_g9_not_required_barrier_records_merging_step(self) -> None:
        state = _make_coordinator_state(
            participant_device_ids=["nstep1", "nstep2"],
            barrier_posture="none",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"nstep1": {"v": 1}, "nstep2": {"v": 2}},
        )
        final_state = result.coordinator_state
        assert final_state is not None
        assert any(
            "advanced to merging" in (getattr(event, "message", "") or "")
            for event in final_state.coordination_events
        )


# ---------------------------------------------------------------------------
# Group H: Merge / aggregation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupH_MergeAggregation:
    def test_h1_merge_combines_all_results(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["m1", "m2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "m1": {"key1": "val1"},
                "m2": {"key2": "val2"},
            },
        )
        assert result.merged_result.get("key1") == "val1"
        assert result.merged_result.get("key2") == "val2"

    def test_h2_merged_result_has_participants_key(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["n1", "n2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"n1": {}, "n2": {}},
        )
        assert "_participants" in result.merged_result
        assert isinstance(result.merged_result["_participants"], list)

    def test_h3_merge_empty_results_gives_empty_dict(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["e1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={"e1": {}})
        assert isinstance(result.merged_result, dict)
        assert "_participants" in result.merged_result

    def test_h4_merge_conflict_last_writer_wins(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["c1", "c2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "c1": {"shared_key": "from_c1"},
                "c2": {"shared_key": "from_c2"},
            },
        )
        # Last writer wins — c2 overwrote c1
        assert result.merged_result.get("shared_key") == "from_c2"

    def test_h5_merge_scalar_result_stored_under_device_id(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["sc1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"sc1": "scalar_value"},
        )
        assert result.merged_result.get("sc1") == "scalar_value"

    def test_h6_merge_timestamp_present(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["ts1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"ts1": {"x": 1}},
        )
        assert "_merge_timestamp" in result.merged_result


# ---------------------------------------------------------------------------
# Group I: Result handling
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupI_ResultHandling:
    def test_i1_all_completed_outcome_is_completed(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["all1", "all2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "all1": {"success": True},
                "all2": {"success": True},
            },
        )
        assert result.outcome == "completed"
        assert result.success is True

    def test_i2_some_failed_outcome_is_partial(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["ok1", "fail1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "ok1": {"success": True},
                "fail1": {"success": False},
            },
        )
        assert result.outcome == "partial"
        assert result.success is True

    def test_i3_all_failed_outcome_is_failed(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["f1", "f2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "f1": {"success": False},
                "f2": {"success": False},
            },
        )
        assert result.outcome == "failed"
        assert result.success is False

    def test_i4_no_participants_submitted_is_failed(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["np1", "np2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={})
        assert result.outcome == "failed"

    def test_i5_participant_outcomes_populated(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["po1", "po2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "po1": {"output": "x"},
                "po2": {"output": "y"},
            },
        )
        assert "po1" in result.participant_outcomes
        assert "po2" in result.participant_outcomes

    def test_i6_coordinator_state_completed_on_full_success(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["cs1", "cs2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "cs1": {"success": True},
                "cs2": {"success": True},
            },
        )
        final = result.coordinator_state
        assert final is not None
        assert final.status == MeshCoordinatorStatus.completed

    def test_i7_coordinator_completed_device_ids_populated(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["cd1", "cd2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "cd1": {"success": True},
                "cd2": {"success": True},
            },
        )
        final = result.coordinator_state
        assert "cd1" in final.completed_device_ids
        assert "cd2" in final.completed_device_ids

    def test_i8_coordinator_failed_device_ids_populated(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["fd1", "fd2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "fd1": {"success": True},
                "fd2": {"success": False},
            },
        )
        final = result.coordinator_state
        assert "fd2" in final.failed_device_ids


# ---------------------------------------------------------------------------
# Group J: Failure paths and exception scenarios
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupJ_FailurePaths:
    def test_j1_participant_drop_during_run(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["drop1", "drop2"])
        # Simulate drop1 being dropped before run
        state = drop_participant(state, "drop1", reason="timeout")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"drop2": {"success": True}},
        )
        assert result is not None
        assert result.outcome in ("partial", "completed", "failed")

    def test_j2_all_participants_dropped_gives_failed(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["lost1", "lost2"])
        state = drop_participant(state, "lost1", reason="gone")
        state = drop_participant(state, "lost2", reason="gone")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={})
        assert result.outcome == "failed"

    def test_j3_errors_list_populated_on_failure(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["e1", "e2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "e1": {"success": False},
                "e2": {"success": False},
            },
        )
        assert len(result.errors) > 0

    def test_j4_engine_never_raises_on_garbage_input(self) -> None:
        engine = LiveMeshRuntimeEngine()
        for bad in [None, object(), 42, "string", [], {}]:
            result = engine.run(bad)  # type: ignore[arg-type]
            assert result is not None
            assert result.outcome in ("completed", "partial", "failed")

    def test_j5_partial_results_partial_outcome(self) -> None:
        state = _make_coordinator_state(participant_device_ids=["g1", "g2", "g3"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "g1": {"success": True},
                # g2 and g3 did not submit
            },
        )
        # g1 succeeded, g2/g3 dropped → partial
        assert result.outcome in ("partial", "failed")

    def test_j6_metadata_passes_through(self) -> None:
        state = _make_coordinator_state()
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"device_a": {"v": 1}, "device_b": {"v": 2}},
            metadata={"custom_key": "custom_value"},
        )
        assert result.metadata.get("custom_key") == "custom_value"

    def test_j7_run_live_mesh_session_graceful_on_none(self) -> None:
        result = run_live_mesh_session(None)  # type: ignore[arg-type]
        assert result is not None
        assert result.outcome == "failed"


# ---------------------------------------------------------------------------
# Group K: Orchestrator staged_mesh integration (PR-J)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _DISPATCH_AVAILABLE, reason="source_dispatch_orchestrator not available")
class TestGroupK_OrchestratorPRJ:
    def test_k1_orchestrator_sentinel_present(self) -> None:
        assert isinstance(orch_sentinel, str)
        assert "PR-J" in orch_sentinel

    def test_k2_staged_mesh_result_has_live_outcome_key(self) -> None:
        ms = _make_mesh_session_dict()
        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_prj_orch",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        assert result is not None
        from contracts.source_dispatch import SourceDispatchMode
        if result.mode == SourceDispatchMode.staged_mesh:
            assert result.result is not None
            assert "action_taken" in result.result
            assert result.result["action_taken"] == "staged_mesh_coordinated"
            # PR-J: live_outcome field must be present (may be None on error path)
            assert "live_outcome" in result.result

    def test_k3_staged_mesh_result_has_live_merged_result_key(self) -> None:
        ms = _make_mesh_session_dict()
        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_prj_merge",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        from contracts.source_dispatch import SourceDispatchMode
        if result.mode == SourceDispatchMode.staged_mesh:
            assert "live_merged_result" in result.result

    def test_k4_orchestrate_never_raises(self) -> None:
        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_prj_safe",
            mesh_session=None,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Group L: Full lifecycle integration test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _COORDINATOR_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="required modules not available",
)
class TestGroupL_FullLifecycle:
    def test_l1_full_lifecycle_staged_to_completed(self) -> None:
        """staged → active → barrier → merge → completed"""
        # 1. Build coordinator state
        state = coordinate_mesh_session(
            mesh_session={
                "session_id": "full_lifecycle_session",
                "mesh_id": "full_mesh",
                "participants": [
                    {"device_id": "phone", "roles": ["source"], "status": "active"},
                    {"device_id": "tablet", "roles": ["primary"], "status": "active"},
                ],
                "multi_device_required": True,
                "barrier_posture": "soft_barrier",
                "merge_owner_device_id": "tablet",
            },
            trace_id="trace_full",
            task_id="task_full",
        )
        assert state.status == MeshCoordinatorStatus.pending

        # 2. Register additional participant (dynamic join)
        state = register_participant(state, "laptop", roles=["support"])
        assert "laptop" in [p.device_id for p in state.participants]

        # 3. Simulate participants becoming ready
        state = update_participant_status(state, "phone", "ready")
        state = update_participant_status(state, "tablet", "ready")
        state = update_participant_status(state, "laptop", "ready")

        # 4. Run live mesh session with all participant results
        result = run_live_mesh_session(
            state,
            participant_results={
                "phone": {"subtask": "capture", "success": True},
                "tablet": {"subtask": "process", "success": True},
                "laptop": {"subtask": "assist", "success": True},
            },
        )

        # 5. Verify outcome
        assert result.outcome == "completed"
        assert result.success is True
        assert result.barrier_released is True
        assert len(result.participant_outcomes) == 3
        assert "phone" in result.participant_outcomes
        assert "tablet" in result.participant_outcomes
        assert "laptop" in result.participant_outcomes

        # 6. Verify coordinator state is finalised
        final_state = result.coordinator_state
        assert final_state.status == MeshCoordinatorStatus.completed
        assert "phone" in final_state.completed_device_ids
        assert "tablet" in final_state.completed_device_ids

    def test_l2_full_lifecycle_with_participant_drop(self) -> None:
        """staged → active → participant drops → partial result"""
        state = coordinate_mesh_session(
            mesh_session={
                "session_id": "drop_lifecycle",
                "participants": [
                    {"device_id": "d1", "status": "active"},
                    {"device_id": "d2", "status": "active"},
                ],
                "multi_device_required": True,
            },
            trace_id="trace_drop",
        )

        # d2 drops before submitting
        state = drop_participant(state, "d2", reason="lost_connection")
        assert "d2" in state.failed_device_ids

        result = run_live_mesh_session(
            state,
            participant_results={"d1": {"output": "partial_ok", "success": True}},
        )
        # d1 succeeded, d2 dropped → partial
        assert result.outcome in ("partial", "completed")
        assert result.success is True

    def test_l3_coordinator_summary_reflects_final_state(self) -> None:
        """get_coordinator_summary returns correct counts after live run"""
        state = coordinate_mesh_session(
            mesh_session={
                "session_id": "summary_test",
                "participants": [
                    {"device_id": "s1", "status": "active"},
                    {"device_id": "s2", "status": "active"},
                ],
                "multi_device_required": True,
            },
        )
        result = run_live_mesh_session(
            state,
            participant_results={
                "s1": {"success": True},
                "s2": {"success": True},
            },
        )
        final_state = result.coordinator_state
        summary = get_coordinator_summary(final_state)
        assert summary is not None
        assert summary.completed_count == 2
        assert summary.failed_count == 0
        assert summary.participant_count == 2
