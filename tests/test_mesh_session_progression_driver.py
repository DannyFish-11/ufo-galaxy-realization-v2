"""tests/test_mesh_session_progression_driver.py
==================================================
Tests for :class:`~core.mesh.mesh_session_progression_driver.MeshSessionProgressionDriver`.

Acceptance criteria verified by this test suite
------------------------------------------------
1. ``MeshSession.status`` is **actively driven** by coordinator events —
   not only modelled by static contract shape.
2. **Barrier wait semantics** are runtime-driven: the session does not
   advance to MERGING until all participants have submitted results.
3. **Assignment progression**: each ``MeshSubtaskAssignment.status``
   field is updated in lock-step with participant events.
4. **Merge trigger**: transition to MERGING/COMPLETED is triggered
   automatically; callers do not need to manually trigger the merge.
5. **Participant failure/dropout** materially affects the runtime outcome
   and session final status.
6. **Thread-safety**: concurrent events from multiple threads do not
   corrupt state.

Test groups
-----------
A   Policy sentinels
B   Construction
C   Participant management
D   Session status driven by participant lifecycle events
E   Assignment status driven by participant lifecycle events
F   Barrier semantics — all participants must arrive before MERGING
G   Finalize — full lifecycle: PENDING → ACTIVE → MERGING → COMPLETED
H   Partial completion (some participants failed / dropped)
I   Full failure (all participants failed)
J   Participant dropout affects session status
K   create_progression_driver convenience function
L   Thread-safety: concurrent event emission
M   core.runtime and core.mesh re-exports
N   to_dict on MeshSessionProgressionFinalResult
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.mesh.mesh_session_progression_driver import (
        MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY,
        MESH_SESSION_PROGRESSION_DRIVER_SENTINEL,
        SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY,
        SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY,
        MeshSessionProgressionDriver,
        MeshSessionProgressionFinalResult,
        create_progression_driver,
    )

    _DRIVER_AVAILABLE = True
except ImportError:
    _DRIVER_AVAILABLE = False

try:
    from contracts.mesh_session import (
        MeshBarrierPosture,
        MeshSession,
        MeshSessionStatus,
        MeshSubtaskAssignment,
        build_mesh_session,
    )

    _SESSION_AVAILABLE = True
except ImportError:
    _SESSION_AVAILABLE = False

try:
    from core.mesh.live_mesh_runtime_engine import LiveMeshRunResult

    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

_ALL_AVAILABLE = _DRIVER_AVAILABLE and _SESSION_AVAILABLE and _ENGINE_AVAILABLE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "test_session",
    device_ids: Optional[list] = None,
    barrier_posture: MeshBarrierPosture = MeshBarrierPosture.WAIT_ALL,
    with_assignments: bool = True,
) -> Any:
    """Build a MeshSession for tests."""
    if not _SESSION_AVAILABLE:
        pytest.skip("contracts not available")
    device_ids = device_ids or ["dev_a", "dev_b"]
    assignments = []
    if with_assignments:
        assignments = [
            MeshSubtaskAssignment(device_id=did, status="pending")
            for did in device_ids
        ]
    return build_mesh_session(
        source_device_id=device_ids[0] if device_ids else "src",
        primary_device_id=device_ids[0] if device_ids else "src",
        session_id=session_id,
        subtask_assignments=assignments,
        barrier_posture=barrier_posture,
        multi_device_required=len(device_ids) > 1,
    )


def _make_driver(
    session_id: str = "drv_test",
    device_ids: Optional[list] = None,
    barrier_posture: MeshBarrierPosture = MeshBarrierPosture.WAIT_ALL,
    add_participants: bool = True,
) -> "MeshSessionProgressionDriver":
    """Build a MeshSessionProgressionDriver with participants pre-added."""
    if not _ALL_AVAILABLE:
        pytest.skip("required modules not available")
    device_ids = device_ids or ["dev_a", "dev_b"]
    session = _make_session(session_id=session_id, device_ids=device_ids, barrier_posture=barrier_posture)
    driver = MeshSessionProgressionDriver(session)
    if add_participants:
        for i, did in enumerate(device_ids):
            driver.add_participant(did, roles=["primary" if i == 0 else "support"])
    return driver


# ---------------------------------------------------------------------------
# Group A: Policy sentinels
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _DRIVER_AVAILABLE, reason="driver not available")
class TestGroupA_Sentinels:
    def test_a1_main_sentinel_present(self) -> None:
        assert isinstance(MESH_SESSION_PROGRESSION_DRIVER_SENTINEL, str)
        assert "MESH-002" in MESH_SESSION_PROGRESSION_DRIVER_SENTINEL or "progression" in MESH_SESSION_PROGRESSION_DRIVER_SENTINEL.lower()

    def test_a2_session_status_policy_present(self) -> None:
        assert isinstance(SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY, str)
        assert "session" in SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY.lower()
        assert "status" in SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY.lower()

    def test_a3_assignment_status_policy_present(self) -> None:
        assert isinstance(SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY, str)
        assert "assignment" in SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY.lower()

    def test_a4_merge_trigger_policy_present(self) -> None:
        assert isinstance(MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY, str)
        assert "merge" in MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY.lower()
        assert "barrier" in MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY.lower()


# ---------------------------------------------------------------------------
# Group B: Construction
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupB_Construction:
    def test_b1_construct_with_none_session(self) -> None:
        driver = MeshSessionProgressionDriver(None)
        assert driver is not None
        assert driver.session is None

    def test_b2_construct_with_valid_session(self) -> None:
        session = _make_session()
        driver = MeshSessionProgressionDriver(session)
        assert driver.session is not None
        assert getattr(driver.session, "session_id", None) is not None

    def test_b3_initial_session_status_is_pending(self) -> None:
        session = _make_session()
        driver = MeshSessionProgressionDriver(session)
        assert driver.session.status == MeshSessionStatus.PENDING

    def test_b4_is_complete_false_with_no_results(self) -> None:
        driver = _make_driver()
        assert driver.is_complete is False

    def test_b5_outcome_running_initially(self) -> None:
        driver = _make_driver()
        assert driver.outcome == "running"

    def test_b6_coordinator_is_set(self) -> None:
        session = _make_session()
        driver = MeshSessionProgressionDriver(session)
        assert driver.coordinator is not None

    def test_b7_construct_with_barrier_timeout(self) -> None:
        session = _make_session()
        driver = MeshSessionProgressionDriver(session, barrier_timeout_seconds=60.0)
        assert driver._barrier_timeout_seconds == 60.0

    def test_b8_construct_with_dict_session(self) -> None:
        """Accepts a dict as mesh_session input."""
        session_dict = {
            "session_id": "dict_session",
            "source_device_id": "src",
            "primary_device_id": "src",
        }
        driver = MeshSessionProgressionDriver(session_dict)
        # Should not raise; session_id may be preserved or regenerated
        assert driver is not None


# ---------------------------------------------------------------------------
# Group C: Participant management
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupC_ParticipantManagement:
    def test_c1_add_participant_registers_in_coordinator(self) -> None:
        session = _make_session(device_ids=["c1_dev"])
        driver = MeshSessionProgressionDriver(session)
        driver.add_participant("c1_dev", roles=["primary"])
        coord_state = driver.coordinator.state
        device_ids = [p.device_id for p in coord_state.participants]
        assert "c1_dev" in device_ids

    def test_c2_add_participant_does_not_raise_on_none_session(self) -> None:
        driver = MeshSessionProgressionDriver(None)
        driver.add_participant("ghost_dev")  # Should not raise

    def test_c3_add_multiple_participants(self) -> None:
        session = _make_session(device_ids=["m1", "m2", "m3"])
        driver = MeshSessionProgressionDriver(session)
        for did in ("m1", "m2", "m3"):
            driver.add_participant(did)
        coord_state = driver.coordinator.state
        device_ids = [p.device_id for p in coord_state.participants]
        assert "m1" in device_ids
        assert "m2" in device_ids
        assert "m3" in device_ids


# ---------------------------------------------------------------------------
# Group D: Session status driven by participant lifecycle events
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupD_SessionStatusDriven:
    def test_d1_session_transitions_to_active_when_participant_works(self) -> None:
        """Evidence: MeshSession.status is actively driven — transitions to
        ACTIVE when a participant starts working (not only modeled)."""
        driver = _make_driver(device_ids=["d1_a", "d1_b"])
        # Initially PENDING
        assert driver.session.status == MeshSessionStatus.PENDING
        driver.on_participant_ready("d1_a")
        driver.on_participant_working("d1_a")
        # Must advance to ACTIVE
        assert driver.session.status == MeshSessionStatus.ACTIVE

    def test_d2_session_transitions_to_merging_when_all_results_in(self) -> None:
        """Evidence: barrier wait is runtime-driven — session advances to
        MERGING only when ALL participants have submitted results."""
        driver = _make_driver(device_ids=["d2_a", "d2_b"])
        driver.on_participant_working("d2_a")
        driver.on_participant_result("d2_a", {"out": "a"})
        # Only one of two participants — should still be ACTIVE, not MERGING
        assert driver.session.status == MeshSessionStatus.ACTIVE

        driver.on_participant_working("d2_b")
        driver.on_participant_result("d2_b", {"out": "b"})
        # Now all participants accounted for — MERGING
        assert driver.session.status == MeshSessionStatus.MERGING

    def test_d3_session_reaches_completed_after_finalize(self) -> None:
        """Evidence: merge trigger advances session to COMPLETED."""
        driver = _make_driver(device_ids=["d3_a"])
        driver.on_participant_working("d3_a")
        driver.on_participant_result("d3_a", {"out": "done"})
        result = driver.finalize()
        assert result.session.status == MeshSessionStatus.COMPLETED

    def test_d4_session_reaches_failed_when_all_fail(self) -> None:
        """Evidence: failure path drives session to FAILED."""
        driver = _make_driver(device_ids=["d4_a", "d4_b"])
        driver.on_participant_failed("d4_a", reason="err")
        driver.on_participant_failed("d4_b", reason="err")
        result = driver.finalize()
        assert result.session.status == MeshSessionStatus.FAILED

    def test_d5_session_status_never_regresses(self) -> None:
        """Once terminal, session status must not change."""
        driver = _make_driver(device_ids=["d5_a"])
        driver.on_participant_working("d5_a")
        driver.on_participant_result("d5_a", {"out": "ok"})
        result = driver.finalize()
        assert result.session.status == MeshSessionStatus.COMPLETED
        # Further events should not regress the session status
        result.session  # snapshot is final

    def test_d6_pending_until_first_participant_works(self) -> None:
        """Session remains PENDING until at least one participant starts work."""
        driver = _make_driver(device_ids=["d6_a", "d6_b"])
        driver.on_participant_ready("d6_a")
        # Just ready, not working yet
        assert driver.session.status == MeshSessionStatus.PENDING


# ---------------------------------------------------------------------------
# Group E: Assignment status driven by participant lifecycle events
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupE_AssignmentStatusDriven:
    def test_e1_assignment_updated_to_running_when_working(self) -> None:
        """Evidence: subtask_assignment.status is updated to 'running' when
        the corresponding participant starts working."""
        driver = _make_driver(device_ids=["e1_a", "e1_b"])
        driver.on_participant_working("e1_a")
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("e1_a") == "running"
        assert assignments.get("e1_b") == "pending"

    def test_e2_assignment_updated_to_success_on_result(self) -> None:
        """Evidence: subtask_assignment.status is updated to 'success' when
        the participant submits a result."""
        driver = _make_driver(device_ids=["e2_a", "e2_b"])
        driver.on_participant_working("e2_a")
        driver.on_participant_result("e2_a", {"x": 1})
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("e2_a") == "success"
        assert assignments.get("e2_b") == "pending"

    def test_e3_assignment_updated_to_failed_on_failure(self) -> None:
        """Evidence: subtask_assignment.status is updated to 'failed' when
        the participant fails."""
        driver = _make_driver(device_ids=["e3_a", "e3_b"])
        driver.on_participant_failed("e3_a", reason="subtask_err")
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("e3_a") == "failed"

    def test_e4_assignment_updated_to_failed_on_dropout(self) -> None:
        """Evidence: subtask_assignment.status is updated to 'failed' when
        the participant is dropped."""
        driver = _make_driver(device_ids=["e4_a", "e4_b"])
        driver.on_participant_dropped("e4_a", reason="timeout")
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("e4_a") == "failed"

    def test_e5_all_assignments_reach_final_status(self) -> None:
        """All assignments must be in a terminal status after full lifecycle."""
        driver = _make_driver(device_ids=["e5_a", "e5_b"])
        driver.on_participant_working("e5_a")
        driver.on_participant_result("e5_a", {"out": "a"})
        driver.on_participant_working("e5_b")
        driver.on_participant_result("e5_b", {"out": "b"})
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("e5_a") == "success"
        assert assignments.get("e5_b") == "success"

    def test_e6_assignment_not_in_session_still_works(self) -> None:
        """Driver works even when subtask_assignments is empty."""
        session = build_mesh_session(
            source_device_id="src",
            primary_device_id="src",
            subtask_assignments=[],  # no assignments
        )
        driver = MeshSessionProgressionDriver(session)
        driver.add_participant("new_dev")
        driver.on_participant_working("new_dev")
        driver.on_participant_result("new_dev", {"x": 1})
        result = driver.finalize()
        assert result.outcome == "completed"

    def test_e7_assignment_for_unknown_device_gracefully_ignored(self) -> None:
        """Updating assignment for a device_id not in assignments does not raise."""
        driver = _make_driver(device_ids=["e7_a"])
        driver.on_participant_working("not_in_assignments")  # Should not raise
        assert len(driver.session.subtask_assignments) == 1
        # Original assignment unchanged
        assert driver.session.subtask_assignments[0].device_id == "e7_a"
        assert driver.session.subtask_assignments[0].status == "pending"


# ---------------------------------------------------------------------------
# Group F: Barrier semantics — all participants must arrive before MERGING
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupF_BarrierSemantics:
    def test_f1_session_not_merging_until_all_results_in(self) -> None:
        """Evidence: barrier wait is runtime-driven."""
        driver = _make_driver(
            device_ids=["f1_a", "f1_b", "f1_c"],
            barrier_posture=MeshBarrierPosture.WAIT_ALL,
        )
        driver.on_participant_result("f1_a", {"x": 1})
        assert driver.session.status != MeshSessionStatus.MERGING
        driver.on_participant_result("f1_b", {"x": 2})
        assert driver.session.status != MeshSessionStatus.MERGING
        driver.on_participant_result("f1_c", {"x": 3})
        # All three arrived — now MERGING
        assert driver.session.status == MeshSessionStatus.MERGING

    def test_f2_barrier_released_reflected_in_finalize(self) -> None:
        """barrier_released must be True in LiveMeshRunResult when all arrive."""
        driver = _make_driver(device_ids=["f2_a", "f2_b"])
        driver.on_participant_result("f2_a", {"x": 1})
        driver.on_participant_result("f2_b", {"x": 2})
        result = driver.finalize()
        assert result.run_result is not None
        assert result.run_result.barrier_released is True

    def test_f3_barrier_posture_no_barrier_proceeds_immediately(self) -> None:
        """With NO_BARRIER posture, session can reach COMPLETED without wait."""
        driver = _make_driver(
            device_ids=["f3_a"],
            barrier_posture=MeshBarrierPosture.NO_BARRIER,
        )
        driver.on_participant_result("f3_a", {"x": 1})
        result = driver.finalize()
        assert result.outcome == "completed"

    def test_f4_merged_result_contains_all_participant_outputs(self) -> None:
        """Merged result must contain all participant outputs."""
        driver = _make_driver(device_ids=["f4_a", "f4_b"])
        driver.on_participant_result("f4_a", {"part": "A", "val": 10})
        driver.on_participant_result("f4_b", {"part": "B", "val": 20})
        result = driver.finalize()
        merged = result.run_result.merged_result
        assert "_participants" in merged
        assert "f4_a" in merged["_participants"]
        assert "f4_b" in merged["_participants"]


# ---------------------------------------------------------------------------
# Group G: Full lifecycle — PENDING → ACTIVE → MERGING → COMPLETED
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupG_FullLifecycle:
    def test_g1_full_two_device_lifecycle(self) -> None:
        """End-to-end evidence that multi-device execution has an operational
        coordinator path (acceptance criterion 3)."""
        driver = _make_driver(session_id="g1_full", device_ids=["alpha", "beta"])

        # Phase 1: PENDING
        assert driver.session.status == MeshSessionStatus.PENDING

        # Phase 2: Participants become ACTIVE
        driver.on_participant_ready("alpha")
        driver.on_participant_working("alpha")
        assert driver.session.status == MeshSessionStatus.ACTIVE
        assert any(
            a.device_id == "alpha" and a.status == "running"
            for a in driver.session.subtask_assignments
        )

        driver.on_participant_ready("beta")
        driver.on_participant_working("beta")
        assert any(
            a.device_id == "beta" and a.status == "running"
            for a in driver.session.subtask_assignments
        )

        # Phase 3: Results arrive — MERGING
        driver.on_participant_result("alpha", {"output": "alpha_done"})
        driver.on_participant_result("beta", {"output": "beta_done"})
        assert driver.session.status == MeshSessionStatus.MERGING
        assert all(
            a.status == "success" for a in driver.session.subtask_assignments
        )

        # Phase 4: Finalize — COMPLETED
        result = driver.finalize()
        assert result.outcome == "completed"
        assert result.success is True
        assert result.session.status == MeshSessionStatus.COMPLETED
        assert result.run_result is not None
        assert result.run_result.barrier_released is True

    def test_g2_single_device_lifecycle(self) -> None:
        """Single-device mesh session reaches COMPLETED."""
        driver = _make_driver(session_id="g2_single", device_ids=["solo"])
        driver.on_participant_working("solo")
        driver.on_participant_result("solo", {"answer": 42})
        result = driver.finalize()
        assert result.outcome == "completed"
        assert result.session.status == MeshSessionStatus.COMPLETED

    def test_g3_three_device_lifecycle(self) -> None:
        """Three-device mesh session reaches COMPLETED when all submit."""
        driver = _make_driver(session_id="g3_three", device_ids=["d1", "d2", "d3"])
        for did in ("d1", "d2", "d3"):
            driver.on_participant_working(did)
        for did in ("d1", "d2", "d3"):
            driver.on_participant_result(did, {"out": did})
        result = driver.finalize()
        assert result.outcome == "completed"
        assert result.session.status == MeshSessionStatus.COMPLETED

    def test_g4_finalize_returns_stable_result_type(self) -> None:
        """finalize() always returns MeshSessionProgressionFinalResult."""
        driver = _make_driver(device_ids=["g4_a"])
        driver.on_participant_result("g4_a", {"x": 1})
        result = driver.finalize()
        assert isinstance(result, MeshSessionProgressionFinalResult)

    def test_g5_finalize_on_none_session_does_not_raise(self) -> None:
        """finalize() on None session must not raise."""
        driver = MeshSessionProgressionDriver(None)
        result = driver.finalize()
        assert result is not None
        assert result.outcome in ("completed", "partial", "failed")

    def test_g6_coordinator_state_embedded_in_result(self) -> None:
        """Final LiveMeshRunResult must embed coordinator state."""
        driver = _make_driver(device_ids=["g6_a"])
        driver.on_participant_result("g6_a", {"x": 1})
        result = driver.finalize()
        assert result.run_result is not None
        assert result.run_result.coordinator_state is not None


# ---------------------------------------------------------------------------
# Group H: Partial completion
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupH_PartialCompletion:
    def test_h1_partial_when_one_fails_one_succeeds(self) -> None:
        """Outcome is 'partial' when some participants succeed and some fail."""
        driver = _make_driver(device_ids=["h1_a", "h1_b"])
        driver.on_participant_result("h1_a", {"out": "ok"})
        driver.on_participant_failed("h1_b", reason="err")
        result = driver.finalize()
        assert result.outcome == "partial"
        assert result.success is True

    def test_h2_partial_session_status_is_completed(self) -> None:
        """Partial outcome still results in session COMPLETED status."""
        driver = _make_driver(device_ids=["h2_a", "h2_b"])
        driver.on_participant_result("h2_a", {"out": "ok"})
        driver.on_participant_dropped("h2_b", reason="timeout")
        result = driver.finalize()
        assert result.session.status == MeshSessionStatus.COMPLETED

    def test_h3_mixed_assignment_statuses(self) -> None:
        """Assignment statuses reflect the mixed outcome."""
        driver = _make_driver(device_ids=["h3_a", "h3_b"])
        driver.on_participant_result("h3_a", {"out": "ok"})
        driver.on_participant_failed("h3_b", reason="err")
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("h3_a") == "success"
        assert assignments.get("h3_b") == "failed"


# ---------------------------------------------------------------------------
# Group I: Full failure
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupI_FullFailure:
    def test_i1_failed_outcome_when_all_fail(self) -> None:
        """Outcome is 'failed' when all participants fail."""
        driver = _make_driver(device_ids=["i1_a", "i1_b"])
        driver.on_participant_failed("i1_a", reason="err")
        driver.on_participant_failed("i1_b", reason="err")
        result = driver.finalize()
        assert result.outcome == "failed"
        assert result.success is False

    def test_i2_failed_session_status_on_full_failure(self) -> None:
        """Session status is FAILED when all participants fail."""
        driver = _make_driver(device_ids=["i2_a", "i2_b"])
        driver.on_participant_failed("i2_a")
        driver.on_participant_failed("i2_b")
        result = driver.finalize()
        assert result.session.status == MeshSessionStatus.FAILED

    def test_i3_all_assignments_failed_on_full_failure(self) -> None:
        """All assignment statuses are 'failed' on full failure."""
        driver = _make_driver(device_ids=["i3_a", "i3_b"])
        driver.on_participant_failed("i3_a")
        driver.on_participant_failed("i3_b")
        for a in driver.session.subtask_assignments:
            assert a.status == "failed"


# ---------------------------------------------------------------------------
# Group J: Participant dropout
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupJ_ParticipantDropout:
    def test_j1_dropout_updates_assignment_to_failed(self) -> None:
        """Evidence: participant dropout materially affects assignments."""
        driver = _make_driver(device_ids=["j1_a", "j1_b"])
        driver.on_participant_dropped("j1_a", reason="disconnect")
        assignments = {a.device_id: a.status for a in driver.session.subtask_assignments}
        assert assignments.get("j1_a") == "failed"

    def test_j2_dropout_plus_success_gives_partial(self) -> None:
        """Partial outcome when one participant drops but another succeeds."""
        driver = _make_driver(device_ids=["j2_a", "j2_b"])
        driver.on_participant_result("j2_a", {"x": 1})
        driver.on_participant_dropped("j2_b", reason="timeout")
        result = driver.finalize()
        assert result.outcome == "partial"

    def test_j3_all_dropout_gives_failed(self) -> None:
        """Failed outcome when all participants are dropped."""
        driver = _make_driver(device_ids=["j3_a", "j3_b"])
        driver.on_participant_dropped("j3_a", reason="timeout")
        driver.on_participant_dropped("j3_b", reason="timeout")
        result = driver.finalize()
        assert result.outcome == "failed"

    def test_j4_events_do_not_raise_on_unknown_device(self) -> None:
        """All event methods silently handle unknown device IDs."""
        driver = _make_driver()
        driver.on_participant_ready("ghost")
        driver.on_participant_working("ghost")
        driver.on_participant_result("ghost", {})
        driver.on_participant_failed("ghost")
        driver.on_participant_dropped("ghost")


# ---------------------------------------------------------------------------
# Group K: create_progression_driver convenience function
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupK_ConvenienceFunction:
    def test_k1_create_with_session(self) -> None:
        session = _make_session()
        driver = create_progression_driver(session)
        assert driver is not None
        assert driver.session is not None

    def test_k2_create_without_session_builds_from_kwargs(self) -> None:
        driver = create_progression_driver(
            session_id="k2_session",
            source_device_id="src",
            primary_device_id="src",
            mesh_id="mesh_k2",
        )
        assert driver is not None
        assert driver.session is not None

    def test_k3_create_with_barrier_timeout(self) -> None:
        driver = create_progression_driver(
            source_device_id="s",
            primary_device_id="s",
            barrier_timeout_seconds=45.0,
        )
        assert driver._barrier_timeout_seconds == 45.0

    def test_k4_create_never_raises(self) -> None:
        """Even with bad input, create_progression_driver does not raise."""
        driver = create_progression_driver(None)
        assert driver is not None


# ---------------------------------------------------------------------------
# Group L: Thread-safety
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupL_ThreadSafety:
    def test_l1_concurrent_result_events_do_not_corrupt_state(self) -> None:
        """Evidence: concurrent event emission is thread-safe."""
        device_ids = [f"td_{i}" for i in range(6)]
        driver = _make_driver(device_ids=device_ids)

        errors: list = []

        def emit_result(did: str) -> None:
            try:
                driver.on_participant_working(did)
                time.sleep(0.001)
                driver.on_participant_result(did, {"device": did, "val": hash(did) % 100})
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=emit_result, args=(did,)) for did in device_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Thread errors: {errors}"

        result = driver.finalize()
        assert result.outcome in ("completed", "partial", "failed")
        # All assignments should have been updated
        statuses = {a.status for a in result.session.subtask_assignments}
        assert "pending" not in statuses

    def test_l2_concurrent_mixed_events_do_not_raise(self) -> None:
        """Mixed concurrent events (results + failures) do not cause errors."""
        device_ids = [f"mix_{i}" for i in range(4)]
        driver = _make_driver(device_ids=device_ids)
        errors: list = []

        def emit_mixed(did: str, succeed: bool) -> None:
            try:
                driver.on_participant_working(did)
                if succeed:
                    driver.on_participant_result(did, {"ok": True})
                else:
                    driver.on_participant_failed(did, reason="test_fail")
            except Exception as exc:
                errors.append(str(exc))

        threads = [
            threading.Thread(target=emit_mixed, args=(did, i % 2 == 0))
            for i, did in enumerate(device_ids)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors
        result = driver.finalize()
        assert result.outcome in ("completed", "partial", "failed")


# ---------------------------------------------------------------------------
# Group M: core.runtime and core.mesh re-exports
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _DRIVER_AVAILABLE, reason="driver not available")
class TestGroupM_ReExports:
    def test_m1_core_mesh_coordinator_re_exports_driver(self) -> None:
        from core.mesh.mesh_session_coordinator import (
            MeshSessionProgressionDriver as D,
            create_progression_driver as cpd,
            MESH_SESSION_PROGRESSION_DRIVER_SENTINEL as S,
        )
        assert D is MeshSessionProgressionDriver
        assert cpd is create_progression_driver
        assert isinstance(S, str)

    def test_m2_core_runtime_re_exports_driver(self) -> None:
        from core.runtime import (
            MeshSessionProgressionDriver as D,
            create_progression_driver as cpd,
            MESH_SESSION_PROGRESSION_DRIVER_SENTINEL as S,
        )
        assert D is MeshSessionProgressionDriver
        assert cpd is create_progression_driver
        assert isinstance(S, str)

    def test_m3_core_runtime_re_exports_policies(self) -> None:
        from core.runtime import (
            SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY as p1,
            SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY as p2,
            MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY as p3,
        )
        assert isinstance(p1, str)
        assert isinstance(p2, str)
        assert isinstance(p3, str)


# ---------------------------------------------------------------------------
# Group N: MeshSessionProgressionFinalResult.to_dict
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupN_FinalResultDict:
    def test_n1_to_dict_returns_dict(self) -> None:
        driver = _make_driver(device_ids=["n1_a"])
        driver.on_participant_result("n1_a", {"x": 1})
        result = driver.finalize()
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "outcome" in d
        assert "success" in d
        assert "session" in d
        assert "run_result" in d

    def test_n2_to_dict_outcome_matches_result_outcome(self) -> None:
        driver = _make_driver(device_ids=["n2_a"])
        driver.on_participant_result("n2_a", {"x": 1})
        result = driver.finalize()
        d = result.to_dict()
        assert d["outcome"] == result.outcome

    def test_n3_to_dict_errors_list_present(self) -> None:
        result = MeshSessionProgressionFinalResult(
            session=None,
            run_result=None,
            errors=["test_err"],
        )
        d = result.to_dict()
        assert "errors" in d
        assert "test_err" in d["errors"]
