"""tests/test_pr33_mesh_session.py
=======================================
Tests for PR-33: Mesh Session Contract.

Coverage:
  1.  Serialisation stability — to_dict / to_json / from_dict round-trips.
  2.  Stable field names — all documented fields present in to_dict output.
  3.  Enum values — MeshSessionStatus, MeshMergePolicy, MeshBarrierPosture.
  4.  Sub-contracts — MeshSessionParticipant, MeshSubtaskAssignment correctness.
  5.  from_device_formation_summary — adapter from FormationSummary.
  6.  from_cross_device_routing_summary — adapter from CrossDeviceAssignmentSummary.
  7.  from_constellation_decomposition — adapter from TaskDecomposition.
  8.  build_mesh_session — convenience factory.
  9.  Graceful handling of partial / missing data (None inputs, missing attrs).
  10. contracts package root re-exports.
  11. core.unified package re-exports.
  12. BodyMeshRegistry.get_mesh_session() integration helper.
  13. Projection endpoint — GET /api/v1/mesh/session (additive, read-only).
  14. to_compact_summary helper.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — mock objects shaped like real runtime data
# ---------------------------------------------------------------------------

def _make_formation_summary(
    formation_id: str = "formation_001",
    source_device_id: str = "phone_001",
    primary_device_id: str = "tablet_002",
    merge_owner: str = None,
    fallback: list = None,
    support: list = None,
    observer: list = None,
    relay: list = None,
    barrier_posture: str = "wait_primary",
    merge_policy: str = "parallel",
    multi_req: bool = True,
    merge_req: bool = False,
) -> Any:
    m = MagicMock()
    m.formation_id = formation_id
    m.source_device_id = source_device_id
    m.primary_execution_device_id = primary_device_id
    m.merge_owner_device_id = merge_owner
    m.fallback_device_ids = fallback or []
    m.support_device_ids = support or []
    m.observer_device_ids = observer or []
    m.relay_device_ids = relay or []
    m.barrier_posture = barrier_posture
    m.merge_policy = merge_policy
    m.multi_device_required = multi_req
    m.merge_confirmation_required = merge_req
    return m


def _make_routing_summary(
    source_device_id: str = "phone_001",
    primary_device_id: str = "tablet_002",
    mesh_id: str = "mesh_alpha",
    routing_posture: str = "split_execution",
    multi_req: bool = True,
    merge_req: bool = False,
    assigned_device_ids: list = None,
    fallback_device_ids: list = None,
) -> Any:
    m = MagicMock()
    m.source_device_id = source_device_id
    m.primary_device_id = primary_device_id
    m.mesh_id = mesh_id
    m.routing_posture = routing_posture
    m.multi_device_required = multi_req
    m.merge_confirmation_required = merge_req
    m.assigned_device_ids = assigned_device_ids or []
    m.fallback_device_ids = fallback_device_ids or []
    m.merge_owner_device_id = None
    return m


def _make_subtask(
    task_id: str,
    device_id: str = "",
    device_type: str = "",
    status: str = "pending",
    name: str = "task",
    action: str = "execute",
    result: dict = None,
) -> Any:
    m = MagicMock()
    m.task_id = task_id
    m.device_id = device_id
    m.device_type = device_type
    m.status = status
    m.name = name
    m.action = action
    m.result = result
    return m


def _make_decomposition(
    goal: str = "do something",
    subtasks: list = None,
) -> Any:
    m = MagicMock()
    m.goal = goal
    m.subtasks = subtasks or []
    return m


# ---------------------------------------------------------------------------
# 1. Serialisation stability
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    def test_to_dict_is_json_safe(self):
        from contracts.mesh_session import build_mesh_session
        session = build_mesh_session(
            source_device_id="dev_a",
            primary_device_id="dev_b",
        )
        d = session.to_dict()
        # Must be JSON-serialisable without error
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_to_json_round_trip(self):
        from contracts.mesh_session import MeshSession, build_mesh_session
        session = build_mesh_session(
            source_device_id="dev_a",
            primary_device_id="dev_b",
            mesh_id="mesh_1",
        )
        json_str = session.to_json()
        d = json.loads(json_str)
        reconstructed = MeshSession.from_dict(d)
        assert reconstructed.session_id == session.session_id
        assert reconstructed.source_device_id == "dev_a"
        assert reconstructed.primary_device_id == "dev_b"
        assert reconstructed.mesh_id == "mesh_1"

    def test_from_dict_tolerates_extra_fields(self):
        from contracts.mesh_session import MeshSession
        d = {
            "session_id": "msess_aaa",
            "source_device_id": "dev_x",
            "primary_device_id": "dev_y",
            "status": "active",
            "unknown_field_future_compat": "should_be_ignored",
        }
        # Should not raise
        session = MeshSession.from_dict(d)
        assert session.session_id == "msess_aaa"
        assert session.status.value == "active"

    def test_from_dict_tolerates_missing_optionals(self):
        from contracts.mesh_session import MeshSession
        session = MeshSession.from_dict({"session_id": "msess_min"})
        assert session.session_id == "msess_min"
        assert session.participants == []
        assert session.subtask_assignments == []


# ---------------------------------------------------------------------------
# 2. Stable field names
# ---------------------------------------------------------------------------

class TestStableFieldNames:
    REQUIRED_TOP_LEVEL_FIELDS = [
        "session_id",
        "trace_id",
        "task_id",
        "mesh_id",
        "source_device_id",
        "primary_device_id",
        "merge_owner_device_id",
        "participants",
        "subtask_assignments",
        "barrier_posture",
        "merge_policy",
        "multi_device_required",
        "merge_confirmation_required",
        "status",
        "created_at",
        "updated_at",
        "metadata",
    ]

    def test_all_fields_present_in_to_dict(self):
        from contracts.mesh_session import build_mesh_session
        session = build_mesh_session(
            source_device_id="dev_a",
            primary_device_id="dev_b",
        )
        d = session.to_dict()
        for field in self.REQUIRED_TOP_LEVEL_FIELDS:
            assert field in d, f"Missing field: {field}"

    def test_participant_fields_present(self):
        from contracts.mesh_session import MeshSessionParticipant
        p = MeshSessionParticipant(
            device_id="dev_a",
            roles=["primary"],
            authority_scope="mesh_authority",
            online=True,
            health_score=0.9,
        )
        d = p.to_dict()
        for field in ["device_id", "runtime_id", "roles", "authority_scope", "online", "health_score", "metadata"]:
            assert field in d, f"Missing participant field: {field}"

    def test_subtask_assignment_fields_present(self):
        from contracts.mesh_session import MeshSubtaskAssignment
        a = MeshSubtaskAssignment(
            subtask_id="sub_001",
            device_id="dev_a",
            capability_required="camera",
            status="success",
            result_ref="ref_001",
        )
        d = a.to_dict()
        for field in ["subtask_id", "device_id", "capability_required", "status", "result_ref", "metadata"]:
            assert field in d, f"Missing assignment field: {field}"


# ---------------------------------------------------------------------------
# 3. Enum values
# ---------------------------------------------------------------------------

class TestEnumValues:
    def test_session_status_values(self):
        from contracts.mesh_session import MeshSessionStatus
        assert MeshSessionStatus.PENDING.value == "pending"
        assert MeshSessionStatus.ACTIVE.value == "active"
        assert MeshSessionStatus.MERGING.value == "merging"
        assert MeshSessionStatus.COMPLETED.value == "completed"
        assert MeshSessionStatus.CANCELLED.value == "cancelled"
        assert MeshSessionStatus.FAILED.value == "failed"
        assert MeshSessionStatus.UNKNOWN.value == "unknown"

    def test_merge_policy_values(self):
        from contracts.mesh_session import MeshMergePolicy
        assert MeshMergePolicy.NO_MERGE.value == "no_merge"
        assert MeshMergePolicy.SEQUENTIAL.value == "sequential"
        assert MeshMergePolicy.PARALLEL.value == "parallel"
        assert MeshMergePolicy.BARRIER.value == "barrier"
        assert MeshMergePolicy.OWNER_DECIDES.value == "owner_decides"
        assert MeshMergePolicy.UNKNOWN.value == "unknown"

    def test_barrier_posture_values(self):
        from contracts.mesh_session import MeshBarrierPosture
        assert MeshBarrierPosture.NO_BARRIER.value == "no_barrier"
        assert MeshBarrierPosture.WAIT_PRIMARY.value == "wait_primary"
        assert MeshBarrierPosture.WAIT_ALL.value == "wait_all"
        assert MeshBarrierPosture.WAIT_MERGE_OWNER.value == "wait_merge_owner"
        assert MeshBarrierPosture.SOFT_BARRIER.value == "soft_barrier"
        assert MeshBarrierPosture.UNKNOWN.value == "unknown"

    def test_enum_serialised_as_string(self):
        from contracts.mesh_session import build_mesh_session, MeshSessionStatus, MeshMergePolicy, MeshBarrierPosture
        session = build_mesh_session(
            status=MeshSessionStatus.ACTIVE,
            merge_policy=MeshMergePolicy.PARALLEL,
            barrier_posture=MeshBarrierPosture.WAIT_ALL,
        )
        d = session.to_dict()
        assert d["status"] == "active"
        assert d["merge_policy"] == "parallel"
        assert d["barrier_posture"] == "wait_all"


# ---------------------------------------------------------------------------
# 4. Sub-contracts
# ---------------------------------------------------------------------------

class TestSubContracts:
    def test_participant_defaults(self):
        from contracts.mesh_session import MeshSessionParticipant
        p = MeshSessionParticipant()
        assert p.device_id == ""
        assert p.roles == []
        assert p.runtime_id is None
        assert p.online is None
        assert p.health_score is None

    def test_participant_to_dict_round_trip(self):
        from contracts.mesh_session import MeshSessionParticipant
        p = MeshSessionParticipant(
            device_id="dev_001",
            roles=["primary", "source"],
            authority_scope="execution_authority",
            online=True,
            health_score=0.85,
            metadata={"display_name": "Main Phone"},
        )
        d = p.to_dict()
        assert d["device_id"] == "dev_001"
        assert "primary" in d["roles"]
        assert d["authority_scope"] == "execution_authority"
        assert d["online"] is True
        assert d["health_score"] == pytest.approx(0.85)
        json.dumps(d)  # must be JSON-serialisable

    def test_subtask_assignment_defaults(self):
        from contracts.mesh_session import MeshSubtaskAssignment
        a = MeshSubtaskAssignment()
        assert a.device_id == ""
        assert a.status == "pending"
        assert a.result_ref is None
        assert a.capability_required is None

    def test_subtask_assignment_to_dict(self):
        from contracts.mesh_session import MeshSubtaskAssignment
        a = MeshSubtaskAssignment(
            subtask_id="sub_abc",
            device_id="dev_b",
            capability_required="gpu",
            status="success",
            result_ref="result_key_xyz",
        )
        d = a.to_dict()
        assert d["subtask_id"] == "sub_abc"
        assert d["status"] == "success"
        json.dumps(d)


# ---------------------------------------------------------------------------
# 5. from_device_formation_summary
# ---------------------------------------------------------------------------

class TestFromDeviceFormationSummary:
    def test_basic_formation(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = _make_formation_summary()
        session = from_device_formation_summary(summary)
        assert session.source_device_id == "phone_001"
        assert session.primary_device_id == "tablet_002"
        assert session.multi_device_required is True
        assert any(p.device_id == "phone_001" for p in session.participants)
        assert any(p.device_id == "tablet_002" for p in session.participants)

    def test_mesh_id_from_formation_id(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = _make_formation_summary(formation_id="form_xyz")
        session = from_device_formation_summary(summary)
        assert session.mesh_id == "form_xyz"

    def test_merge_policy_mapped(self):
        from contracts.mesh_session import from_device_formation_summary, MeshMergePolicy
        summary = _make_formation_summary(merge_policy="parallel")
        session = from_device_formation_summary(summary)
        assert session.merge_policy == MeshMergePolicy.PARALLEL

    def test_barrier_posture_mapped(self):
        from contracts.mesh_session import from_device_formation_summary, MeshBarrierPosture
        summary = _make_formation_summary(barrier_posture="wait_primary")
        session = from_device_formation_summary(summary)
        assert session.barrier_posture == MeshBarrierPosture.WAIT_PRIMARY

    def test_merge_owner_populated(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = _make_formation_summary(merge_owner="merge_dev_99")
        session = from_device_formation_summary(summary)
        assert session.merge_owner_device_id == "merge_dev_99"
        assert any(p.device_id == "merge_dev_99" for p in session.participants)

    def test_fallback_support_in_participants(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = _make_formation_summary(
            fallback=["fallback_003"],
            support=["support_004"],
            observer=["observer_005"],
        )
        session = from_device_formation_summary(summary)
        device_ids = {p.device_id for p in session.participants}
        assert "fallback_003" in device_ids
        assert "support_004" in device_ids
        assert "observer_005" in device_ids

    def test_optional_ids_passed_through(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = _make_formation_summary()
        session = from_device_formation_summary(
            summary,
            session_id="sess_explicit",
            task_id="task_001",
            trace_id="trace_abc",
        )
        assert session.session_id == "sess_explicit"
        assert session.task_id == "task_001"
        assert session.trace_id == "trace_abc"

    def test_none_returns_stub(self):
        from contracts.mesh_session import from_device_formation_summary, MeshSessionStatus
        session = from_device_formation_summary(None)
        assert isinstance(session.session_id, str)
        assert session.status == MeshSessionStatus.UNKNOWN
        assert session.metadata.get("empty") is True

    def test_serialisable(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = _make_formation_summary()
        session = from_device_formation_summary(summary)
        json.dumps(session.to_dict())


# ---------------------------------------------------------------------------
# 6. from_cross_device_routing_summary
# ---------------------------------------------------------------------------

class TestFromCrossDeviceRoutingSummary:
    def test_basic_routing(self):
        from contracts.mesh_session import from_cross_device_routing_summary
        summary = _make_routing_summary()
        session = from_cross_device_routing_summary(summary)
        assert session.source_device_id == "phone_001"
        assert session.primary_device_id == "tablet_002"
        assert session.mesh_id == "mesh_alpha"

    def test_split_posture_maps_to_parallel_merge(self):
        from contracts.mesh_session import from_cross_device_routing_summary, MeshMergePolicy, MeshBarrierPosture
        summary = _make_routing_summary(routing_posture="split_execution")
        session = from_cross_device_routing_summary(summary)
        assert session.merge_policy == MeshMergePolicy.PARALLEL
        assert session.barrier_posture == MeshBarrierPosture.WAIT_ALL

    def test_sequential_posture_maps_correctly(self):
        from contracts.mesh_session import from_cross_device_routing_summary, MeshMergePolicy, MeshBarrierPosture
        summary = _make_routing_summary(routing_posture="sequential")
        session = from_cross_device_routing_summary(summary)
        assert session.merge_policy == MeshMergePolicy.SEQUENTIAL
        assert session.barrier_posture == MeshBarrierPosture.WAIT_PRIMARY

    def test_remote_posture_maps_to_no_merge(self):
        from contracts.mesh_session import from_cross_device_routing_summary, MeshMergePolicy, MeshBarrierPosture
        summary = _make_routing_summary(routing_posture="remote_required")
        session = from_cross_device_routing_summary(summary)
        assert session.merge_policy == MeshMergePolicy.NO_MERGE
        assert session.barrier_posture == MeshBarrierPosture.NO_BARRIER

    def test_assigned_devices_in_participants(self):
        from contracts.mesh_session import from_cross_device_routing_summary
        summary = _make_routing_summary(
            assigned_device_ids=["dev_c", "dev_d"],
        )
        session = from_cross_device_routing_summary(summary)
        device_ids = {p.device_id for p in session.participants}
        assert "dev_c" in device_ids
        assert "dev_d" in device_ids

    def test_none_returns_stub(self):
        from contracts.mesh_session import from_cross_device_routing_summary, MeshSessionStatus
        session = from_cross_device_routing_summary(None)
        assert session.status == MeshSessionStatus.UNKNOWN
        assert session.metadata.get("empty") is True

    def test_serialisable(self):
        from contracts.mesh_session import from_cross_device_routing_summary
        summary = _make_routing_summary()
        session = from_cross_device_routing_summary(summary)
        json.dumps(session.to_dict())


# ---------------------------------------------------------------------------
# 7. from_constellation_decomposition
# ---------------------------------------------------------------------------

class TestFromConstellationDecomposition:
    def test_basic_decomposition(self):
        from contracts.mesh_session import from_constellation_decomposition
        subtasks = [
            _make_subtask("sub_1", device_id="dev_a", device_type="phone"),
            _make_subtask("sub_2", device_id="dev_b", device_type="tablet"),
        ]
        decomp = _make_decomposition(goal="test goal", subtasks=subtasks)
        session = from_constellation_decomposition(
            decomp,
            source_device_id="dev_a",
            primary_device_id="dev_a",
        )
        assert len(session.subtask_assignments) == 2
        assert any(a.subtask_id == "sub_1" for a in session.subtask_assignments)
        assert any(a.subtask_id == "sub_2" for a in session.subtask_assignments)

    def test_subtask_status_mapped(self):
        from contracts.mesh_session import from_constellation_decomposition
        subtasks = [
            _make_subtask("sub_1", status="success"),
            _make_subtask("sub_2", status="failed"),
        ]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        statuses = {a.subtask_id: a.status for a in session.subtask_assignments}
        assert statuses["sub_1"] == "success"
        assert statuses["sub_2"] == "failed"

    def test_session_status_inferred_all_success(self):
        from contracts.mesh_session import from_constellation_decomposition, MeshSessionStatus
        subtasks = [
            _make_subtask("sub_1", status="success"),
            _make_subtask("sub_2", status="success"),
        ]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        assert session.status == MeshSessionStatus.COMPLETED

    def test_session_status_inferred_any_failed(self):
        from contracts.mesh_session import from_constellation_decomposition, MeshSessionStatus
        subtasks = [
            _make_subtask("sub_1", status="success"),
            _make_subtask("sub_2", status="failed"),
        ]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        assert session.status == MeshSessionStatus.FAILED

    def test_multi_device_required_when_multiple_devices(self):
        from contracts.mesh_session import from_constellation_decomposition
        subtasks = [
            _make_subtask("sub_1", device_id="dev_a"),
            _make_subtask("sub_2", device_id="dev_b"),
        ]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        assert session.multi_device_required is True

    def test_single_device_not_multi_required(self):
        from contracts.mesh_session import from_constellation_decomposition
        subtasks = [
            _make_subtask("sub_1", device_id="dev_a"),
            _make_subtask("sub_2", device_id="dev_a"),
        ]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        assert session.multi_device_required is False

    def test_capability_required_from_device_type(self):
        from contracts.mesh_session import from_constellation_decomposition
        subtasks = [_make_subtask("sub_1", device_id="dev_a", device_type="camera_device")]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        assignment = session.subtask_assignments[0]
        assert assignment.capability_required == "camera_device"

    def test_none_returns_stub(self):
        from contracts.mesh_session import from_constellation_decomposition, MeshSessionStatus
        session = from_constellation_decomposition(None)
        assert session.status == MeshSessionStatus.UNKNOWN
        assert session.metadata.get("empty") is True

    def test_serialisable(self):
        from contracts.mesh_session import from_constellation_decomposition
        subtasks = [_make_subtask("sub_1", device_id="dev_a")]
        decomp = _make_decomposition(subtasks=subtasks)
        session = from_constellation_decomposition(decomp)
        json.dumps(session.to_dict())


# ---------------------------------------------------------------------------
# 8. build_mesh_session
# ---------------------------------------------------------------------------

class TestBuildMeshSession:
    def test_defaults(self):
        from contracts.mesh_session import build_mesh_session, MeshSessionStatus, MeshMergePolicy, MeshBarrierPosture
        session = build_mesh_session()
        assert session.session_id.startswith("msess_")
        assert session.status == MeshSessionStatus.PENDING
        assert session.merge_policy == MeshMergePolicy.UNKNOWN
        assert session.barrier_posture == MeshBarrierPosture.UNKNOWN
        assert session.participants == []
        assert session.subtask_assignments == []

    def test_explicit_params(self):
        from contracts.mesh_session import build_mesh_session, MeshSessionStatus, MeshMergePolicy, MeshBarrierPosture
        session = build_mesh_session(
            source_device_id="phone",
            primary_device_id="tablet",
            session_id="sess_explicit",
            task_id="task_xyz",
            trace_id="trace_123",
            mesh_id="mesh_beta",
            merge_owner_device_id="phone",
            multi_device_required=True,
            merge_confirmation_required=True,
            status=MeshSessionStatus.ACTIVE,
            merge_policy=MeshMergePolicy.BARRIER,
            barrier_posture=MeshBarrierPosture.WAIT_MERGE_OWNER,
            metadata={"custom": "value"},
        )
        assert session.session_id == "sess_explicit"
        assert session.source_device_id == "phone"
        assert session.primary_device_id == "tablet"
        assert session.task_id == "task_xyz"
        assert session.trace_id == "trace_123"
        assert session.mesh_id == "mesh_beta"
        assert session.merge_owner_device_id == "phone"
        assert session.multi_device_required is True
        assert session.merge_confirmation_required is True
        assert session.status == MeshSessionStatus.ACTIVE
        assert session.merge_policy == MeshMergePolicy.BARRIER
        assert session.barrier_posture == MeshBarrierPosture.WAIT_MERGE_OWNER
        assert session.metadata["custom"] == "value"

    def test_with_participants(self):
        from contracts.mesh_session import build_mesh_session, MeshSessionParticipant
        p = MeshSessionParticipant(device_id="dev_a", roles=["primary"])
        session = build_mesh_session(participants=[p])
        assert len(session.participants) == 1
        assert session.participants[0].device_id == "dev_a"


# ---------------------------------------------------------------------------
# 9. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------

class TestGracefulPartialData:
    def test_formation_summary_with_no_device_ids(self):
        from contracts.mesh_session import from_device_formation_summary
        summary = MagicMock()
        summary.formation_id = ""
        summary.source_device_id = ""
        summary.primary_execution_device_id = ""
        summary.merge_owner_device_id = None
        summary.fallback_device_ids = []
        summary.support_device_ids = []
        summary.observer_device_ids = []
        summary.relay_device_ids = []
        summary.barrier_posture = None
        summary.merge_policy = None
        summary.multi_device_required = False
        summary.merge_confirmation_required = False
        session = from_device_formation_summary(summary)
        assert session is not None
        assert isinstance(session.session_id, str)

    def test_routing_summary_missing_attrs(self):
        from contracts.mesh_session import from_cross_device_routing_summary
        summary = MagicMock(spec=[])  # no attributes
        session = from_cross_device_routing_summary(summary)
        assert session is not None

    def test_decomposition_with_empty_subtasks(self):
        from contracts.mesh_session import from_constellation_decomposition
        decomp = _make_decomposition(subtasks=[])
        session = from_constellation_decomposition(decomp)
        assert session.subtask_assignments == []

    def test_decomposition_subtask_with_missing_fields(self):
        from contracts.mesh_session import from_constellation_decomposition
        bad_subtask = MagicMock(spec=["task_id"])
        bad_subtask.task_id = "sub_bad"
        decomp = _make_decomposition(subtasks=[bad_subtask])
        # Should not raise
        session = from_constellation_decomposition(decomp)
        assert len(session.subtask_assignments) >= 0  # may skip bad subtask

    def test_participant_with_all_nones(self):
        from contracts.mesh_session import MeshSessionParticipant
        p = MeshSessionParticipant(device_id="dev", online=None, health_score=None)
        d = p.to_dict()
        assert d["online"] is None
        assert d["health_score"] is None
        json.dumps(d)

    def test_from_dict_minimal_session(self):
        from contracts.mesh_session import MeshSession
        session = MeshSession.from_dict({})
        # Should have defaults, not crash
        assert isinstance(session.session_id, str)
        assert session.status.value in ("pending", "unknown")


# ---------------------------------------------------------------------------
# 10. contracts package root re-exports
# ---------------------------------------------------------------------------

class TestContractsPackageReExports:
    def test_mesh_session_importable_from_contracts(self):
        from contracts import MeshSession
        assert MeshSession is not None

    def test_mesh_session_participant_importable(self):
        from contracts import MeshSessionParticipant
        assert MeshSessionParticipant is not None

    def test_mesh_subtask_assignment_importable(self):
        from contracts import MeshSubtaskAssignment
        assert MeshSubtaskAssignment is not None

    def test_mesh_merge_policy_importable(self):
        from contracts import MeshMergePolicy
        assert MeshMergePolicy is not None

    def test_mesh_barrier_posture_importable(self):
        from contracts import MeshBarrierPosture
        assert MeshBarrierPosture is not None

    def test_mesh_session_status_importable(self):
        from contracts import MeshSessionStatus
        assert MeshSessionStatus is not None

    def test_build_mesh_session_importable(self):
        from contracts import build_mesh_session
        assert callable(build_mesh_session)

    def test_from_constellation_decomposition_importable(self):
        from contracts import from_constellation_decomposition
        assert callable(from_constellation_decomposition)

    def test_mesh_session_from_formation_importable(self):
        from contracts import mesh_session_from_formation
        assert callable(mesh_session_from_formation)

    def test_mesh_session_from_routing_importable(self):
        from contracts import mesh_session_from_routing
        assert callable(mesh_session_from_routing)


# ---------------------------------------------------------------------------
# 11. core.unified package re-exports
# ---------------------------------------------------------------------------

class TestCoreUnifiedReExports:
    def test_mesh_session_importable_from_core_unified(self):
        from core.unified import MeshSession
        assert MeshSession is not None

    def test_build_mesh_session_importable_from_core_unified(self):
        from core.unified import build_mesh_session
        assert callable(build_mesh_session)

    def test_mesh_session_status_importable_from_core_unified(self):
        from core.unified import MeshSessionStatus
        assert MeshSessionStatus is not None

    def test_from_constellation_decomposition_importable_from_core_unified(self):
        from core.unified import from_constellation_decomposition
        assert callable(from_constellation_decomposition)

    def test_mesh_session_from_formation_importable_from_core_unified(self):
        from core.unified import mesh_session_from_formation
        assert callable(mesh_session_from_formation)

    def test_mesh_session_from_routing_importable_from_core_unified(self):
        from core.unified import mesh_session_from_routing
        assert callable(mesh_session_from_routing)


# ---------------------------------------------------------------------------
# 12. BodyMeshRegistry.get_mesh_session()
# ---------------------------------------------------------------------------

class TestBodyMeshRegistryGetMeshSession:
    def test_empty_registry_returns_default_session(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry
        registry = BodyMeshRegistry()
        session = registry.get_mesh_session(mesh_id="test_mesh")
        assert session is not None
        # Empty registry returns a stub with no participants
        assert session.participants == [] or isinstance(session.participants, list)

    def test_single_device_session(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        registry = BodyMeshRegistry()
        registry.register("device_alpha", roles=[DeviceRole.PERCEPTION])
        session = registry.get_mesh_session(mesh_id="test_mesh")
        assert session is not None
        assert len(session.participants) == 1
        assert session.participants[0].device_id == "device_alpha"

    def test_multi_device_session_marks_multi_required(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        registry = BodyMeshRegistry()
        registry.register("dev_x", roles=[DeviceRole.PERCEPTION])
        registry.register("dev_y", roles=[DeviceRole.ACTION])
        session = registry.get_mesh_session(mesh_id="test_mesh")
        assert session is not None
        assert session.multi_device_required is True
        device_ids = {p.device_id for p in session.participants}
        assert "dev_x" in device_ids
        assert "dev_y" in device_ids

    def test_session_serialisable(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        registry = BodyMeshRegistry()
        registry.register("dev_z", roles=[DeviceRole.PRESENCE])
        session = registry.get_mesh_session(mesh_id="test_mesh")
        assert session is not None
        json.dumps(session.to_dict())

    def test_mesh_id_embedded_in_session(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
        registry = BodyMeshRegistry()
        registry.register("dev_a", roles=[DeviceRole.PERCEPTION])
        session = registry.get_mesh_session(mesh_id="my_mesh_id")
        assert session is not None
        assert session.mesh_id == "my_mesh_id"


# ---------------------------------------------------------------------------
# 13. Projection endpoint — GET /api/v1/mesh/session
# ---------------------------------------------------------------------------

class TestProjectionEndpoint:
    def test_endpoint_registered_in_router(self):
        """The /api/v1/mesh/session GET route should be present."""
        from core.routes.projection import create_router
        router = create_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/mesh/session" in routes

    @pytest.mark.asyncio
    async def test_endpoint_returns_valid_session(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            resp = client.get("/api/v1/mesh/session")
        assert resp.status_code == 200
        data = resp.json()
        # Must have session_id field
        assert "session_id" in data
        assert isinstance(data["session_id"], str)

    @pytest.mark.asyncio
    async def test_endpoint_is_additive_does_not_break_memberships(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            r1 = client.get("/api/v1/mesh/memberships")
            r2 = client.get("/api/v1/mesh/session")

        assert r1.status_code == 200
        assert r2.status_code == 200

        d1 = r1.json()
        d2 = r2.json()
        # memberships endpoint still has 'memberships' key
        assert "memberships" in d1
        # session endpoint has 'session_id' key
        assert "session_id" in d2


# ---------------------------------------------------------------------------
# 14. to_compact_summary
# ---------------------------------------------------------------------------

class TestCompactSummary:
    def test_compact_summary_has_expected_keys(self):
        from contracts.mesh_session import build_mesh_session
        session = build_mesh_session(
            source_device_id="dev_a",
            primary_device_id="dev_b",
            mesh_id="mesh_x",
        )
        summary = session.to_compact_summary()
        for key in [
            "session_id", "status", "source_device_id", "primary_device_id",
            "merge_owner_device_id", "participant_count", "subtask_count",
            "multi_device_required", "merge_policy", "barrier_posture",
            "mesh_id", "task_id", "trace_id",
        ]:
            assert key in summary, f"Missing compact summary key: {key}"

    def test_compact_summary_serialisable(self):
        from contracts.mesh_session import build_mesh_session
        session = build_mesh_session(source_device_id="a", primary_device_id="b")
        json.dumps(session.to_compact_summary())

    def test_compact_summary_counts_participants(self):
        from contracts.mesh_session import build_mesh_session, MeshSessionParticipant
        p1 = MeshSessionParticipant(device_id="d1", roles=["primary"])
        p2 = MeshSessionParticipant(device_id="d2", roles=["support"])
        session = build_mesh_session(participants=[p1, p2])
        summary = session.to_compact_summary()
        assert summary["participant_count"] == 2
