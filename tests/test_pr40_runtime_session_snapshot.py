"""tests/test_pr40_runtime_session_snapshot.py
================================================
Tests for PR-40: Durable Runtime Session Snapshot Contract.

Coverage:
  1.  RuntimeSessionSnapshotStatus — all expected values present.
  2.  RuntimeSessionSnapshotIdentity — serialisation stability (to_dict/to_json/from_dict).
  3.  RuntimeSessionSnapshotIdentity — stable field names.
  4.  RuntimeSessionSnapshotIdentity — snapshot_id auto-generated.
  5.  RuntimeSessionSnapshotDispatchState — serialisation stability.
  6.  RuntimeSessionSnapshotDispatchState — stable field names.
  7.  RuntimeSessionSnapshotDispatchState — empty construction valid.
  8.  RuntimeSessionSnapshotTakeoverState — serialisation stability.
  9.  RuntimeSessionSnapshotTakeoverState — stable field names.
  10. RuntimeSessionSnapshotTakeoverState — empty construction valid.
  11. RuntimeSessionSnapshotCoordinatorState — serialisation stability.
  12. RuntimeSessionSnapshotCoordinatorState — stable field names.
  13. RuntimeSessionSnapshotCoordinatorState — empty construction valid.
  14. RuntimeSessionSnapshotResultState — serialisation stability.
  15. RuntimeSessionSnapshotResultState — stable field names.
  16. RuntimeSessionSnapshotResultState — empty construction valid.
  17. RuntimeSessionSnapshotRecoveryState — serialisation stability.
  18. RuntimeSessionSnapshotRecoveryState — stable field names.
  19. RuntimeSessionSnapshotRecoveryState — empty construction valid.
  20. RuntimeSessionSnapshot — serialisation stability (to_dict/to_json/from_dict).
  21. RuntimeSessionSnapshot — stable field names.
  22. RuntimeSessionSnapshot — snapshot_id auto-generated.
  23. RuntimeSessionSnapshot — session_id default empty string.
  24. RuntimeSessionSnapshot — created_at/updated_at populated.
  25. RuntimeSessionSnapshot — status default unknown.
  26. RuntimeSessionSnapshot — empty construction valid.
  27. RuntimeSessionSnapshot — to_identity returns identity block.
  28. RuntimeSessionSnapshot — repr informative.
  29. RuntimeSessionSnapshot — from_dict round-trip stable.
  30. RuntimeSessionSnapshotSummary — serialisation stability.
  31. RuntimeSessionSnapshotSummary — stable field names.
  32. RuntimeSessionSnapshotSummary — summary_id auto-generated.
  33. RuntimeSessionSnapshotSummary — empty construction valid.
  34. RuntimeSessionSnapshotSummary — repr informative.
  35. build_runtime_session_snapshot — empty inputs.
  36. build_runtime_session_snapshot — session_id respected.
  37. build_runtime_session_snapshot — trace_id/task_id/mesh_session_id respected.
  38. build_runtime_session_snapshot — source_device_id/primary_device_id respected.
  39. build_runtime_session_snapshot — explicit snapshot_id respected.
  40. build_runtime_session_snapshot — never raises on None inputs.
  41. build_runtime_session_snapshot — never raises on bad inputs.
  42. build_runtime_session_snapshot — runtime_devices populated.
  43. build_runtime_session_snapshot — runtime_hosts populated.
  44. build_runtime_session_snapshot — mesh_memberships populated.
  45. build_runtime_session_snapshot — mesh_session populated.
  46. build_runtime_session_snapshot — dispatch_state populated from dict.
  47. build_runtime_session_snapshot — takeover_states populated from list of dicts.
  48. build_runtime_session_snapshot — coordinator_state populated from dict.
  49. build_runtime_session_snapshot — merged_result populated from dict.
  50. build_runtime_session_snapshot — recovery_state populated from dict.
  51. build_runtime_session_snapshot — governance_snapshot populated.
  52. build_runtime_session_snapshot — policy_alignment populated.
  53. build_runtime_session_snapshot — status inferred from recovery completed.
  54. build_runtime_session_snapshot — status inferred from recovery recovering.
  55. build_runtime_session_snapshot — status inferred from merged result completed.
  56. build_runtime_session_snapshot — explicit status overrides inference.
  57. build_runtime_session_snapshot_summary — empty snapshot.
  58. build_runtime_session_snapshot_summary — full snapshot counts correct.
  59. build_runtime_session_snapshot_summary — has_* flags set correctly.
  60. build_runtime_session_snapshot_summary — never raises on None.
  61. build_runtime_session_snapshot_summary — never raises on bad input.
  62. from_mesh_session — empty dict → valid snapshot.
  63. from_mesh_session — None input → valid snapshot.
  64. from_mesh_session — mesh_session_id populated from session_id.
  65. from_mesh_session — participants mapped to runtime_devices.
  66. from_mesh_session — never raises on garbage input.
  67. from_source_dispatch_result — empty dict → valid snapshot.
  68. from_source_dispatch_result — None input → valid snapshot.
  69. from_source_dispatch_result — dispatch_state populated.
  70. from_source_dispatch_result — session_id extracted.
  71. from_source_dispatch_result — never raises on garbage.
  72. from_target_takeover_result — empty dict → valid snapshot.
  73. from_target_takeover_result — None input → valid snapshot.
  74. from_target_takeover_result — takeover_states populated.
  75. from_target_takeover_result — primary_device_id from target_device_id.
  76. from_target_takeover_result — never raises on garbage.
  77. from_result_merge — empty dict → valid snapshot.
  78. from_result_merge — None input → valid snapshot.
  79. from_result_merge — merged_result populated.
  80. from_result_merge — session_id extracted.
  81. from_result_merge — never raises on garbage.
  82. from_recovery_state — empty dict → valid snapshot.
  83. from_recovery_state — None input → valid snapshot.
  84. from_recovery_state — recovery_state populated.
  85. from_recovery_state — session_id extracted.
  86. from_recovery_state — never raises on garbage.
  87. from_multi_device_runtime_projection — empty dict → valid snapshot.
  88. from_multi_device_runtime_projection — None input → valid snapshot.
  89. from_multi_device_runtime_projection — devices extracted.
  90. from_multi_device_runtime_projection — hosts extracted.
  91. from_multi_device_runtime_projection — mesh_memberships extracted.
  92. from_multi_device_runtime_projection — mesh_session from first entry.
  93. from_multi_device_runtime_projection — dispatch from first dispatch entry.
  94. from_multi_device_runtime_projection — takeovers extracted.
  95. from_multi_device_runtime_projection — coordinator from first coordinator entry.
  96. from_multi_device_runtime_projection — merged result from first merged entry.
  97. from_multi_device_runtime_projection — recovery_state extracted.
  98. from_multi_device_runtime_projection — session_id kwarg respected.
  99. from_multi_device_runtime_projection — never raises on garbage.
  100. contracts package root re-exports.
  101. core.unified package re-exports.
  102. Route GET /api/v1/projection/runtime/session-snapshot — present.
  103. Route GET /api/v1/projection/runtime/session-snapshot — returns valid JSON.
  104. Route GET /api/v1/projection/runtime/session-snapshot — stable top-level keys.
  105. Route GET /api/v1/projection/runtime/session-snapshot — graceful on failure.
  106. MultiDeviceRuntimeProjection — runtime_session_snapshot field present.
  107. MultiDeviceRuntimeProjection — runtime_session_snapshot None by default.
  108. MultiDeviceRuntimeProjection — runtime_session_snapshot populated from builder.
  109. build_multi_device_runtime_projection — runtime_session_snapshot kwarg accepted.
  110. RuntimeSessionSnapshot — metadata preserved through round-trip.
  111. RuntimeSessionSnapshotSummary — from_dict ignores extra fields.
  112. RuntimeSessionSnapshot — from_dict ignores extra fields.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest


# ---------------------------------------------------------------------------
# 1. RuntimeSessionSnapshotStatus — all expected values present
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotStatus:
    def test_all_expected_values(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotStatus

        expected = {
            "active",
            "completed",
            "failed",
            "partial",
            "interrupted",
            "recovering",
            "unknown",
        }
        actual = {m.value for m in RuntimeSessionSnapshotStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# 2–4. RuntimeSessionSnapshotIdentity
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotIdentity:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity

        obj = RuntimeSessionSnapshotIdentity(session_id="sess_001")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert parsed == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity

        fields = set(RuntimeSessionSnapshotIdentity.model_fields.keys())
        expected = {
            "snapshot_id",
            "session_id",
            "trace_id",
            "task_id",
            "mesh_session_id",
            "source_device_id",
            "primary_device_id",
            "created_at",
            "updated_at",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_snapshot_id_auto_generated(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity

        obj = RuntimeSessionSnapshotIdentity(session_id="sess")
        assert obj.snapshot_id.startswith("rsnap_")

    def test_from_dict_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity

        obj = RuntimeSessionSnapshotIdentity(session_id="sess_rt", trace_id="tr_01")
        d = obj.to_dict()
        obj2 = RuntimeSessionSnapshotIdentity.from_dict(d)
        assert obj2.snapshot_id == obj.snapshot_id
        assert obj2.session_id == obj.session_id
        assert obj2.trace_id == obj.trace_id


# ---------------------------------------------------------------------------
# 5–7. RuntimeSessionSnapshotDispatchState
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotDispatchState:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState

        obj = RuntimeSessionSnapshotDispatchState(dispatch_mode="local")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState

        fields = set(RuntimeSessionSnapshotDispatchState.model_fields.keys())
        expected = {
            "dispatch_id",
            "dispatch_mode",
            "dispatch_status",
            "target_device_ids",
            "plan_id",
            "reason",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState

        obj = RuntimeSessionSnapshotDispatchState()
        assert obj.dispatch_id is None
        assert obj.target_device_ids == []


# ---------------------------------------------------------------------------
# 8–10. RuntimeSessionSnapshotTakeoverState
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotTakeoverState:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotTakeoverState

        obj = RuntimeSessionSnapshotTakeoverState(target_device_id="dev_01")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotTakeoverState

        fields = set(RuntimeSessionSnapshotTakeoverState.model_fields.keys())
        expected = {
            "takeover_id",
            "target_device_id",
            "takeover_status",
            "session_context_id",
            "reason",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotTakeoverState

        obj = RuntimeSessionSnapshotTakeoverState()
        assert obj.takeover_id is None
        assert obj.target_device_id is None


# ---------------------------------------------------------------------------
# 11–13. RuntimeSessionSnapshotCoordinatorState
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotCoordinatorState:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotCoordinatorState

        obj = RuntimeSessionSnapshotCoordinatorState(coordinator_status="healthy")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotCoordinatorState

        fields = set(RuntimeSessionSnapshotCoordinatorState.model_fields.keys())
        expected = {
            "coordinator_id",
            "coordinator_status",
            "participant_count",
            "assignment_count",
            "barrier_active",
            "event_count",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotCoordinatorState

        obj = RuntimeSessionSnapshotCoordinatorState()
        assert obj.coordinator_id is None
        assert obj.participant_count == 0
        assert obj.barrier_active is False


# ---------------------------------------------------------------------------
# 14–16. RuntimeSessionSnapshotResultState
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotResultState:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState

        obj = RuntimeSessionSnapshotResultState(merge_status="authoritative")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState

        fields = set(RuntimeSessionSnapshotResultState.model_fields.keys())
        expected = {
            "merge_id",
            "merge_status",
            "authoritative_unit_ids",
            "stale_unit_ids",
            "pending_unit_ids",
            "result_unit_count",
            "merge_policy",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState

        obj = RuntimeSessionSnapshotResultState()
        assert obj.merge_id is None
        assert obj.authoritative_unit_ids == []
        assert obj.result_unit_count == 0


# ---------------------------------------------------------------------------
# 17–19. RuntimeSessionSnapshotRecoveryState
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotRecoveryState:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotRecoveryState

        obj = RuntimeSessionSnapshotRecoveryState(recovery_status="resolved")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotRecoveryState

        fields = set(RuntimeSessionSnapshotRecoveryState.model_fields.keys())
        expected = {
            "reconciliation_id",
            "recovery_status",
            "incident_count",
            "replay_required",
            "resume_allowed",
            "merge_confirmation_required",
            "has_barrier",
            "reason",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotRecoveryState

        obj = RuntimeSessionSnapshotRecoveryState()
        assert obj.reconciliation_id is None
        assert obj.incident_count == 0
        assert obj.replay_required is False


# ---------------------------------------------------------------------------
# 20–29. RuntimeSessionSnapshot
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshot:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot(session_id="sess_001")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert isinstance(j, str)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        fields = set(RuntimeSessionSnapshot.model_fields.keys())
        expected = {
            "snapshot_id",
            "session_id",
            "trace_id",
            "task_id",
            "mesh_session_id",
            "source_device_id",
            "primary_device_id",
            "created_at",
            "updated_at",
            "status",
            "runtime_devices",
            "runtime_hosts",
            "mesh_memberships",
            "mesh_session",
            "dispatch_state",
            "takeover_states",
            "coordinator_state",
            "merged_result",
            "recovery_state",
            "governance_snapshot",
            "policy_alignment",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_snapshot_id_auto_generated(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot()
        assert obj.snapshot_id.startswith("rsnap_")

    def test_session_id_default_empty_string(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot()
        assert obj.session_id == ""

    def test_created_at_updated_at_populated(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        before = time.time()
        obj = RuntimeSessionSnapshot()
        after = time.time()
        assert before <= obj.created_at <= after
        assert before <= obj.updated_at <= after

    def test_status_default_unknown(self):
        from contracts.runtime_session_snapshot import (
            RuntimeSessionSnapshot,
            RuntimeSessionSnapshotStatus,
        )

        obj = RuntimeSessionSnapshot()
        assert obj.status == RuntimeSessionSnapshotStatus.unknown.value

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot()
        assert obj.runtime_devices == []
        assert obj.runtime_hosts == []
        assert obj.mesh_memberships == []
        assert obj.takeover_states == []
        assert obj.dispatch_state is None
        assert obj.mesh_session is None

    def test_to_identity_returns_identity_block(self):
        from contracts.runtime_session_snapshot import (
            RuntimeSessionSnapshot,
            RuntimeSessionSnapshotIdentity,
        )

        obj = RuntimeSessionSnapshot(
            session_id="sess_id_test",
            trace_id="tr_001",
        )
        identity = obj.to_identity()
        assert isinstance(identity, RuntimeSessionSnapshotIdentity)
        assert identity.snapshot_id == obj.snapshot_id
        assert identity.session_id == obj.session_id
        assert identity.trace_id == obj.trace_id

    def test_repr_informative(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot(session_id="sess_repr")
        r = repr(obj)
        assert "RuntimeSessionSnapshot" in r
        assert "sess_repr" in r

    def test_from_dict_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot(
            session_id="sess_rt",
            trace_id="tr_rt",
            source_device_id="dev_rt",
        )
        d = obj.to_dict()
        obj2 = RuntimeSessionSnapshot.from_dict(d)
        assert obj2.snapshot_id == obj.snapshot_id
        assert obj2.session_id == obj.session_id
        assert obj2.trace_id == obj.trace_id

    def test_from_dict_ignores_extra_fields(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        d = {"session_id": "sess_extra", "snapshot_id": "rsnap_test001", "unknown_field": "ignored"}
        obj = RuntimeSessionSnapshot.from_dict(d)
        assert obj.session_id == "sess_extra"

    def test_metadata_preserved_through_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot

        obj = RuntimeSessionSnapshot(
            session_id="sess_meta",
            metadata={"env": "test", "version": 2},
        )
        d = obj.to_dict()
        obj2 = RuntimeSessionSnapshot.from_dict(d)
        assert obj2.metadata["env"] == "test"
        assert obj2.metadata["version"] == 2


# ---------------------------------------------------------------------------
# 30–34. RuntimeSessionSnapshotSummary
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotSummary:
    def test_serialisation_stability(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotSummary

        obj = RuntimeSessionSnapshotSummary(session_id="sess_001")
        d = obj.to_dict()
        j = obj.to_json()
        assert isinstance(d, dict)
        assert json.loads(j) == d

    def test_stable_field_names(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotSummary

        fields = set(RuntimeSessionSnapshotSummary.model_fields.keys())
        expected = {
            "summary_id",
            "snapshot_id",
            "session_id",
            "trace_id",
            "task_id",
            "mesh_session_id",
            "source_device_id",
            "primary_device_id",
            "status",
            "runtime_device_count",
            "runtime_host_count",
            "mesh_membership_count",
            "takeover_count",
            "has_dispatch_state",
            "has_coordinator_state",
            "has_merged_result",
            "has_recovery_state",
            "has_mesh_session",
            "has_governance_snapshot",
            "has_policy_alignment",
            "created_at",
            "updated_at",
            "generated_at",
            "metadata",
        }
        assert expected.issubset(fields)

    def test_summary_id_auto_generated(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotSummary

        obj = RuntimeSessionSnapshotSummary()
        assert obj.summary_id.startswith("rsnsum_")

    def test_empty_construction_valid(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotSummary

        obj = RuntimeSessionSnapshotSummary()
        assert obj.runtime_device_count == 0
        assert obj.has_dispatch_state is False

    def test_repr_informative(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotSummary

        obj = RuntimeSessionSnapshotSummary(session_id="sess_repr")
        r = repr(obj)
        assert "RuntimeSessionSnapshotSummary" in r
        assert "sess_repr" in r

    def test_from_dict_ignores_extra_fields(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotSummary

        d = {"session_id": "sess_ex", "summary_id": "rsnsum_test01", "zz_unknown": True}
        obj = RuntimeSessionSnapshotSummary.from_dict(d)
        assert obj.session_id == "sess_ex"


# ---------------------------------------------------------------------------
# 35–56. build_runtime_session_snapshot
# ---------------------------------------------------------------------------


class TestBuildRuntimeSessionSnapshot:
    def test_empty_inputs(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot()
        assert snap.snapshot_id.startswith("rsnap_")
        assert snap.session_id == ""

    def test_session_id_respected(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(session_id="sess_abc")
        assert snap.session_id == "sess_abc"

    def test_trace_task_mesh_ids_respected(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            session_id="s",
            trace_id="tr_001",
            task_id="task_002",
            mesh_session_id="mesh_003",
        )
        assert snap.trace_id == "tr_001"
        assert snap.task_id == "task_002"
        assert snap.mesh_session_id == "mesh_003"

    def test_device_ids_respected(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            source_device_id="phone_01",
            primary_device_id="tablet_02",
        )
        assert snap.source_device_id == "phone_01"
        assert snap.primary_device_id == "tablet_02"

    def test_explicit_snapshot_id_respected(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(snapshot_id="rsnap_explicit123")
        assert snap.snapshot_id == "rsnap_explicit123"

    def test_never_raises_on_none_inputs(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            session_id=None,  # type: ignore[arg-type]
            trace_id=None,
            runtime_devices=None,
            dispatch_state=None,
            takeover_states=None,
            recovery_state=None,
        )
        assert snap is not None

    def test_never_raises_on_bad_inputs(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            session_id=123,  # type: ignore[arg-type]
            runtime_devices="not_a_list",  # type: ignore[arg-type]
            dispatch_state="not_a_dict",  # type: ignore[arg-type]
        )
        assert snap is not None

    def test_runtime_devices_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            runtime_devices=[{"device_id": "dev_01"}, {"device_id": "dev_02"}],
        )
        assert len(snap.runtime_devices) == 2

    def test_runtime_hosts_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            runtime_hosts=[{"host_id": "host_01"}],
        )
        assert len(snap.runtime_hosts) == 1

    def test_mesh_memberships_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            mesh_memberships=[{"device_id": "dev_01", "role": "source"}],
        )
        assert len(snap.mesh_memberships) == 1

    def test_mesh_session_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            mesh_session={"session_id": "mesh_01", "status": "active"},
        )
        assert snap.mesh_session is not None
        assert snap.mesh_session["session_id"] == "mesh_01"

    def test_dispatch_state_populated_from_dict(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            dispatch_state={"mode": "cross_device", "status": "dispatched", "reason": "ok"},
        )
        assert snap.dispatch_state is not None
        assert snap.dispatch_state.dispatch_mode == "cross_device"

    def test_takeover_states_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            takeover_states=[
                {"target_device_id": "dev_01", "status": "completed"},
                {"target_device_id": "dev_02", "status": "failed"},
            ],
        )
        assert len(snap.takeover_states) == 2
        assert snap.takeover_states[0].target_device_id == "dev_01"

    def test_coordinator_state_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            coordinator_state={
                "coordinator_id": "coord_01",
                "status": "healthy",
                "participants": [{"device_id": "a"}, {"device_id": "b"}],
            },
        )
        assert snap.coordinator_state is not None
        assert snap.coordinator_state.coordinator_status == "healthy"
        assert snap.coordinator_state.participant_count == 2

    def test_merged_result_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            merged_result={
                "merge_id": "merge_01",
                "status": "authoritative",
                "result_units": [
                    {"unit_id": "u1", "status": "authoritative"},
                    {"unit_id": "u2", "status": "stale"},
                    {"unit_id": "u3", "status": "pending"},
                ],
            },
        )
        assert snap.merged_result is not None
        assert snap.merged_result.result_unit_count == 3
        assert "u1" in snap.merged_result.authoritative_unit_ids
        assert "u2" in snap.merged_result.stale_unit_ids
        assert "u3" in snap.merged_result.pending_unit_ids

    def test_recovery_state_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            recovery_state={
                "reconciliation_id": "rrec_01",
                "status": "resolved",
                "incident_count": 0,
                "replay_required": False,
                "resume_allowed": True,
                "merge_confirmation_required": False,
                "has_barrier": False,
                "reason": "all clear",
            },
        )
        assert snap.recovery_state is not None
        assert snap.recovery_state.recovery_status == "resolved"
        assert snap.recovery_state.resume_allowed is True

    def test_governance_snapshot_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            governance_snapshot={"snapshot_id": "gov_01", "posture": "ok"},
        )
        assert snap.governance_snapshot is not None
        assert snap.governance_snapshot["snapshot_id"] == "gov_01"

    def test_policy_alignment_populated(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot

        snap = build_runtime_session_snapshot(
            policy_alignment={"aligned": True, "alignment_id": "align_01"},
        )
        assert snap.policy_alignment is not None
        assert snap.policy_alignment["aligned"] is True

    def test_status_inferred_from_recovery_resolved(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            RuntimeSessionSnapshotStatus,
        )

        snap = build_runtime_session_snapshot(
            recovery_state={"status": "resolved"},
        )
        assert snap.status == RuntimeSessionSnapshotStatus.completed.value

    def test_status_inferred_from_recovery_in_progress(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            RuntimeSessionSnapshotStatus,
        )

        snap = build_runtime_session_snapshot(
            recovery_state={"status": "in_progress"},
        )
        assert snap.status == RuntimeSessionSnapshotStatus.recovering.value

    def test_status_inferred_from_merged_result_completed(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            RuntimeSessionSnapshotStatus,
        )

        snap = build_runtime_session_snapshot(
            merged_result={"status": "authoritative"},
        )
        assert snap.status == RuntimeSessionSnapshotStatus.completed.value

    def test_explicit_status_overrides_inference(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            RuntimeSessionSnapshotStatus,
        )

        snap = build_runtime_session_snapshot(
            status="active",
            recovery_state={"status": "resolved"},
        )
        assert snap.status == "active"


# ---------------------------------------------------------------------------
# 57–61. build_runtime_session_snapshot_summary
# ---------------------------------------------------------------------------


class TestBuildRuntimeSessionSnapshotSummary:
    def test_empty_snapshot(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            build_runtime_session_snapshot_summary,
        )

        snap = build_runtime_session_snapshot()
        summary = build_runtime_session_snapshot_summary(snap)
        assert summary.summary_id.startswith("rsnsum_")
        assert summary.runtime_device_count == 0

    def test_full_snapshot_counts_correct(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            build_runtime_session_snapshot_summary,
        )

        snap = build_runtime_session_snapshot(
            runtime_devices=[{"device_id": "d1"}, {"device_id": "d2"}],
            runtime_hosts=[{"host_id": "h1"}],
            mesh_memberships=[{"device_id": "d1"}],
            takeover_states=[{"target_device_id": "d2"}],
        )
        summary = build_runtime_session_snapshot_summary(snap)
        assert summary.runtime_device_count == 2
        assert summary.runtime_host_count == 1
        assert summary.mesh_membership_count == 1
        assert summary.takeover_count == 1

    def test_has_flags_set_correctly(self):
        from contracts.runtime_session_snapshot import (
            build_runtime_session_snapshot,
            build_runtime_session_snapshot_summary,
        )

        snap = build_runtime_session_snapshot(
            dispatch_state={"mode": "local"},
            coordinator_state={"status": "healthy"},
            merged_result={"status": "authoritative"},
            recovery_state={"status": "resolved"},
            mesh_session={"session_id": "ms_01"},
            governance_snapshot={"snapshot_id": "gov_01"},
            policy_alignment={"aligned": True},
        )
        summary = build_runtime_session_snapshot_summary(snap)
        assert summary.has_dispatch_state is True
        assert summary.has_coordinator_state is True
        assert summary.has_merged_result is True
        assert summary.has_recovery_state is True
        assert summary.has_mesh_session is True
        assert summary.has_governance_snapshot is True
        assert summary.has_policy_alignment is True

    def test_never_raises_on_none(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot_summary

        summary = build_runtime_session_snapshot_summary(None)
        assert summary is not None

    def test_never_raises_on_bad_input(self):
        from contracts.runtime_session_snapshot import build_runtime_session_snapshot_summary

        summary = build_runtime_session_snapshot_summary("not_a_snapshot")
        assert summary is not None


# ---------------------------------------------------------------------------
# 62–66. from_mesh_session
# ---------------------------------------------------------------------------


class TestFromMeshSession:
    def test_empty_dict(self):
        from contracts.runtime_session_snapshot import from_mesh_session

        snap = from_mesh_session({})
        assert snap is not None

    def test_none_input(self):
        from contracts.runtime_session_snapshot import from_mesh_session

        snap = from_mesh_session(None)
        assert snap is not None

    def test_mesh_session_id_populated(self):
        from contracts.runtime_session_snapshot import from_mesh_session

        snap = from_mesh_session({"session_id": "mesh_test_01"})
        assert snap.mesh_session_id == "mesh_test_01"

    def test_participants_mapped_to_runtime_devices(self):
        from contracts.runtime_session_snapshot import from_mesh_session

        snap = from_mesh_session({
            "session_id": "ms_01",
            "participants": [
                {"device_id": "dev_a"},
                {"device_id": "dev_b"},
            ],
        })
        assert len(snap.runtime_devices) == 2

    def test_never_raises_on_garbage(self):
        from contracts.runtime_session_snapshot import from_mesh_session

        snap = from_mesh_session(12345)
        assert snap is not None


# ---------------------------------------------------------------------------
# 67–71. from_source_dispatch_result
# ---------------------------------------------------------------------------


class TestFromSourceDispatchResult:
    def test_empty_dict(self):
        from contracts.runtime_session_snapshot import from_source_dispatch_result

        snap = from_source_dispatch_result({})
        assert snap is not None

    def test_none_input(self):
        from contracts.runtime_session_snapshot import from_source_dispatch_result

        snap = from_source_dispatch_result(None)
        assert snap is not None

    def test_dispatch_state_populated(self):
        from contracts.runtime_session_snapshot import from_source_dispatch_result

        snap = from_source_dispatch_result({"mode": "cross_device", "status": "dispatched"})
        assert snap.dispatch_state is not None

    def test_session_id_extracted(self):
        from contracts.runtime_session_snapshot import from_source_dispatch_result

        snap = from_source_dispatch_result({"session_id": "sess_disp_01"})
        assert snap.session_id == "sess_disp_01"

    def test_never_raises_on_garbage(self):
        from contracts.runtime_session_snapshot import from_source_dispatch_result

        snap = from_source_dispatch_result([1, 2, 3])
        assert snap is not None


# ---------------------------------------------------------------------------
# 72–76. from_target_takeover_result
# ---------------------------------------------------------------------------


class TestFromTargetTakeoverResult:
    def test_empty_dict(self):
        from contracts.runtime_session_snapshot import from_target_takeover_result

        snap = from_target_takeover_result({})
        assert snap is not None

    def test_none_input(self):
        from contracts.runtime_session_snapshot import from_target_takeover_result

        snap = from_target_takeover_result(None)
        assert snap is not None

    def test_takeover_states_populated(self):
        from contracts.runtime_session_snapshot import from_target_takeover_result

        snap = from_target_takeover_result({"status": "completed", "target_device_id": "dev_01"})
        assert len(snap.takeover_states) == 1

    def test_primary_device_id_from_target(self):
        from contracts.runtime_session_snapshot import from_target_takeover_result

        snap = from_target_takeover_result({"target_device_id": "dev_01"})
        assert snap.primary_device_id == "dev_01"

    def test_never_raises_on_garbage(self):
        from contracts.runtime_session_snapshot import from_target_takeover_result

        snap = from_target_takeover_result(True)
        assert snap is not None


# ---------------------------------------------------------------------------
# 77–81. from_result_merge
# ---------------------------------------------------------------------------


class TestFromResultMerge:
    def test_empty_dict(self):
        from contracts.runtime_session_snapshot import from_result_merge

        snap = from_result_merge({})
        assert snap is not None

    def test_none_input(self):
        from contracts.runtime_session_snapshot import from_result_merge

        snap = from_result_merge(None)
        assert snap is not None

    def test_merged_result_populated(self):
        from contracts.runtime_session_snapshot import from_result_merge

        snap = from_result_merge({"status": "authoritative", "merge_id": "m_01"})
        assert snap.merged_result is not None

    def test_session_id_extracted(self):
        from contracts.runtime_session_snapshot import from_result_merge

        snap = from_result_merge({"session_id": "sess_merge_01"})
        assert snap.session_id == "sess_merge_01"

    def test_never_raises_on_garbage(self):
        from contracts.runtime_session_snapshot import from_result_merge

        snap = from_result_merge(object())
        assert snap is not None


# ---------------------------------------------------------------------------
# 82–86. from_recovery_state
# ---------------------------------------------------------------------------


class TestFromRecoveryState:
    def test_empty_dict(self):
        from contracts.runtime_session_snapshot import from_recovery_state

        snap = from_recovery_state({})
        assert snap is not None

    def test_none_input(self):
        from contracts.runtime_session_snapshot import from_recovery_state

        snap = from_recovery_state(None)
        assert snap is not None

    def test_recovery_state_populated(self):
        from contracts.runtime_session_snapshot import from_recovery_state

        snap = from_recovery_state({"status": "resolved", "reconciliation_id": "rrec_01"})
        assert snap.recovery_state is not None
        assert snap.recovery_state.recovery_status == "resolved"

    def test_session_id_extracted(self):
        from contracts.runtime_session_snapshot import from_recovery_state

        snap = from_recovery_state({"session_id": "sess_rec_01"})
        assert snap.session_id == "sess_rec_01"

    def test_never_raises_on_garbage(self):
        from contracts.runtime_session_snapshot import from_recovery_state

        snap = from_recovery_state(42.5)
        assert snap is not None


# ---------------------------------------------------------------------------
# 87–99. from_multi_device_runtime_projection
# ---------------------------------------------------------------------------


class TestFromMultiDeviceRuntimeProjection:
    def test_empty_dict(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({})
        assert snap is not None

    def test_none_input(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection(None)
        assert snap is not None

    def test_devices_extracted(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "runtime_devices": [{"device_id": "d1"}, {"device_id": "d2"}],
        })
        assert len(snap.runtime_devices) == 2

    def test_hosts_extracted(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "runtime_hosts": [{"host_id": "h1"}],
        })
        assert len(snap.runtime_hosts) == 1

    def test_mesh_memberships_extracted(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "mesh_memberships": [{"device_id": "d1"}],
        })
        assert len(snap.mesh_memberships) == 1

    def test_mesh_session_from_first_entry(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "mesh_sessions": [{"session_id": "ms_01"}, {"session_id": "ms_02"}],
        })
        assert snap.mesh_session is not None
        assert snap.mesh_session.get("session_id") == "ms_01"

    def test_dispatch_from_first_dispatch_entry(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "source_dispatches": [{"mode": "cross_device", "status": "dispatched"}],
        })
        assert snap.dispatch_state is not None

    def test_takeovers_extracted(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "takeover_summaries": [
                {"target_device_id": "dev_01"},
                {"target_device_id": "dev_02"},
            ],
        })
        assert len(snap.takeover_states) == 2

    def test_coordinator_from_first_entry(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "coordinator_summaries": [{"coordinator_id": "coord_01", "status": "healthy"}],
        })
        assert snap.coordinator_state is not None

    def test_merged_result_from_first_entry(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "merged_results": [{"status": "authoritative"}],
        })
        assert snap.merged_result is not None

    def test_recovery_state_extracted(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({
            "runtime_recovery": {"status": "resolved"},
        })
        assert snap.recovery_state is not None

    def test_session_id_kwarg_respected(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection({}, session_id="sess_kwarg_01")
        assert snap.session_id == "sess_kwarg_01"

    def test_never_raises_on_garbage(self):
        from contracts.runtime_session_snapshot import from_multi_device_runtime_projection

        snap = from_multi_device_runtime_projection("garbage_input")
        assert snap is not None


# ---------------------------------------------------------------------------
# 100–101. Package re-exports
# ---------------------------------------------------------------------------


class TestPackageReExports:
    def test_contracts_package_root(self):
        import contracts

        exports = [
            "RuntimeSessionSnapshotStatus",
            "RuntimeSessionSnapshotIdentity",
            "RuntimeSessionSnapshotDispatchState",
            "RuntimeSessionSnapshotTakeoverState",
            "RuntimeSessionSnapshotCoordinatorState",
            "RuntimeSessionSnapshotResultState",
            "RuntimeSessionSnapshotRecoveryState",
            "RuntimeSessionSnapshot",
            "RuntimeSessionSnapshotSummary",
            "build_runtime_session_snapshot",
            "build_runtime_session_snapshot_summary",
            "session_snapshot_from_mesh_session",
            "session_snapshot_from_dispatch",
            "session_snapshot_from_takeover",
            "session_snapshot_from_merge",
            "session_snapshot_from_recovery",
            "session_snapshot_from_projection",
        ]
        for name in exports:
            assert hasattr(contracts, name), f"contracts.{name} missing"

    def test_core_unified_package(self):
        import core.unified as unified

        exports = [
            "RuntimeSessionSnapshot",
            "build_runtime_session_snapshot",
            "session_snapshot_from_projection",
        ]
        for name in exports:
            assert hasattr(unified, name), f"core.unified.{name} missing"


# ---------------------------------------------------------------------------
# 102–105. Route tests
# ---------------------------------------------------------------------------


class TestRuntimeSessionSnapshotRoute:
    def test_route_present(self):
        from core.routes.projection import create_router as create_projection_router

        router = create_projection_router()
        route_paths = [r.path for r in router.routes]
        assert "/api/v1/projection/runtime/session-snapshot" in route_paths

    def test_route_returns_valid_json(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router as create_projection_router

        app = FastAPI()
        app.include_router(create_projection_router())
        client = TestClient(app)
        response = client.get("/api/v1/projection/runtime/session-snapshot")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_route_stable_top_level_keys(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router as create_projection_router

        app = FastAPI()
        app.include_router(create_projection_router())
        client = TestClient(app)
        response = client.get("/api/v1/projection/runtime/session-snapshot")
        data = response.json()
        expected_keys = {
            "summary_id",
            "status",
            "generated_at",
        }
        for key in expected_keys:
            assert key in data, f"Key {key!r} missing from response"

    def test_route_graceful_on_failure(self):
        """Route always returns 200, never 500."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router as create_projection_router

        app = FastAPI()
        app.include_router(create_projection_router())
        client = TestClient(app)
        response = client.get("/api/v1/projection/runtime/session-snapshot")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 106–109. MultiDeviceRuntimeProjection integration
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionIntegration:
    def test_runtime_session_snapshot_field_present(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        fields = MultiDeviceRuntimeProjection.model_fields
        assert "runtime_session_snapshot" in fields

    def test_runtime_session_snapshot_none_by_default(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        proj = MultiDeviceRuntimeProjection()
        assert proj.runtime_session_snapshot is None

    def test_runtime_session_snapshot_populated(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        snap_dict = {"snapshot_id": "rsnap_test123", "session_id": "sess_01", "status": "active"}
        proj = MultiDeviceRuntimeProjection(runtime_session_snapshot=snap_dict)
        assert proj.runtime_session_snapshot is not None
        assert proj.runtime_session_snapshot["snapshot_id"] == "rsnap_test123"

    def test_build_multi_device_runtime_projection_kwarg_accepted(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        snap_dict = {"snapshot_id": "rsnap_build_test", "session_id": "sess_build"}
        proj = build_multi_device_runtime_projection(runtime_session_snapshot=snap_dict)
        assert proj.runtime_session_snapshot is not None
        assert proj.runtime_session_snapshot["snapshot_id"] == "rsnap_build_test"
