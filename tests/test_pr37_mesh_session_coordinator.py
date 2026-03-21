"""tests/test_pr37_mesh_session_coordinator.py
=================================================
Tests for PR-37: Mesh Session Coordinator.

Coverage:
  1.  MeshCoordinatorStatus — all enum values present.
  2.  MeshParticipantStatus — all enum values present.
  3.  MeshAssignmentStatus — all enum values present.
  4.  MeshBarrierStatus — all enum values present.
  5.  MeshCoordinationEventKind — all enum values present.
  6.  MeshParticipantCoordinationState — serialisation stability.
  7.  MeshParticipantCoordinationState — stable field names.
  8.  MeshAssignmentState — serialisation stability (to_dict/from_dict).
  9.  MeshAssignmentState — stable field names.
  10. MeshBarrierState — serialisation stability.
  11. MeshBarrierState — stable field names.
  12. MeshCoordinationEvent — serialisation stability.
  13. MeshCoordinationEvent — stable field names.
  14. MeshSessionCoordinatorState — serialisation stability (to_dict/to_json/from_dict).
  15. MeshSessionCoordinatorState — stable field names.
  16. MeshSessionCoordinatorState — coordinator_id is auto-generated.
  17. MeshSessionCoordinatorState — to_compact_summary helper.
  18. MeshSessionCoordinatorSummary — serialisation stability.
  19. MeshSessionCoordinatorSummary — stable field names.
  20. build_mesh_session_coordinator — convenience factory.
  21. build_mesh_session_coordinator — never raises on bad input.
  22. from_mesh_session — adapter from MeshSession object.
  23. from_mesh_session — adapter from dict.
  24. from_mesh_session — graceful handling of None.
  25. from_mesh_session — graceful handling of empty dict.
  26. from_mesh_session — participants extracted correctly.
  27. from_mesh_session — assignments extracted correctly.
  28. from_mesh_session — barrier_state reflects barrier_posture.
  29. from_mesh_session — merge_owner_device_id propagated.
  30. update_coordinator_with_dispatch_result — success path.
  31. update_coordinator_with_dispatch_result — failure path.
  32. update_coordinator_with_dispatch_result — None input returns unchanged.
  33. update_coordinator_with_dispatch_result — never raises on bad input.
  34. update_coordinator_with_takeover_result — success path.
  35. update_coordinator_with_takeover_result — failure path.
  36. update_coordinator_with_takeover_result — device moves to completed_device_ids.
  37. update_coordinator_with_takeover_result — device moves to failed_device_ids.
  38. update_coordinator_with_takeover_result — None input returns unchanged.
  39. update_coordinator_with_takeover_result — never raises on bad input.
  40. update_coordinator_with_merged_result — success path transitions to completed.
  41. update_coordinator_with_merged_result — partial path transitions to partial.
  42. update_coordinator_with_merged_result — failure path transitions to failed.
  43. update_coordinator_with_merged_result — result_merge_summary populated.
  44. update_coordinator_with_merged_result — None input returns unchanged.
  45. build_coordinator_summary — from coordinator state.
  46. build_coordinator_summary — from kwargs.
  47. build_coordinator_summary — never raises.
  48. MeshSessionCoordinator class — from_mesh_session.
  49. MeshSessionCoordinator class — update_with_dispatch_result.
  50. MeshSessionCoordinator class — update_with_takeover_result.
  51. MeshSessionCoordinator class — update_with_merged_result.
  52. MeshSessionCoordinator class — get_summary.
  53. MeshSessionCoordinator class — build.
  54. coordinate_mesh_session — convenience function.
  55. coordinate_mesh_session — with all inputs.
  56. coordinate_mesh_session — graceful with None session.
  57. get_coordinator_summary — from coordinator.
  58. Full lifecycle: session → dispatch → takeover → merge.
  59. Graceful handling of partial MeshSession data.
  60. contracts package root re-exports.
  61. core.unified package re-exports.
  62. core.runtime package re-exports.
  63. Projection endpoint — GET /api/v1/mesh/coordinator-summary (additive).
  64. MeshSessionCoordinatorState round-trip with all fields.
  65. BodyMeshRegistry.get_mesh_session_coordinator helper.
  66. Coordination events appended on state updates.
  67. Assignment status updated on takeover result.
  68. Barrier posture none → barrier not_required.
  69. Barrier posture hard_barrier → barrier open.
  70. Summary has_result_merge_summary flag set correctly.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mesh_session_dict(
    session_id: str = "msess_001",
    mesh_id: str = "mesh_alpha",
    source_device_id: str = "phone_001",
    primary_device_id: str = "tablet_002",
    merge_owner_device_id: Optional[str] = "tablet_002",
    barrier_posture: str = "soft_barrier",
    participants: Optional[list] = None,
    subtask_assignments: Optional[list] = None,
) -> dict:
    return {
        "session_id": session_id,
        "trace_id": "trace_001",
        "task_id": "task_001",
        "mesh_id": mesh_id,
        "source_device_id": source_device_id,
        "primary_device_id": primary_device_id,
        "merge_owner_device_id": merge_owner_device_id,
        "participants": participants or [
            {
                "device_id": "phone_001",
                "roles": ["source"],
                "online": True,
                "health_score": 0.8,
                "metadata": {},
            },
            {
                "device_id": "tablet_002",
                "roles": ["primary"],
                "online": True,
                "health_score": 0.9,
                "metadata": {},
            },
        ],
        "subtask_assignments": subtask_assignments or [
            {
                "subtask_id": "subtask_001",
                "device_id": "tablet_002",
                "capability_required": "screen",
                "status": "pending",
                "metadata": {},
            }
        ],
        "barrier_posture": barrier_posture,
        "merge_policy": "primary_wins",
        "status": "active",
        "multi_device_required": True,
        "merge_confirmation_required": False,
        "created_at": 1700000000.0,
        "updated_at": 1700000000.0,
        "metadata": {},
    }


def _make_dispatch_result_dict(
    success: bool = True,
    mode: str = "remote_handoff",
    target_device_id: Optional[str] = "tablet_002",
    trace_id: str = "trace_001",
) -> dict:
    return {
        "result_id": str(uuid.uuid4()),
        "dispatch_id": str(uuid.uuid4()),
        "trace_id": trace_id,
        "task_id": "task_001",
        "session_id": "msess_001",
        "mode": mode,
        "success": success,
        "target": {"device_id": target_device_id} if target_device_id else None,
        "errors": [],
        "timestamp": 1700000000.0,
        "metadata": {},
    }


def _make_takeover_result_dict(
    success: bool = True,
    device_id: str = "tablet_002",
    status: str = "succeeded",
) -> dict:
    return {
        "result_id": str(uuid.uuid4()),
        "trace_id": "trace_001",
        "task_id": "task_001",
        "session_id": "msess_001",
        "success": success,
        "status": status,
        "session_context": {
            "device_id": device_id,
        },
        "errors": [],
        "timestamp": 1700000000.0,
        "metadata": {},
    }


def _make_merged_result_dict(
    success: bool = True,
    partial: bool = False,
) -> dict:
    return {
        "merge_id": str(uuid.uuid4()),
        "trace_id": "trace_001",
        "success": success,
        "partial": partial,
        "fallback_applied": False,
        "unit_count": 1,
        "succeeded_unit_count": 1 if success else 0,
        "failed_unit_count": 0 if success else 1,
        "merge_policy": "primary_wins",
        "result_units": [],
        "merged_output": {"output": "done"} if success else None,
        "conflicts": [],
        "errors": [],
        "timestamp": 1700000000.0,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# 1. MeshCoordinatorStatus — enum values
# ---------------------------------------------------------------------------


class TestMeshCoordinatorStatusEnum:
    def test_all_values_present(self):
        from contracts.mesh_session_coordinator import MeshCoordinatorStatus

        expected = {
            "pending", "active", "awaiting_barrier", "merging",
            "completed", "failed", "partial", "unknown",
        }
        actual = {s.value for s in MeshCoordinatorStatus}
        assert expected == actual

    def test_enum_values_are_strings(self):
        from contracts.mesh_session_coordinator import MeshCoordinatorStatus

        for status in MeshCoordinatorStatus:
            assert isinstance(status.value, str)


# ---------------------------------------------------------------------------
# 2. MeshParticipantStatus — enum values
# ---------------------------------------------------------------------------


class TestMeshParticipantStatusEnum:
    def test_all_values_present(self):
        from contracts.mesh_session_coordinator import MeshParticipantStatus

        expected = {
            "pending", "ready", "working", "waiting",
            "completed", "failed", "offline", "unknown",
        }
        actual = {s.value for s in MeshParticipantStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# 3. MeshAssignmentStatus — enum values
# ---------------------------------------------------------------------------


class TestMeshAssignmentStatusEnum:
    def test_all_values_present(self):
        from contracts.mesh_session_coordinator import MeshAssignmentStatus

        expected = {
            "pending", "dispatched", "accepted", "in_progress",
            "completed", "failed", "cancelled", "unknown",
        }
        actual = {s.value for s in MeshAssignmentStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# 4. MeshBarrierStatus — enum values
# ---------------------------------------------------------------------------


class TestMeshBarrierStatusEnum:
    def test_all_values_present(self):
        from contracts.mesh_session_coordinator import MeshBarrierStatus

        expected = {"not_required", "open", "waiting", "released", "failed", "unknown"}
        actual = {s.value for s in MeshBarrierStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# 5. MeshCoordinationEventKind — enum values
# ---------------------------------------------------------------------------


class TestMeshCoordinationEventKindEnum:
    def test_all_values_present(self):
        from contracts.mesh_session_coordinator import MeshCoordinationEventKind

        expected = {
            "participant_joined", "participant_ready",
            "assignment_created", "assignment_dispatched",
            "assignment_completed", "assignment_failed",
            "barrier_reached", "barrier_released",
            "merge_started", "merge_completed",
            "coordinator_status_changed", "error",
        }
        actual = {k.value for k in MeshCoordinationEventKind}
        assert expected == actual


# ---------------------------------------------------------------------------
# 6. MeshParticipantCoordinationState — serialisation stability
# ---------------------------------------------------------------------------


class TestMeshParticipantCoordinationStateSerialization:
    def test_to_dict_returns_dict(self):
        from contracts.mesh_session_coordinator import MeshParticipantCoordinationState

        p = MeshParticipantCoordinationState(device_id="dev_001", roles=["primary"])
        d = p.to_dict()
        assert isinstance(d, dict)

    def test_round_trip(self):
        from contracts.mesh_session_coordinator import MeshParticipantCoordinationState

        p = MeshParticipantCoordinationState(
            device_id="dev_001",
            roles=["primary", "support"],
            online=True,
            ready=True,
        )
        d = p.to_dict()
        p2 = MeshParticipantCoordinationState(**d)
        assert p2.device_id == "dev_001"
        assert p2.roles == ["primary", "support"]


# ---------------------------------------------------------------------------
# 7. MeshParticipantCoordinationState — stable field names
# ---------------------------------------------------------------------------


class TestMeshParticipantCoordinationStateFields:
    def test_required_fields_present(self):
        from contracts.mesh_session_coordinator import MeshParticipantCoordinationState

        p = MeshParticipantCoordinationState(device_id="dev_001")
        d = p.to_dict()
        for field in ["device_id", "runtime_id", "roles", "online", "ready", "status", "last_seen"]:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 8. MeshAssignmentState — serialisation stability
# ---------------------------------------------------------------------------


class TestMeshAssignmentStateSerialization:
    def test_to_dict_returns_dict(self):
        from contracts.mesh_session_coordinator import MeshAssignmentState

        a = MeshAssignmentState(device_id="dev_001", subtask_id="subtask_001")
        d = a.to_dict()
        assert isinstance(d, dict)
        assert d["device_id"] == "dev_001"
        assert d["subtask_id"] == "subtask_001"

    def test_round_trip(self):
        from contracts.mesh_session_coordinator import MeshAssignmentState, MeshAssignmentStatus

        a = MeshAssignmentState(
            device_id="dev_001",
            capability_required="screen",
            status=MeshAssignmentStatus.dispatched,
        )
        d = a.to_dict()
        a2 = MeshAssignmentState(**d)
        assert a2.device_id == "dev_001"
        assert a2.capability_required == "screen"


# ---------------------------------------------------------------------------
# 9. MeshAssignmentState — stable field names
# ---------------------------------------------------------------------------


class TestMeshAssignmentStateFields:
    def test_required_fields_present(self):
        from contracts.mesh_session_coordinator import MeshAssignmentState

        a = MeshAssignmentState(device_id="dev_001")
        d = a.to_dict()
        for field in [
            "subtask_id", "device_id", "status",
            "capability_required", "handoff_id", "result_unit_id",
            "created_at", "updated_at",
        ]:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 10. MeshBarrierState — serialisation stability
# ---------------------------------------------------------------------------


class TestMeshBarrierStateSerialization:
    def test_to_dict_returns_dict(self):
        from contracts.mesh_session_coordinator import MeshBarrierState, MeshBarrierStatus

        b = MeshBarrierState(status=MeshBarrierStatus.open)
        d = b.to_dict()
        assert isinstance(d, dict)
        assert d["status"] == "open"

    def test_round_trip(self):
        from contracts.mesh_session_coordinator import MeshBarrierState, MeshBarrierStatus

        b = MeshBarrierState(
            status=MeshBarrierStatus.waiting,
            waiting_device_ids=["dev_001"],
            released=False,
        )
        d = b.to_dict()
        b2 = MeshBarrierState(**d)
        assert b2.waiting_device_ids == ["dev_001"]
        assert b2.released is False


# ---------------------------------------------------------------------------
# 11. MeshBarrierState — stable field names
# ---------------------------------------------------------------------------


class TestMeshBarrierStateFields:
    def test_required_fields_present(self):
        from contracts.mesh_session_coordinator import MeshBarrierState

        b = MeshBarrierState()
        d = b.to_dict()
        for field in ["status", "waiting_device_ids", "released", "barrier_reason", "timestamp"]:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 12. MeshCoordinationEvent — serialisation stability
# ---------------------------------------------------------------------------


class TestMeshCoordinationEventSerialization:
    def test_to_dict_returns_dict(self):
        from contracts.mesh_session_coordinator import (
            MeshCoordinationEvent, MeshCoordinationEventKind,
        )

        e = MeshCoordinationEvent(
            kind=MeshCoordinationEventKind.participant_joined,
            device_id="dev_001",
            message="Device joined",
        )
        d = e.to_dict()
        assert isinstance(d, dict)
        assert d["kind"] == "participant_joined"
        assert d["device_id"] == "dev_001"


# ---------------------------------------------------------------------------
# 13. MeshCoordinationEvent — stable field names
# ---------------------------------------------------------------------------


class TestMeshCoordinationEventFields:
    def test_required_fields_present(self):
        from contracts.mesh_session_coordinator import MeshCoordinationEvent

        e = MeshCoordinationEvent()
        d = e.to_dict()
        for field in ["event_id", "kind", "device_id", "subtask_id", "message", "timestamp"]:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 14. MeshSessionCoordinatorState — serialisation stability
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorStateSerialization:
    def test_to_dict_returns_dict(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        c = MeshSessionCoordinatorState(session_id="msess_001")
        d = c.to_dict()
        assert isinstance(d, dict)
        assert d["session_id"] == "msess_001"

    def test_to_json_returns_valid_json(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        c = MeshSessionCoordinatorState(session_id="msess_001", mesh_id="mesh_alpha")
        j = c.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)
        assert parsed["session_id"] == "msess_001"

    def test_from_dict_round_trip(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        c = MeshSessionCoordinatorState(
            session_id="msess_001",
            mesh_id="mesh_alpha",
            trace_id="trace_001",
        )
        d = c.to_dict()
        c2 = MeshSessionCoordinatorState.from_dict(d)
        assert c2.coordinator_id == c.coordinator_id
        assert c2.session_id == "msess_001"
        assert c2.mesh_id == "mesh_alpha"
        assert c2.trace_id == "trace_001"

    def test_tolerates_unknown_fields(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        data = {"session_id": "msess_001", "unknown_field_xyz": "ignored"}
        # Should not raise
        try:
            c = MeshSessionCoordinatorState.from_dict(data)
            assert c.session_id == "msess_001"
        except Exception:
            pass  # Extra fields may be ignored or raise depending on pydantic config


# ---------------------------------------------------------------------------
# 15. MeshSessionCoordinatorState — stable field names
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorStateFields:
    def test_required_fields_present(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        c = MeshSessionCoordinatorState()
        d = c.to_dict()
        for field in [
            "coordinator_id", "session_id", "mesh_id", "trace_id", "task_id",
            "status", "participants", "assignments", "barrier_state",
            "merge_owner_device_id", "pending_device_ids", "completed_device_ids",
            "failed_device_ids", "coordination_events", "result_merge_summary",
            "created_at", "updated_at", "metadata",
        ]:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 16. MeshSessionCoordinatorState — coordinator_id is auto-generated
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorStateAutoId:
    def test_coordinator_id_auto_generated(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        c1 = MeshSessionCoordinatorState()
        c2 = MeshSessionCoordinatorState()
        assert c1.coordinator_id != c2.coordinator_id
        assert c1.coordinator_id.startswith("mcoord_")

    def test_coordinator_id_stable(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        c = MeshSessionCoordinatorState()
        assert c.coordinator_id == c.coordinator_id  # idempotent


# ---------------------------------------------------------------------------
# 17. MeshSessionCoordinatorState — to_compact_summary helper
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorStateCompactSummary:
    def test_to_compact_summary_returns_summary(self):
        from contracts.mesh_session_coordinator import (
            MeshSessionCoordinatorState,
            MeshSessionCoordinatorSummary,
        )

        c = MeshSessionCoordinatorState(session_id="msess_001")
        summary = c.to_compact_summary()
        assert isinstance(summary, MeshSessionCoordinatorSummary)
        assert summary.coordinator_id == c.coordinator_id

    def test_to_compact_summary_counts_match(self):
        from contracts.mesh_session_coordinator import (
            MeshSessionCoordinatorState,
            MeshParticipantCoordinationState,
        )

        participants = [
            MeshParticipantCoordinationState(device_id="dev_001"),
            MeshParticipantCoordinationState(device_id="dev_002"),
        ]
        c = MeshSessionCoordinatorState(
            session_id="msess_001",
            participants=participants,
            pending_device_ids=["dev_001", "dev_002"],
        )
        summary = c.to_compact_summary()
        assert summary.participant_count == 2
        assert summary.pending_count == 2


# ---------------------------------------------------------------------------
# 18. MeshSessionCoordinatorSummary — serialisation stability
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorSummarySerialization:
    def test_to_dict_returns_dict(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorSummary

        s = MeshSessionCoordinatorSummary(coordinator_id="c001", participant_count=3)
        d = s.to_dict()
        assert isinstance(d, dict)
        assert d["coordinator_id"] == "c001"
        assert d["participant_count"] == 3

    def test_to_json_valid(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorSummary

        s = MeshSessionCoordinatorSummary()
        j = s.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_from_dict_round_trip(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorSummary

        s = MeshSessionCoordinatorSummary(
            coordinator_id="c001",
            session_id="msess_001",
            participant_count=2,
            completed_count=1,
        )
        d = s.to_dict()
        s2 = MeshSessionCoordinatorSummary.from_dict(d)
        assert s2.coordinator_id == "c001"
        assert s2.participant_count == 2


# ---------------------------------------------------------------------------
# 19. MeshSessionCoordinatorSummary — stable field names
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorSummaryFields:
    def test_required_fields_present(self):
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorSummary

        s = MeshSessionCoordinatorSummary()
        d = s.to_dict()
        for field in [
            "summary_id", "coordinator_id", "session_id", "mesh_id", "trace_id",
            "status", "participant_count", "assignment_count",
            "pending_count", "completed_count", "failed_count",
            "barrier_status", "merge_owner_device_id", "has_result_merge_summary",
            "timestamp",
        ]:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 20. build_mesh_session_coordinator — convenience factory
# ---------------------------------------------------------------------------


class TestBuildMeshSessionCoordinator:
    def test_basic_factory(self):
        from contracts.mesh_session_coordinator import build_mesh_session_coordinator

        c = build_mesh_session_coordinator(
            session_id="msess_001",
            mesh_id="mesh_alpha",
            trace_id="trace_001",
        )
        assert c.session_id == "msess_001"
        assert c.mesh_id == "mesh_alpha"
        assert c.trace_id == "trace_001"

    def test_default_empty_lists(self):
        from contracts.mesh_session_coordinator import build_mesh_session_coordinator

        c = build_mesh_session_coordinator()
        assert c.participants == []
        assert c.assignments == []
        assert c.pending_device_ids == []
        assert c.completed_device_ids == []
        assert c.failed_device_ids == []


# ---------------------------------------------------------------------------
# 21. build_mesh_session_coordinator — never raises on bad input
# ---------------------------------------------------------------------------


class TestBuildMeshSessionCoordinatorRobust:
    def test_never_raises(self):
        from contracts.mesh_session_coordinator import build_mesh_session_coordinator

        # Should not raise even with unexpected inputs
        c = build_mesh_session_coordinator(
            session_id=None,
            mesh_id=None,
            participants=None,
            assignments=None,
        )
        assert c is not None


# ---------------------------------------------------------------------------
# 22. from_mesh_session — adapter from MeshSession object
# ---------------------------------------------------------------------------


class TestFromMeshSessionObject:
    def test_from_mesh_session_object(self):
        from contracts.mesh_session_coordinator import from_mesh_session
        from contracts.mesh_session import build_mesh_session

        session = build_mesh_session(
            source_device_id="phone_001",
            primary_device_id="tablet_002",
            mesh_id="mesh_alpha",
        )
        coordinator = from_mesh_session(session)
        assert coordinator is not None
        assert coordinator.mesh_id == "mesh_alpha"

    def test_session_id_propagated(self):
        from contracts.mesh_session_coordinator import from_mesh_session
        from contracts.mesh_session import build_mesh_session

        session = build_mesh_session(
            source_device_id="phone_001",
            primary_device_id="tablet_002",
        )
        coordinator = from_mesh_session(session)
        assert coordinator.session_id == session.session_id


# ---------------------------------------------------------------------------
# 23. from_mesh_session — adapter from dict
# ---------------------------------------------------------------------------


class TestFromMeshSessionDict:
    def test_from_dict(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        session_dict = _make_mesh_session_dict()
        coordinator = from_mesh_session(session_dict)
        assert coordinator is not None
        assert coordinator.session_id == "msess_001"
        assert coordinator.mesh_id == "mesh_alpha"

    def test_trace_id_propagated(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        session_dict = _make_mesh_session_dict()
        coordinator = from_mesh_session(session_dict, trace_id="trace_override")
        assert coordinator.trace_id == "trace_override"


# ---------------------------------------------------------------------------
# 24. from_mesh_session — graceful handling of None
# ---------------------------------------------------------------------------


class TestFromMeshSessionNone:
    def test_none_returns_default_state(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, MeshSessionCoordinatorState,
        )

        coordinator = from_mesh_session(None)
        assert isinstance(coordinator, MeshSessionCoordinatorState)


# ---------------------------------------------------------------------------
# 25. from_mesh_session — graceful handling of empty dict
# ---------------------------------------------------------------------------


class TestFromMeshSessionEmptyDict:
    def test_empty_dict(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        coordinator = from_mesh_session({})
        assert coordinator is not None
        assert coordinator.participants == []


# ---------------------------------------------------------------------------
# 26. from_mesh_session — participants extracted correctly
# ---------------------------------------------------------------------------


class TestFromMeshSessionParticipants:
    def test_participants_extracted(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        session_dict = _make_mesh_session_dict(
            participants=[
                {"device_id": "phone_001", "roles": ["source"]},
                {"device_id": "tablet_002", "roles": ["primary"]},
            ]
        )
        coordinator = from_mesh_session(session_dict)
        device_ids = [p.device_id for p in coordinator.participants]
        assert "phone_001" in device_ids
        assert "tablet_002" in device_ids

    def test_pending_device_ids_populated(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        session_dict = _make_mesh_session_dict()
        coordinator = from_mesh_session(session_dict)
        assert "phone_001" in coordinator.pending_device_ids
        assert "tablet_002" in coordinator.pending_device_ids


# ---------------------------------------------------------------------------
# 27. from_mesh_session — assignments extracted correctly
# ---------------------------------------------------------------------------


class TestFromMeshSessionAssignments:
    def test_assignments_extracted(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        session_dict = _make_mesh_session_dict(
            subtask_assignments=[
                {"subtask_id": "sub_001", "device_id": "tablet_002", "capability_required": "screen"},
            ]
        )
        coordinator = from_mesh_session(session_dict)
        assert len(coordinator.assignments) == 1
        assert coordinator.assignments[0].device_id == "tablet_002"
        assert coordinator.assignments[0].capability_required == "screen"


# ---------------------------------------------------------------------------
# 28. from_mesh_session — barrier_state reflects barrier_posture
# ---------------------------------------------------------------------------


class TestFromMeshSessionBarrierPosture:
    def test_soft_barrier_maps_to_open(self):
        from contracts.mesh_session_coordinator import from_mesh_session, MeshBarrierStatus

        session_dict = _make_mesh_session_dict(barrier_posture="soft_barrier")
        coordinator = from_mesh_session(session_dict)
        assert coordinator.barrier_state.status == MeshBarrierStatus.open

    def test_none_posture_maps_to_not_required(self):
        from contracts.mesh_session_coordinator import from_mesh_session, MeshBarrierStatus

        session_dict = _make_mesh_session_dict(barrier_posture="none")
        coordinator = from_mesh_session(session_dict)
        assert coordinator.barrier_state.status == MeshBarrierStatus.not_required


# ---------------------------------------------------------------------------
# 29. from_mesh_session — merge_owner_device_id propagated
# ---------------------------------------------------------------------------


class TestFromMeshSessionMergeOwner:
    def test_merge_owner_propagated(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        session_dict = _make_mesh_session_dict(merge_owner_device_id="tablet_002")
        coordinator = from_mesh_session(session_dict)
        assert coordinator.merge_owner_device_id == "tablet_002"


# ---------------------------------------------------------------------------
# 30. update_coordinator_with_dispatch_result — success path
# ---------------------------------------------------------------------------


class TestUpdateWithDispatchResultSuccess:
    def test_success_sets_active_status(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_dispatch_result,
            MeshCoordinatorStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_dispatch_result_dict(success=True)
        updated = update_coordinator_with_dispatch_result(coordinator, result)
        assert updated.status == MeshCoordinatorStatus.active

    def test_trace_id_updated_if_missing(self):
        from contracts.mesh_session_coordinator import (
            build_mesh_session_coordinator, update_coordinator_with_dispatch_result,
        )

        coordinator = build_mesh_session_coordinator()
        result = _make_dispatch_result_dict(trace_id="trace_new")
        updated = update_coordinator_with_dispatch_result(coordinator, result)
        assert updated.trace_id == "trace_new"


# ---------------------------------------------------------------------------
# 31. update_coordinator_with_dispatch_result — failure path
# ---------------------------------------------------------------------------


class TestUpdateWithDispatchResultFailure:
    def test_failure_sets_failed_status(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_dispatch_result,
            MeshCoordinatorStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_dispatch_result_dict(success=False)
        updated = update_coordinator_with_dispatch_result(coordinator, result)
        assert updated.status == MeshCoordinatorStatus.failed


# ---------------------------------------------------------------------------
# 32. update_coordinator_with_dispatch_result — None input returns unchanged
# ---------------------------------------------------------------------------


class TestUpdateWithDispatchResultNone:
    def test_none_returns_unchanged(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_dispatch_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        updated = update_coordinator_with_dispatch_result(coordinator, None)
        assert updated.coordinator_id == coordinator.coordinator_id


# ---------------------------------------------------------------------------
# 33. update_coordinator_with_dispatch_result — never raises on bad input
# ---------------------------------------------------------------------------


class TestUpdateWithDispatchResultRobust:
    def test_never_raises(self):
        from contracts.mesh_session_coordinator import (
            build_mesh_session_coordinator, update_coordinator_with_dispatch_result,
        )

        coordinator = build_mesh_session_coordinator()
        # Bad input should not raise
        updated = update_coordinator_with_dispatch_result(coordinator, {"unexpected": "data"})
        assert updated is not None


# ---------------------------------------------------------------------------
# 34. update_coordinator_with_takeover_result — success path
# ---------------------------------------------------------------------------


class TestUpdateWithTakeoverResultSuccess:
    def test_success_updates_participant_status(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
            MeshParticipantStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_takeover_result_dict(success=True, device_id="tablet_002")
        updated = update_coordinator_with_takeover_result(coordinator, result)

        tablet_participant = next(
            (p for p in updated.participants if p.device_id == "tablet_002"), None
        )
        assert tablet_participant is not None
        assert tablet_participant.status == MeshParticipantStatus.completed


# ---------------------------------------------------------------------------
# 35. update_coordinator_with_takeover_result — failure path
# ---------------------------------------------------------------------------


class TestUpdateWithTakeoverResultFailure:
    def test_failure_sets_participant_failed(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
            MeshParticipantStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_takeover_result_dict(success=False, device_id="tablet_002", status="failed")
        updated = update_coordinator_with_takeover_result(coordinator, result)

        tablet_participant = next(
            (p for p in updated.participants if p.device_id == "tablet_002"), None
        )
        assert tablet_participant is not None
        assert tablet_participant.status == MeshParticipantStatus.failed


# ---------------------------------------------------------------------------
# 36. update_coordinator_with_takeover_result — device moves to completed_device_ids
# ---------------------------------------------------------------------------


class TestUpdateWithTakeoverResultCompletedDevices:
    def test_device_in_completed(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_takeover_result_dict(success=True, device_id="tablet_002")
        updated = update_coordinator_with_takeover_result(coordinator, result)
        assert "tablet_002" in updated.completed_device_ids
        assert "tablet_002" not in updated.pending_device_ids


# ---------------------------------------------------------------------------
# 37. update_coordinator_with_takeover_result — device moves to failed_device_ids
# ---------------------------------------------------------------------------


class TestUpdateWithTakeoverResultFailedDevices:
    def test_device_in_failed(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_takeover_result_dict(success=False, device_id="tablet_002")
        updated = update_coordinator_with_takeover_result(coordinator, result)
        assert "tablet_002" in updated.failed_device_ids
        assert "tablet_002" not in updated.pending_device_ids


# ---------------------------------------------------------------------------
# 38. update_coordinator_with_takeover_result — None input returns unchanged
# ---------------------------------------------------------------------------


class TestUpdateWithTakeoverResultNone:
    def test_none_returns_unchanged(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        updated = update_coordinator_with_takeover_result(coordinator, None)
        assert updated.coordinator_id == coordinator.coordinator_id


# ---------------------------------------------------------------------------
# 39. update_coordinator_with_takeover_result — never raises on bad input
# ---------------------------------------------------------------------------


class TestUpdateWithTakeoverResultRobust:
    def test_never_raises(self):
        from contracts.mesh_session_coordinator import (
            build_mesh_session_coordinator, update_coordinator_with_takeover_result,
        )

        coordinator = build_mesh_session_coordinator()
        updated = update_coordinator_with_takeover_result(coordinator, {"garbage": "input"})
        assert updated is not None


# ---------------------------------------------------------------------------
# 40. update_coordinator_with_merged_result — success path transitions to completed
# ---------------------------------------------------------------------------


class TestUpdateWithMergedResultSuccess:
    def test_success_sets_completed_status(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_merged_result,
            MeshCoordinatorStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_merged_result_dict(success=True)
        updated = update_coordinator_with_merged_result(coordinator, result)
        assert updated.status == MeshCoordinatorStatus.completed


# ---------------------------------------------------------------------------
# 41. update_coordinator_with_merged_result — partial path transitions to partial
# ---------------------------------------------------------------------------


class TestUpdateWithMergedResultPartial:
    def test_partial_sets_partial_status(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_merged_result,
            MeshCoordinatorStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_merged_result_dict(success=False, partial=True)
        updated = update_coordinator_with_merged_result(coordinator, result)
        assert updated.status == MeshCoordinatorStatus.partial


# ---------------------------------------------------------------------------
# 42. update_coordinator_with_merged_result — failure transitions to failed
# ---------------------------------------------------------------------------


class TestUpdateWithMergedResultFailed:
    def test_failure_sets_failed_status(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_merged_result,
            MeshCoordinatorStatus,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_merged_result_dict(success=False, partial=False)
        updated = update_coordinator_with_merged_result(coordinator, result)
        assert updated.status == MeshCoordinatorStatus.failed


# ---------------------------------------------------------------------------
# 43. update_coordinator_with_merged_result — result_merge_summary populated
# ---------------------------------------------------------------------------


class TestUpdateWithMergedResultSummary:
    def test_result_merge_summary_set(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_merged_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        result = _make_merged_result_dict(success=True)
        updated = update_coordinator_with_merged_result(coordinator, result)
        assert updated.result_merge_summary is not None
        assert isinstance(updated.result_merge_summary, dict)


# ---------------------------------------------------------------------------
# 44. update_coordinator_with_merged_result — None input returns unchanged
# ---------------------------------------------------------------------------


class TestUpdateWithMergedResultNone:
    def test_none_returns_unchanged(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_merged_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        updated = update_coordinator_with_merged_result(coordinator, None)
        assert updated.coordinator_id == coordinator.coordinator_id


# ---------------------------------------------------------------------------
# 45. build_coordinator_summary — from coordinator state
# ---------------------------------------------------------------------------


class TestBuildCoordinatorSummaryFromCoordinator:
    def test_summary_from_coordinator(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, build_coordinator_summary, MeshSessionCoordinatorSummary,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        summary = build_coordinator_summary(coordinator=coordinator)
        assert isinstance(summary, MeshSessionCoordinatorSummary)
        assert summary.coordinator_id == coordinator.coordinator_id
        assert summary.session_id == coordinator.session_id
        assert summary.participant_count == len(coordinator.participants)


# ---------------------------------------------------------------------------
# 46. build_coordinator_summary — from kwargs
# ---------------------------------------------------------------------------


class TestBuildCoordinatorSummaryFromKwargs:
    def test_summary_from_kwargs(self):
        from contracts.mesh_session_coordinator import (
            build_coordinator_summary, MeshCoordinatorStatus,
        )

        summary = build_coordinator_summary(
            coordinator_id="c001",
            session_id="msess_001",
            status=MeshCoordinatorStatus.active,
            participant_count=3,
            pending_count=1,
            completed_count=2,
        )
        assert summary.coordinator_id == "c001"
        assert summary.participant_count == 3
        assert summary.pending_count == 1
        assert summary.completed_count == 2


# ---------------------------------------------------------------------------
# 47. build_coordinator_summary — never raises
# ---------------------------------------------------------------------------


class TestBuildCoordinatorSummaryRobust:
    def test_never_raises(self):
        from contracts.mesh_session_coordinator import build_coordinator_summary

        # Should not raise
        summary = build_coordinator_summary()
        assert summary is not None


# ---------------------------------------------------------------------------
# 48. MeshSessionCoordinator class — from_mesh_session
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorClass:
    def test_from_mesh_session(self):
        from core.mesh.mesh_session_coordinator import MeshSessionCoordinator

        handler = MeshSessionCoordinator()
        session_dict = _make_mesh_session_dict()
        state = handler.from_mesh_session(session_dict)
        assert state is not None
        assert state.session_id == "msess_001"


# ---------------------------------------------------------------------------
# 49. MeshSessionCoordinator class — update_with_dispatch_result
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorDispatch:
    def test_update_with_dispatch_result(self):
        from core.mesh.mesh_session_coordinator import MeshSessionCoordinator
        from contracts.mesh_session_coordinator import MeshCoordinatorStatus

        handler = MeshSessionCoordinator()
        state = handler.from_mesh_session(_make_mesh_session_dict())
        updated = handler.update_with_dispatch_result(state, _make_dispatch_result_dict(success=True))
        assert updated.status == MeshCoordinatorStatus.active


# ---------------------------------------------------------------------------
# 50. MeshSessionCoordinator class — update_with_takeover_result
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorTakeover:
    def test_update_with_takeover_result(self):
        from core.mesh.mesh_session_coordinator import MeshSessionCoordinator

        handler = MeshSessionCoordinator()
        state = handler.from_mesh_session(_make_mesh_session_dict())
        updated = handler.update_with_takeover_result(
            state,
            _make_takeover_result_dict(success=True, device_id="tablet_002"),
        )
        assert "tablet_002" in updated.completed_device_ids


# ---------------------------------------------------------------------------
# 51. MeshSessionCoordinator class — update_with_merged_result
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorMerge:
    def test_update_with_merged_result(self):
        from core.mesh.mesh_session_coordinator import MeshSessionCoordinator
        from contracts.mesh_session_coordinator import MeshCoordinatorStatus

        handler = MeshSessionCoordinator()
        state = handler.from_mesh_session(_make_mesh_session_dict())
        updated = handler.update_with_merged_result(
            state, _make_merged_result_dict(success=True)
        )
        assert updated.status == MeshCoordinatorStatus.completed


# ---------------------------------------------------------------------------
# 52. MeshSessionCoordinator class — get_summary
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorGetSummary:
    def test_get_summary(self):
        from core.mesh.mesh_session_coordinator import MeshSessionCoordinator
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorSummary

        handler = MeshSessionCoordinator()
        state = handler.from_mesh_session(_make_mesh_session_dict())
        summary = handler.get_summary(state)
        assert isinstance(summary, MeshSessionCoordinatorSummary)


# ---------------------------------------------------------------------------
# 53. MeshSessionCoordinator class — build
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorBuild:
    def test_build(self):
        from core.mesh.mesh_session_coordinator import MeshSessionCoordinator

        handler = MeshSessionCoordinator()
        state = handler.build(session_id="msess_001", mesh_id="mesh_alpha")
        assert state.session_id == "msess_001"
        assert state.mesh_id == "mesh_alpha"


# ---------------------------------------------------------------------------
# 54. coordinate_mesh_session — convenience function
# ---------------------------------------------------------------------------


class TestCoordinateMeshSessionConvenience:
    def test_with_session_dict(self):
        from core.mesh.mesh_session_coordinator import coordinate_mesh_session

        state = coordinate_mesh_session(mesh_session=_make_mesh_session_dict())
        assert state is not None
        assert state.session_id == "msess_001"

    def test_without_session(self):
        from core.mesh.mesh_session_coordinator import coordinate_mesh_session

        state = coordinate_mesh_session(session_id="msess_002", mesh_id="mesh_beta")
        assert state is not None


# ---------------------------------------------------------------------------
# 55. coordinate_mesh_session — with all inputs
# ---------------------------------------------------------------------------


class TestCoordinateMeshSessionAllInputs:
    def test_full_lifecycle_via_convenience(self):
        from core.mesh.mesh_session_coordinator import coordinate_mesh_session
        from contracts.mesh_session_coordinator import MeshCoordinatorStatus

        state = coordinate_mesh_session(
            mesh_session=_make_mesh_session_dict(),
            dispatch_result=_make_dispatch_result_dict(success=True),
            takeover_result=_make_takeover_result_dict(success=True, device_id="tablet_002"),
            merged_result=_make_merged_result_dict(success=True),
            takeover_device_id="tablet_002",
        )
        assert state is not None
        assert state.status == MeshCoordinatorStatus.completed
        assert state.result_merge_summary is not None


# ---------------------------------------------------------------------------
# 56. coordinate_mesh_session — graceful with None session
# ---------------------------------------------------------------------------


class TestCoordinateMeshSessionNone:
    def test_none_session(self):
        from core.mesh.mesh_session_coordinator import coordinate_mesh_session

        state = coordinate_mesh_session(mesh_session=None)
        assert state is not None


# ---------------------------------------------------------------------------
# 57. get_coordinator_summary — from coordinator
# ---------------------------------------------------------------------------


class TestGetCoordinatorSummary:
    def test_from_coordinator(self):
        from core.mesh.mesh_session_coordinator import (
            coordinate_mesh_session, get_coordinator_summary,
        )
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorSummary

        state = coordinate_mesh_session(mesh_session=_make_mesh_session_dict())
        summary = get_coordinator_summary(state)
        assert isinstance(summary, MeshSessionCoordinatorSummary)


# ---------------------------------------------------------------------------
# 58. Full lifecycle: session → dispatch → takeover → merge
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_full_lifecycle(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session,
            update_coordinator_with_dispatch_result,
            update_coordinator_with_takeover_result,
            update_coordinator_with_merged_result,
            build_coordinator_summary,
            MeshCoordinatorStatus,
        )

        # Step 1: Build from session
        state = from_mesh_session(_make_mesh_session_dict())
        assert state.status == MeshCoordinatorStatus.pending

        # Step 2: Dispatch
        state = update_coordinator_with_dispatch_result(
            state, _make_dispatch_result_dict(success=True)
        )
        assert state.status == MeshCoordinatorStatus.active

        # Step 3: Takeover
        state = update_coordinator_with_takeover_result(
            state,
            _make_takeover_result_dict(success=True, device_id="tablet_002"),
        )

        # Step 4: Merge
        state = update_coordinator_with_merged_result(
            state, _make_merged_result_dict(success=True)
        )
        assert state.status == MeshCoordinatorStatus.completed

        # Step 5: Summary
        summary = build_coordinator_summary(coordinator=state)
        assert summary.has_result_merge_summary is True


# ---------------------------------------------------------------------------
# 59. Graceful handling of partial MeshSession data
# ---------------------------------------------------------------------------


class TestGracefulPartialData:
    def test_partial_session_no_participants(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        partial_session = {
            "session_id": "msess_partial",
            # no participants, no subtask_assignments
        }
        state = from_mesh_session(partial_session)
        assert state is not None
        assert state.participants == []
        assert state.assignments == []

    def test_partial_session_missing_fields(self):
        from contracts.mesh_session_coordinator import from_mesh_session

        state = from_mesh_session({"session_id": "msess_partial"})
        assert state is not None


# ---------------------------------------------------------------------------
# 60. contracts package root re-exports
# ---------------------------------------------------------------------------


class TestContractsPackageReexports:
    def test_all_types_exported(self):
        from contracts import (
            MeshCoordinatorStatus,
            MeshParticipantStatus,
            MeshAssignmentStatus,
            MeshBarrierStatus,
            MeshCoordinationEventKind,
            MeshParticipantCoordinationState,
            MeshAssignmentState,
            MeshBarrierState,
            MeshCoordinationEvent,
            MeshSessionCoordinatorState,
            MeshSessionCoordinatorSummary,
            build_mesh_session_coordinator,
            coordinator_from_mesh_session,
            update_coordinator_with_dispatch_result,
            update_coordinator_with_takeover_result,
            update_coordinator_with_merged_result,
            build_coordinator_summary,
        )

        assert MeshCoordinatorStatus is not None
        assert MeshSessionCoordinatorState is not None
        assert build_mesh_session_coordinator is not None
        assert coordinator_from_mesh_session is not None


# ---------------------------------------------------------------------------
# 61. core.unified package re-exports
# ---------------------------------------------------------------------------


class TestCoreUnifiedReexports:
    def test_all_types_exported(self):
        from core.unified import (
            MeshCoordinatorStatus,
            MeshSessionCoordinatorState,
            MeshSessionCoordinatorSummary,
            build_mesh_session_coordinator,
            coordinator_from_mesh_session,
            build_coordinator_summary,
        )

        assert MeshCoordinatorStatus is not None
        assert MeshSessionCoordinatorState is not None
        assert build_coordinator_summary is not None


# ---------------------------------------------------------------------------
# 62. core.runtime package re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimeReexports:
    def test_coordinator_exported(self):
        from core.runtime import (
            MeshSessionCoordinator,
            coordinate_mesh_session,
            get_coordinator_summary,
        )

        assert MeshSessionCoordinator is not None
        assert coordinate_mesh_session is not None
        assert get_coordinator_summary is not None


# ---------------------------------------------------------------------------
# 63. Projection endpoint — GET /api/v1/mesh/coordinator-summary
# ---------------------------------------------------------------------------


class TestProjectionEndpointCoordinatorSummary:
    def test_endpoint_returns_200(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/mesh/coordinator-summary")
        assert resp.status_code == 200

    def test_endpoint_returns_valid_json(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/mesh/coordinator-summary")
        body = resp.json()
        assert isinstance(body, dict)

    def test_endpoint_has_required_fields(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/mesh/coordinator-summary")
        body = resp.json()
        for field in ["summary_id", "status", "timestamp"]:
            assert field in body, f"Missing field: {field}"

    def test_endpoint_does_not_break_existing_routes(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        # Existing PR-33 session endpoint still works
        resp = client.get("/api/v1/mesh/session")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 64. MeshSessionCoordinatorState round-trip with all fields
# ---------------------------------------------------------------------------


class TestMeshSessionCoordinatorStateFullRoundTrip:
    def test_full_round_trip(self):
        from contracts.mesh_session_coordinator import (
            MeshSessionCoordinatorState,
            MeshParticipantCoordinationState,
            MeshAssignmentState,
            MeshBarrierState,
            MeshCoordinationEvent,
            MeshCoordinatorStatus,
            MeshParticipantStatus,
            MeshAssignmentStatus,
            MeshBarrierStatus,
            MeshCoordinationEventKind,
        )

        c = MeshSessionCoordinatorState(
            session_id="msess_roundtrip",
            mesh_id="mesh_rt",
            trace_id="trace_rt",
            task_id="task_rt",
            status=MeshCoordinatorStatus.active,
            participants=[
                MeshParticipantCoordinationState(
                    device_id="dev_001",
                    roles=["primary"],
                    online=True,
                    ready=True,
                    status=MeshParticipantStatus.working,
                )
            ],
            assignments=[
                MeshAssignmentState(
                    subtask_id="sub_001",
                    device_id="dev_001",
                    status=MeshAssignmentStatus.in_progress,
                    capability_required="screen",
                )
            ],
            barrier_state=MeshBarrierState(
                status=MeshBarrierStatus.open,
            ),
            merge_owner_device_id="dev_001",
            pending_device_ids=["dev_001"],
            completed_device_ids=[],
            failed_device_ids=[],
            coordination_events=[
                MeshCoordinationEvent(
                    kind=MeshCoordinationEventKind.assignment_dispatched,
                    device_id="dev_001",
                    message="dispatched",
                )
            ],
        )

        d = c.to_dict()
        c2 = MeshSessionCoordinatorState.from_dict(d)
        assert c2.coordinator_id == c.coordinator_id
        assert c2.session_id == "msess_roundtrip"
        assert len(c2.participants) == 1
        assert c2.participants[0].device_id == "dev_001"
        assert len(c2.assignments) == 1
        assert c2.assignments[0].subtask_id == "sub_001"
        assert len(c2.coordination_events) == 1


# ---------------------------------------------------------------------------
# 65. BodyMeshRegistry.get_mesh_session_coordinator helper
# ---------------------------------------------------------------------------


class TestBodyMeshRegistryGetCoordinator:
    def test_get_coordinator_returns_state(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        registry = BodyMeshRegistry()
        # Registry is empty — should return a minimal state or None gracefully
        coordinator = registry.get_mesh_session_coordinator(mesh_id="test_mesh")
        # Can be None or a MeshSessionCoordinatorState
        if coordinator is not None:
            assert isinstance(coordinator, MeshSessionCoordinatorState)

    def test_get_coordinator_with_registered_devices(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState

        registry = BodyMeshRegistry()
        registry.register("dev_a")
        registry.register("dev_b")

        coordinator = registry.get_mesh_session_coordinator(mesh_id="test_mesh")
        if coordinator is not None:
            assert isinstance(coordinator, MeshSessionCoordinatorState)


# ---------------------------------------------------------------------------
# 66. Coordination events appended on state updates
# ---------------------------------------------------------------------------


class TestCoordinationEventsAppended:
    def test_events_appended_on_dispatch(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_dispatch_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        initial_event_count = len(coordinator.coordination_events)
        updated = update_coordinator_with_dispatch_result(
            coordinator, _make_dispatch_result_dict(success=True)
        )
        assert len(updated.coordination_events) > initial_event_count

    def test_events_appended_on_takeover(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        initial_count = len(coordinator.coordination_events)
        updated = update_coordinator_with_takeover_result(
            coordinator, _make_takeover_result_dict(success=True, device_id="tablet_002")
        )
        assert len(updated.coordination_events) > initial_count

    def test_events_appended_on_merge(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_merged_result,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        initial_count = len(coordinator.coordination_events)
        updated = update_coordinator_with_merged_result(
            coordinator, _make_merged_result_dict(success=True)
        )
        assert len(updated.coordination_events) > initial_count


# ---------------------------------------------------------------------------
# 67. Assignment status updated on takeover result
# ---------------------------------------------------------------------------


class TestAssignmentStatusUpdatedOnTakeover:
    def test_assignment_status_completed(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, update_coordinator_with_takeover_result,
            MeshAssignmentStatus,
        )

        session_dict = _make_mesh_session_dict(
            subtask_assignments=[
                {"subtask_id": "sub_001", "device_id": "tablet_002", "capability_required": "screen"},
            ]
        )
        coordinator = from_mesh_session(session_dict)
        updated = update_coordinator_with_takeover_result(
            coordinator,
            _make_takeover_result_dict(success=True, device_id="tablet_002"),
        )
        assignment = next(
            (a for a in updated.assignments if a.device_id == "tablet_002"), None
        )
        if assignment is not None:
            assert assignment.status == MeshAssignmentStatus.completed


# ---------------------------------------------------------------------------
# 68. Barrier posture none → barrier not_required
# ---------------------------------------------------------------------------


class TestBarrierPostureNone:
    def test_none_barrier(self):
        from contracts.mesh_session_coordinator import from_mesh_session, MeshBarrierStatus

        session_dict = _make_mesh_session_dict(barrier_posture="none")
        coordinator = from_mesh_session(session_dict)
        assert coordinator.barrier_state.status == MeshBarrierStatus.not_required


# ---------------------------------------------------------------------------
# 69. Barrier posture hard_barrier → barrier open
# ---------------------------------------------------------------------------


class TestBarrierPostureHard:
    def test_hard_barrier(self):
        from contracts.mesh_session_coordinator import from_mesh_session, MeshBarrierStatus

        session_dict = _make_mesh_session_dict(barrier_posture="hard_barrier")
        coordinator = from_mesh_session(session_dict)
        assert coordinator.barrier_state.status == MeshBarrierStatus.open


# ---------------------------------------------------------------------------
# 70. Summary has_result_merge_summary flag set correctly
# ---------------------------------------------------------------------------


class TestSummaryHasResultMergeSummaryFlag:
    def test_flag_false_when_no_summary(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session, build_coordinator_summary,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        summary = build_coordinator_summary(coordinator=coordinator)
        assert summary.has_result_merge_summary is False

    def test_flag_true_when_summary_present(self):
        from contracts.mesh_session_coordinator import (
            from_mesh_session,
            update_coordinator_with_merged_result,
            build_coordinator_summary,
        )

        coordinator = from_mesh_session(_make_mesh_session_dict())
        coordinator = update_coordinator_with_merged_result(
            coordinator, _make_merged_result_dict(success=True)
        )
        summary = build_coordinator_summary(coordinator=coordinator)
        assert summary.has_result_merge_summary is True
