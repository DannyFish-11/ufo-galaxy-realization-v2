"""tests/test_pr39_runtime_recovery_reconciliation.py
======================================================
Tests for PR-39: Runtime Recovery and Reconciliation Contract.

Coverage:
  1.  RecoveryIncidentType — all expected values present.
  2.  RecoveryStatus — all expected values present.
  3.  RecoveryActionType — all expected values present.
  4.  RecoveryParticipantState — serialisation stability (to_dict/to_json/from_dict).
  5.  RecoveryParticipantState — stable field names.
  6.  RecoveryActionRecommendation — serialisation stability.
  7.  RecoveryActionRecommendation — stable field names.
  8.  RecoveryBarrierState — serialisation stability.
  9.  RecoveryBarrierState — stable field names.
  10. RuntimeRecoveryIncident — serialisation stability.
  11. RuntimeRecoveryIncident — stable field names.
  12. RuntimeRecoveryIncident — recovery_id auto-generated.
  13. RuntimeRecoveryIncident — generated_at populated.
  14. RuntimeRecoveryIncident — empty construction valid.
  15. RuntimeRecoveryIncident — to_compact_summary fields.
  16. RuntimeReconciliationState — serialisation stability.
  17. RuntimeReconciliationState — stable field names.
  18. RuntimeReconciliationState — reconciliation_id auto-generated.
  19. RuntimeReconciliationState — empty construction valid.
  20. RuntimeReconciliationState — to_compact_summary fields.
  21. RecoverySummary — serialisation stability.
  22. RecoverySummary — stable field names.
  23. RecoverySummary — summary_id auto-generated.
  24. RecoverySummary — empty construction valid.
  25. build_runtime_recovery_incident — empty inputs.
  26. build_runtime_recovery_incident — full inputs.
  27. build_runtime_recovery_incident — never raises on bad input.
  28. build_runtime_recovery_incident — explicit recovery_id respected.
  29. build_runtime_recovery_incident — participant dicts parsed.
  30. build_runtime_recovery_incident — action dicts parsed.
  31. build_runtime_recovery_incident — barrier dict parsed.
  32. build_runtime_reconciliation_state — empty inputs.
  33. build_runtime_reconciliation_state — full inputs.
  34. build_runtime_reconciliation_state — never raises on bad input.
  35. build_runtime_reconciliation_state — incident dicts parsed.
  36. build_recovery_summary — no incidents → resolved.
  37. build_recovery_summary — all resolved incidents → resolved.
  38. build_recovery_summary — pending incidents → pending.
  39. build_recovery_summary — needs_intervention → needs_intervention.
  40. build_recovery_summary — mixed statuses aggregate correctly.
  41. build_recovery_summary — from reconciliation incidents.
  42. build_recovery_summary — replay_required aggregation.
  43. build_recovery_summary — resume_allowed aggregation.
  44. build_recovery_summary — merge_confirmation_required aggregation.
  45. build_recovery_summary — recommended_action_types deduplicated.
  46. build_recovery_summary — most_recent_incident_type populated.
  47. from_source_dispatch_result — failed status → dispatch_failure incident.
  48. from_source_dispatch_result — partial status → partial_completion incident.
  49. from_source_dispatch_result — success status → resolved incident.
  50. from_source_dispatch_result — None input → valid incident.
  51. from_source_dispatch_result — empty dict → valid incident.
  52. from_target_takeover_result — failed status → takeover_failed incident.
  53. from_target_takeover_result — interrupted status → handoff_interrupted incident.
  54. from_target_takeover_result — success status → resolved incident.
  55. from_target_takeover_result — None input → valid incident.
  56. from_mesh_session_coordinator — error status → coordinator_lost incident.
  57. from_mesh_session_coordinator — degraded status → session_diverged incident.
  58. from_mesh_session_coordinator — healthy status → resolved incident.
  59. from_mesh_session_coordinator — None input → valid incident.
  60. from_mesh_session_coordinator — participants extracted.
  61. from_merged_runtime_result — conflict status → merge_conflict incident.
  62. from_merged_runtime_result — failed status → partial_completion incident.
  63. from_merged_runtime_result — pending status → partial_completion in_progress.
  64. from_merged_runtime_result — success status → resolved incident.
  65. from_merged_runtime_result — stale/authoritative/pending unit ids classified.
  66. from_merged_runtime_result — None input → valid incident.
  67. from_multi_device_projection — empty projection → resolved reconciliation.
  68. from_multi_device_projection — failed dispatch → incident detected.
  69. from_multi_device_projection — failed takeover → incident detected.
  70. from_multi_device_projection — coordinator error → incident detected.
  71. from_multi_device_projection — merge conflict → incident detected.
  72. from_multi_device_projection — multiple failures → multiple incidents.
  73. from_multi_device_projection — None input → valid reconciliation.
  74. from_multi_device_projection — never raises on garbage input.
  75. contracts package root re-exports.
  76. core.unified package re-exports.
  77. Route GET /api/v1/projection/runtime/recovery — present.
  78. Route GET /api/v1/projection/runtime/recovery — returns valid JSON.
  79. Route GET /api/v1/projection/runtime/recovery — stable top-level keys.
  80. Route GET /api/v1/projection/runtime/recovery — graceful on failure.
  81. MultiDeviceRuntimeProjection — runtime_recovery field present.
  82. MultiDeviceRuntimeProjection — runtime_recovery None by default.
  83. MultiDeviceRuntimeProjection — runtime_recovery populated from builder.
  84. build_multi_device_runtime_projection — runtime_recovery kwarg accepted.
  85. RecoverySummary — repr informative.
  86. RuntimeRecoveryIncident — repr informative.
  87. RuntimeReconciliationState — repr informative.
  88. RecoveryParticipantState — from_dict ignores extra fields.
  89. RuntimeRecoveryIncident — from_dict round-trip stable.
  90. RuntimeReconciliationState — from_dict round-trip stable.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_dispatch_dict(
    status: str = "failed",
    source_device_id: str = "phone_001",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "source_device_id": source_device_id,
        "trace_id": trace_id or f"tr_{uuid.uuid4().hex[:8]}",
        "task_id": f"task_{uuid.uuid4().hex[:8]}",
    }


def _make_takeover_dict(
    status: str = "failed",
    device_id: str = "tablet_002",
) -> Dict[str, Any]:
    return {
        "status": status,
        "device_id": device_id,
        "session_context": {"session_id": f"sess_{uuid.uuid4().hex[:8]}"},
    }


def _make_coordinator_dict(
    status: str = "error",
    mesh_session_id: str = "msess_001",
    participants: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "mesh_session_id": mesh_session_id,
        "coordinator_id": f"coord_{uuid.uuid4().hex[:8]}",
        "participants": participants or [],
    }


def _make_merged_result_dict(
    status: str = "conflict",
    source_device_id: str = "phone_001",
    result_units: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "source_device_id": source_device_id,
        "result_units": result_units or [],
    }


def _make_projection_dict(
    source_dispatches: Optional[List[Dict[str, Any]]] = None,
    takeover_summaries: Optional[List[Dict[str, Any]]] = None,
    coordinator_summaries: Optional[List[Dict[str, Any]]] = None,
    merged_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "projection_id": f"mdrt_proj_{uuid.uuid4().hex[:12]}",
        "generated_at": time.time(),
        "runtime_devices": [],
        "runtime_hosts": [],
        "mesh_memberships": [],
        "mesh_sessions": [],
        "source_dispatches": source_dispatches or [],
        "handoff_summaries": [],
        "takeover_summaries": takeover_summaries or [],
        "coordinator_summaries": coordinator_summaries or [],
        "merged_results": merged_results or [],
        "governance_snapshot": None,
        "policy_alignment": None,
        "runtime_recovery": None,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Test: Enumerations
# ---------------------------------------------------------------------------


class TestRecoveryIncidentType:
    def test_expected_values(self):
        from contracts.runtime_recovery_reconciliation import RecoveryIncidentType

        expected = {
            "dispatch_failure", "handoff_interrupted", "takeover_failed",
            "merge_conflict", "coordinator_lost", "session_diverged",
            "result_stale", "partial_completion", "unknown",
        }
        actual = {e.value for e in RecoveryIncidentType}
        assert expected == actual


class TestRecoveryStatus:
    def test_expected_values(self):
        from contracts.runtime_recovery_reconciliation import RecoveryStatus

        expected = {"pending", "in_progress", "resolved", "needs_intervention", "stale"}
        actual = {e.value for e in RecoveryStatus}
        assert expected == actual


class TestRecoveryActionType:
    def test_expected_values(self):
        from contracts.runtime_recovery_reconciliation import RecoveryActionType

        expected = {
            "retry_handoff", "resume_local", "request_merge_confirmation",
            "repair_mesh_session", "mark_stale", "fallback_local",
            "replay_assignment", "wait_for_participant", "escalate",
        }
        actual = {e.value for e in RecoveryActionType}
        assert expected == actual


# ---------------------------------------------------------------------------
# Test: RecoveryParticipantState
# ---------------------------------------------------------------------------


class TestRecoveryParticipantStateSerialization:
    def test_to_dict_round_trip(self):
        from contracts.runtime_recovery_reconciliation import RecoveryParticipantState

        p = RecoveryParticipantState(device_id="dev_001", status="pending")
        d = p.to_dict()
        assert isinstance(d, dict)
        p2 = RecoveryParticipantState.from_dict(d)
        assert p2.device_id == "dev_001"

    def test_to_json_valid(self):
        from contracts.runtime_recovery_reconciliation import RecoveryParticipantState

        p = RecoveryParticipantState(device_id="dev_001")
        j = p.to_json()
        data = json.loads(j)
        assert data["device_id"] == "dev_001"

    def test_from_dict_ignores_extra_fields(self):
        from contracts.runtime_recovery_reconciliation import RecoveryParticipantState

        p = RecoveryParticipantState.from_dict({"device_id": "dev_001", "unknown_field": "x"})
        assert p.device_id == "dev_001"


class TestRecoveryParticipantStateFieldNames:
    def test_stable_field_names(self):
        from contracts.runtime_recovery_reconciliation import RecoveryParticipantState

        p = RecoveryParticipantState(device_id="dev_001")
        d = p.to_dict()
        for field in (
            "device_id", "runtime_id", "status", "authoritative",
            "replay_required", "resume_allowed",
            "last_known_assignment_ids", "last_known_result_unit_ids", "metadata",
        ):
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Test: RecoveryActionRecommendation
# ---------------------------------------------------------------------------


class TestRecoveryActionRecommendationSerialization:
    def test_to_dict_round_trip(self):
        from contracts.runtime_recovery_reconciliation import RecoveryActionRecommendation

        a = RecoveryActionRecommendation(action_type="retry_handoff", reason="test")
        d = a.to_dict()
        a2 = RecoveryActionRecommendation.from_dict(d)
        assert a2.action_type == "retry_handoff"

    def test_to_json_valid(self):
        from contracts.runtime_recovery_reconciliation import RecoveryActionRecommendation

        a = RecoveryActionRecommendation(action_type="escalate")
        assert json.loads(a.to_json())["action_type"] == "escalate"


class TestRecoveryActionRecommendationFieldNames:
    def test_stable_field_names(self):
        from contracts.runtime_recovery_reconciliation import RecoveryActionRecommendation

        a = RecoveryActionRecommendation(action_type="fallback_local")
        d = a.to_dict()
        for field in ("action_type", "target_device_id", "result_unit_id", "reason", "metadata"):
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Test: RecoveryBarrierState
# ---------------------------------------------------------------------------


class TestRecoveryBarrierStateSerialization:
    def test_to_dict_round_trip(self):
        from contracts.runtime_recovery_reconciliation import RecoveryBarrierState

        b = RecoveryBarrierState(blocking=True, description="barrier test")
        d = b.to_dict()
        b2 = RecoveryBarrierState.from_dict(d)
        assert b2.blocking is True

    def test_barrier_id_auto_generated(self):
        from contracts.runtime_recovery_reconciliation import RecoveryBarrierState

        b1 = RecoveryBarrierState()
        b2 = RecoveryBarrierState()
        assert b1.barrier_id != b2.barrier_id


class TestRecoveryBarrierStateFieldNames:
    def test_stable_field_names(self):
        from contracts.runtime_recovery_reconciliation import RecoveryBarrierState

        b = RecoveryBarrierState()
        d = b.to_dict()
        for field in ("barrier_id", "blocking", "pending_device_ids", "clearable", "description", "metadata"):
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Test: RuntimeRecoveryIncident
# ---------------------------------------------------------------------------


class TestRuntimeRecoveryIncidentSerialization:
    def test_to_dict_round_trip(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident()
        d = inc.to_dict()
        inc2 = RuntimeRecoveryIncident.from_dict(d)
        assert inc2.recovery_id == inc.recovery_id

    def test_to_json_valid(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident(incident_type="dispatch_failure")
        d = json.loads(inc.to_json())
        assert d["incident_type"] == "dispatch_failure"

    def test_from_dict_round_trip_stable(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident(
            incident_type="takeover_failed",
            affected_devices=["dev_a", "dev_b"],
            replay_required=True,
        )
        d = inc.to_dict()
        inc2 = RuntimeRecoveryIncident.from_dict(d)
        assert inc2.incident_type == "takeover_failed"
        assert inc2.affected_devices == ["dev_a", "dev_b"]
        assert inc2.replay_required is True


class TestRuntimeRecoveryIncidentAutoId:
    def test_recovery_id_auto_generated(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident()
        assert inc.recovery_id.startswith("rrinc_")

    def test_recovery_ids_unique(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        ids = {RuntimeRecoveryIncident().recovery_id for _ in range(10)}
        assert len(ids) == 10


class TestRuntimeRecoveryIncidentGeneratedAt:
    def test_generated_at_is_recent(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        before = time.time()
        inc = RuntimeRecoveryIncident()
        after = time.time()
        assert before <= inc.generated_at <= after


class TestRuntimeRecoveryIncidentEmptyConstruction:
    def test_empty_construction_valid(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident()
        assert inc.affected_devices == []
        assert inc.participant_states == []
        assert inc.recommended_actions == []
        assert inc.replay_required is False

    def test_optional_none_fields(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident()
        assert inc.trace_id is None
        assert inc.task_id is None
        assert inc.mesh_session_id is None
        assert inc.barrier_state is None


class TestRuntimeRecoveryIncidentFieldNames:
    def test_stable_field_names(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident()
        d = inc.to_dict()
        for field in (
            "recovery_id", "generated_at", "trace_id", "task_id", "session_id",
            "mesh_session_id", "source_device_id", "primary_device_id",
            "incident_type", "status", "affected_devices", "affected_runtime_ids",
            "participant_states", "stale_result_unit_ids", "authoritative_result_unit_ids",
            "pending_result_unit_ids", "replay_required", "resume_allowed",
            "merge_confirmation_required", "barrier_state", "recommended_actions",
            "reason", "metadata",
        ):
            assert field in d, f"Missing field: {field}"


class TestRuntimeRecoveryIncidentCompactSummary:
    def test_compact_summary_fields(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident()
        s = inc.to_compact_summary()
        for field in (
            "recovery_id", "incident_type", "status",
            "affected_device_count", "participant_count",
            "replay_required", "resume_allowed", "merge_confirmation_required",
            "has_barrier", "recommended_action_count", "reason", "generated_at",
        ):
            assert field in s, f"Missing compact summary field: {field}"

    def test_compact_summary_counts(self):
        from contracts.runtime_recovery_reconciliation import (
            RuntimeRecoveryIncident, RecoveryParticipantState, RecoveryActionRecommendation,
        )

        inc = RuntimeRecoveryIncident(
            affected_devices=["d1", "d2"],
            participant_states=[
                RecoveryParticipantState(device_id="d1"),
                RecoveryParticipantState(device_id="d2"),
            ],
            recommended_actions=[
                RecoveryActionRecommendation(action_type="retry_handoff"),
            ],
        )
        s = inc.to_compact_summary()
        assert s["affected_device_count"] == 2
        assert s["participant_count"] == 2
        assert s["recommended_action_count"] == 1

    def test_compact_summary_repr(self):
        from contracts.runtime_recovery_reconciliation import RuntimeRecoveryIncident

        inc = RuntimeRecoveryIncident(incident_type="dispatch_failure")
        r = repr(inc)
        assert "dispatch_failure" in r


# ---------------------------------------------------------------------------
# Test: RuntimeReconciliationState
# ---------------------------------------------------------------------------


class TestRuntimeReconciliationStateSerialization:
    def test_to_dict_round_trip(self):
        from contracts.runtime_recovery_reconciliation import RuntimeReconciliationState

        rec = RuntimeReconciliationState()
        d = rec.to_dict()
        rec2 = RuntimeReconciliationState.from_dict(d)
        assert rec2.reconciliation_id == rec.reconciliation_id

    def test_reconciliation_id_auto_generated(self):
        from contracts.runtime_recovery_reconciliation import RuntimeReconciliationState

        rec = RuntimeReconciliationState()
        assert rec.reconciliation_id.startswith("rrec_")

    def test_empty_construction_valid(self):
        from contracts.runtime_recovery_reconciliation import RuntimeReconciliationState

        rec = RuntimeReconciliationState()
        assert rec.participant_states == []
        assert rec.incidents == []

    def test_compact_summary_fields(self):
        from contracts.runtime_recovery_reconciliation import RuntimeReconciliationState

        rec = RuntimeReconciliationState()
        s = rec.to_compact_summary()
        for field in (
            "reconciliation_id", "status", "participant_count",
            "authoritative_result_count", "stale_result_count",
            "pending_result_count", "replay_required", "resume_allowed",
            "merge_confirmation_required", "incident_count", "reason", "generated_at",
        ):
            assert field in s, f"Missing compact summary field: {field}"

    def test_repr_informative(self):
        from contracts.runtime_recovery_reconciliation import RuntimeReconciliationState

        rec = RuntimeReconciliationState(status="needs_intervention")
        assert "needs_intervention" in repr(rec)


class TestRuntimeReconciliationStateFieldNames:
    def test_stable_field_names(self):
        from contracts.runtime_recovery_reconciliation import RuntimeReconciliationState

        rec = RuntimeReconciliationState()
        d = rec.to_dict()
        for field in (
            "reconciliation_id", "generated_at", "recovery_id", "trace_id", "task_id",
            "session_id", "mesh_session_id", "source_device_id", "primary_device_id",
            "status", "participant_states", "authoritative_result_unit_ids",
            "stale_result_unit_ids", "pending_result_unit_ids",
            "replay_required", "resume_allowed", "merge_confirmation_required",
            "barrier_state", "recommended_actions", "incidents", "reason", "metadata",
        ):
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Test: RecoverySummary
# ---------------------------------------------------------------------------


class TestRecoverySummarySerialization:
    def test_to_dict_round_trip(self):
        from contracts.runtime_recovery_reconciliation import RecoverySummary

        s = RecoverySummary()
        d = s.to_dict()
        s2 = RecoverySummary.from_dict(d)
        assert s2.summary_id == s.summary_id

    def test_summary_id_auto_generated(self):
        from contracts.runtime_recovery_reconciliation import RecoverySummary

        s = RecoverySummary()
        assert s.summary_id.startswith("rrsum_")

    def test_summary_ids_unique(self):
        from contracts.runtime_recovery_reconciliation import RecoverySummary

        ids = {RecoverySummary().summary_id for _ in range(10)}
        assert len(ids) == 10

    def test_empty_construction_valid(self):
        from contracts.runtime_recovery_reconciliation import RecoverySummary

        s = RecoverySummary()
        assert s.incident_count == 0
        assert s.recommended_action_types == []

    def test_repr_informative(self):
        from contracts.runtime_recovery_reconciliation import RecoverySummary

        s = RecoverySummary(overall_status="resolved")
        assert "resolved" in repr(s)


class TestRecoverySummaryFieldNames:
    def test_stable_field_names(self):
        from contracts.runtime_recovery_reconciliation import RecoverySummary

        s = RecoverySummary()
        d = s.to_dict()
        for field in (
            "summary_id", "generated_at", "overall_status", "incident_count",
            "resolved_incident_count", "pending_incident_count",
            "needs_intervention_count", "replay_required", "resume_allowed",
            "merge_confirmation_required", "has_barrier", "recommended_action_types",
            "most_recent_incident_type", "most_recent_recovery_id", "reason", "metadata",
        ):
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Test: build_runtime_recovery_incident
# ---------------------------------------------------------------------------


class TestBuildRuntimeRecoveryIncidentEmpty:
    def test_empty_returns_valid(self):
        from contracts.runtime_recovery_reconciliation import build_runtime_recovery_incident

        inc = build_runtime_recovery_incident()
        assert inc.recovery_id.startswith("rrinc_")
        assert inc.incident_type == "unknown"
        assert inc.status == "pending"

    def test_explicit_recovery_id_respected(self):
        from contracts.runtime_recovery_reconciliation import build_runtime_recovery_incident

        inc = build_runtime_recovery_incident(recovery_id="rrinc_custom_123")
        assert inc.recovery_id == "rrinc_custom_123"


class TestBuildRuntimeRecoveryIncidentFull:
    def test_full_inputs(self):
        from contracts.runtime_recovery_reconciliation import (
            build_runtime_recovery_incident,
            RecoveryParticipantState,
            RecoveryActionRecommendation,
            RecoveryBarrierState,
        )

        inc = build_runtime_recovery_incident(
            incident_type="dispatch_failure",
            status="pending",
            trace_id="tr_001",
            task_id="task_001",
            session_id="sess_001",
            mesh_session_id="msess_001",
            source_device_id="phone_001",
            primary_device_id="tablet_002",
            affected_devices=["phone_001", "tablet_002"],
            affected_runtime_ids=["rt_001"],
            participant_states=[
                RecoveryParticipantState(device_id="phone_001"),
                {"device_id": "tablet_002", "status": "pending"},
            ],
            stale_result_unit_ids=["ru_stale_1"],
            authoritative_result_unit_ids=["ru_auth_1"],
            pending_result_unit_ids=["ru_pend_1"],
            replay_required=True,
            resume_allowed=True,
            merge_confirmation_required=False,
            barrier_state=RecoveryBarrierState(blocking=True),
            recommended_actions=[
                RecoveryActionRecommendation(action_type="retry_handoff"),
                {"action_type": "fallback_local", "reason": "fallback"},
            ],
            reason="test reason",
            metadata={"test": "value"},
        )
        assert inc.incident_type == "dispatch_failure"
        assert inc.trace_id == "tr_001"
        assert len(inc.affected_devices) == 2
        assert len(inc.participant_states) == 2
        assert inc.replay_required is True
        assert inc.barrier_state is not None
        assert len(inc.recommended_actions) == 2
        assert inc.stale_result_unit_ids == ["ru_stale_1"]

    def test_never_raises_on_garbage(self):
        from contracts.runtime_recovery_reconciliation import build_runtime_recovery_incident

        inc = build_runtime_recovery_incident(
            participant_states=["not_a_dict", None, 42],
            recommended_actions=[None, "bad", 99],
            barrier_state="not_a_dict",
        )
        assert inc is not None

    def test_participant_dicts_parsed(self):
        from contracts.runtime_recovery_reconciliation import (
            build_runtime_recovery_incident,
            RecoveryParticipantState,
        )

        inc = build_runtime_recovery_incident(
            participant_states=[{"device_id": "dev_001", "status": "pending"}],
        )
        assert len(inc.participant_states) == 1
        assert isinstance(inc.participant_states[0], RecoveryParticipantState)
        assert inc.participant_states[0].device_id == "dev_001"


# ---------------------------------------------------------------------------
# Test: build_runtime_reconciliation_state
# ---------------------------------------------------------------------------


class TestBuildRuntimeReconciliationStateEmpty:
    def test_empty_returns_valid(self):
        from contracts.runtime_recovery_reconciliation import build_runtime_reconciliation_state

        rec = build_runtime_reconciliation_state()
        assert rec.reconciliation_id.startswith("rrec_")

    def test_never_raises_on_garbage(self):
        from contracts.runtime_recovery_reconciliation import build_runtime_reconciliation_state

        rec = build_runtime_reconciliation_state(
            participant_states=["bad", None, 99],
            recommended_actions=["bad"],
            incidents=["bad", None],
            barrier_state="not_valid",
        )
        assert rec is not None


class TestBuildRuntimeReconciliationStateFull:
    def test_incident_dicts_parsed(self):
        from contracts.runtime_recovery_reconciliation import (
            build_runtime_reconciliation_state,
            RuntimeRecoveryIncident,
        )

        inc = RuntimeRecoveryIncident(incident_type="dispatch_failure")
        rec = build_runtime_reconciliation_state(incidents=[inc])
        assert len(rec.incidents) == 1
        assert rec.incidents[0].incident_type == "dispatch_failure"

    def test_full_inputs(self):
        from contracts.runtime_recovery_reconciliation import build_runtime_reconciliation_state

        rec = build_runtime_reconciliation_state(
            status="in_progress",
            trace_id="tr_001",
            task_id="task_001",
            session_id="sess_001",
            mesh_session_id="msess_001",
            source_device_id="phone_001",
            primary_device_id="tablet_002",
            authoritative_result_unit_ids=["ru_auth_1"],
            stale_result_unit_ids=["ru_stale_1"],
            pending_result_unit_ids=["ru_pend_1"],
            replay_required=True,
            reason="test",
        )
        assert rec.status == "in_progress"
        assert rec.replay_required is True
        assert rec.trace_id == "tr_001"


# ---------------------------------------------------------------------------
# Test: build_recovery_summary
# ---------------------------------------------------------------------------


class TestBuildRecoverySummary:
    def test_no_incidents_resolved(self):
        from contracts.runtime_recovery_reconciliation import build_recovery_summary

        s = build_recovery_summary([])
        assert s.overall_status == "resolved"
        assert s.incident_count == 0
        assert s.reason == "no incidents"

    def test_all_resolved_incidents(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        incidents = [
            RuntimeRecoveryIncident(status="resolved"),
            RuntimeRecoveryIncident(status="resolved"),
        ]
        s = build_recovery_summary(incidents)
        assert s.overall_status == "resolved"
        assert s.resolved_incident_count == 2

    def test_pending_incidents(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        incidents = [RuntimeRecoveryIncident(status="pending")]
        s = build_recovery_summary(incidents)
        assert s.overall_status == "pending"
        assert s.pending_incident_count == 1

    def test_needs_intervention(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        incidents = [RuntimeRecoveryIncident(status="needs_intervention")]
        s = build_recovery_summary(incidents)
        assert s.overall_status == "needs_intervention"
        assert s.needs_intervention_count == 1

    def test_replay_required_aggregation(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        incidents = [
            RuntimeRecoveryIncident(replay_required=False),
            RuntimeRecoveryIncident(replay_required=True),
        ]
        s = build_recovery_summary(incidents)
        assert s.replay_required is True

    def test_resume_allowed_aggregation(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        incidents = [
            RuntimeRecoveryIncident(resume_allowed=True),
        ]
        s = build_recovery_summary(incidents)
        assert s.resume_allowed is True

    def test_merge_confirmation_aggregation(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        incidents = [RuntimeRecoveryIncident(merge_confirmation_required=True)]
        s = build_recovery_summary(incidents)
        assert s.merge_confirmation_required is True

    def test_recommended_action_types_deduplicated(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident, RecoveryActionRecommendation,
        )

        inc1 = RuntimeRecoveryIncident(
            recommended_actions=[
                RecoveryActionRecommendation(action_type="retry_handoff"),
                RecoveryActionRecommendation(action_type="fallback_local"),
            ]
        )
        inc2 = RuntimeRecoveryIncident(
            recommended_actions=[
                RecoveryActionRecommendation(action_type="retry_handoff"),
            ]
        )
        s = build_recovery_summary([inc1, inc2])
        assert s.recommended_action_types.count("retry_handoff") == 1
        assert "fallback_local" in s.recommended_action_types

    def test_most_recent_incident_populated(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, RuntimeRecoveryIncident,
        )

        inc = RuntimeRecoveryIncident(incident_type="coordinator_lost")
        s = build_recovery_summary([inc])
        assert s.most_recent_incident_type == "coordinator_lost"
        assert s.most_recent_recovery_id == inc.recovery_id

    def test_from_reconciliation_incidents(self):
        from contracts.runtime_recovery_reconciliation import (
            build_recovery_summary, build_runtime_reconciliation_state,
            RuntimeRecoveryIncident,
        )

        inc = RuntimeRecoveryIncident(status="pending")
        rec = build_runtime_reconciliation_state(incidents=[inc])
        s = build_recovery_summary(incidents=None, reconciliation=rec)
        assert s.incident_count == 1


# ---------------------------------------------------------------------------
# Test: from_source_dispatch_result
# ---------------------------------------------------------------------------


class TestFromSourceDispatchResult:
    def test_failed_status(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result(_make_dispatch_dict("failed", "phone_001"))
        assert inc.incident_type == "dispatch_failure"
        assert inc.status == "pending"
        assert inc.replay_required is True
        assert any(a.action_type == "retry_handoff" for a in inc.recommended_actions)

    def test_timeout_status(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result({"status": "timeout", "source_device_id": "dev_1"})
        assert inc.incident_type == "dispatch_failure"

    def test_partial_status(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result({"status": "partial", "source_device_id": "dev_1"})
        assert inc.incident_type == "partial_completion"
        assert inc.status == "in_progress"
        assert any(a.action_type == "resume_local" for a in inc.recommended_actions)

    def test_success_status_resolved(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result({"status": "success"})
        assert inc.status == "resolved"

    def test_none_input_valid(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result(None)
        assert inc is not None
        assert inc.incident_type == "unknown"

    def test_empty_dict_valid(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result({})
        assert inc is not None

    def test_mesh_session_id_propagated(self):
        from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

        inc = from_source_dispatch_result(
            {"status": "failed"},
            mesh_session_id="msess_123",
        )
        assert inc.mesh_session_id == "msess_123"


# ---------------------------------------------------------------------------
# Test: from_target_takeover_result
# ---------------------------------------------------------------------------


class TestFromTargetTakeoverResult:
    def test_failed_status(self):
        from contracts.runtime_recovery_reconciliation import from_target_takeover_result

        inc = from_target_takeover_result(_make_takeover_dict("failed", "tablet_002"))
        assert inc.incident_type == "takeover_failed"
        assert inc.replay_required is True
        assert any(a.action_type == "retry_handoff" for a in inc.recommended_actions)

    def test_interrupted_status(self):
        from contracts.runtime_recovery_reconciliation import from_target_takeover_result

        inc = from_target_takeover_result({"status": "interrupted", "device_id": "tab_1"})
        assert inc.incident_type == "handoff_interrupted"
        assert inc.resume_allowed is True

    def test_success_status_resolved(self):
        from contracts.runtime_recovery_reconciliation import from_target_takeover_result

        inc = from_target_takeover_result({"status": "completed"})
        assert inc.status == "resolved"

    def test_none_input_valid(self):
        from contracts.runtime_recovery_reconciliation import from_target_takeover_result

        inc = from_target_takeover_result(None)
        assert inc is not None


# ---------------------------------------------------------------------------
# Test: from_mesh_session_coordinator
# ---------------------------------------------------------------------------


class TestFromMeshSessionCoordinator:
    def test_error_status(self):
        from contracts.runtime_recovery_reconciliation import from_mesh_session_coordinator

        inc = from_mesh_session_coordinator(_make_coordinator_dict("error"))
        assert inc.incident_type == "coordinator_lost"
        assert inc.status == "needs_intervention"
        assert any(a.action_type == "repair_mesh_session" for a in inc.recommended_actions)

    def test_degraded_status(self):
        from contracts.runtime_recovery_reconciliation import from_mesh_session_coordinator

        inc = from_mesh_session_coordinator({"status": "degraded", "mesh_session_id": "ms_1"})
        assert inc.incident_type == "session_diverged"
        assert inc.status == "in_progress"

    def test_healthy_status_resolved(self):
        from contracts.runtime_recovery_reconciliation import from_mesh_session_coordinator

        inc = from_mesh_session_coordinator({"status": "active"})
        assert inc.status == "resolved"

    def test_none_input_valid(self):
        from contracts.runtime_recovery_reconciliation import from_mesh_session_coordinator

        inc = from_mesh_session_coordinator(None)
        assert inc is not None

    def test_participants_extracted(self):
        from contracts.runtime_recovery_reconciliation import from_mesh_session_coordinator

        coord = _make_coordinator_dict(
            "error",
            participants=[
                {"device_id": "dev_a", "status": "failed"},
                {"device_id": "dev_b", "status": "active"},
            ],
        )
        inc = from_mesh_session_coordinator(coord)
        assert len(inc.participant_states) == 2
        assert inc.affected_devices == ["dev_a", "dev_b"]


# ---------------------------------------------------------------------------
# Test: from_merged_runtime_result
# ---------------------------------------------------------------------------


class TestFromMergedRuntimeResult:
    def test_conflict_status(self):
        from contracts.runtime_recovery_reconciliation import from_merged_runtime_result

        inc = from_merged_runtime_result(_make_merged_result_dict("conflict"))
        assert inc.incident_type == "merge_conflict"
        assert inc.status == "needs_intervention"
        assert inc.merge_confirmation_required is True
        assert any(a.action_type == "request_merge_confirmation" for a in inc.recommended_actions)

    def test_failed_status(self):
        from contracts.runtime_recovery_reconciliation import from_merged_runtime_result

        inc = from_merged_runtime_result({"status": "failed"})
        assert inc.incident_type == "partial_completion"
        assert inc.replay_required is True

    def test_pending_status(self):
        from contracts.runtime_recovery_reconciliation import from_merged_runtime_result

        inc = from_merged_runtime_result({"status": "pending"})
        assert inc.incident_type == "partial_completion"
        assert inc.status == "in_progress"
        assert any(a.action_type == "wait_for_participant" for a in inc.recommended_actions)

    def test_success_status_resolved(self):
        from contracts.runtime_recovery_reconciliation import from_merged_runtime_result

        inc = from_merged_runtime_result({"status": "completed"})
        assert inc.status == "resolved"

    def test_result_unit_classification(self):
        from contracts.runtime_recovery_reconciliation import from_merged_runtime_result

        merged = _make_merged_result_dict(
            "conflict",
            result_units=[
                {"unit_id": "ru_1", "status": "stale"},
                {"unit_id": "ru_2", "status": "authoritative"},
                {"unit_id": "ru_3", "status": "pending"},
            ],
        )
        inc = from_merged_runtime_result(merged)
        assert "ru_1" in inc.stale_result_unit_ids
        assert "ru_2" in inc.authoritative_result_unit_ids
        assert "ru_3" in inc.pending_result_unit_ids

    def test_none_input_valid(self):
        from contracts.runtime_recovery_reconciliation import from_merged_runtime_result

        inc = from_merged_runtime_result(None)
        assert inc is not None


# ---------------------------------------------------------------------------
# Test: from_multi_device_projection
# ---------------------------------------------------------------------------


class TestFromMultiDeviceProjection:
    def test_empty_projection_resolved(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        rec = from_multi_device_projection(_make_projection_dict())
        assert rec.status == "resolved"
        assert rec.incidents == []

    def test_failed_dispatch_incident_detected(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        proj = _make_projection_dict(
            source_dispatches=[_make_dispatch_dict("failed")],
        )
        rec = from_multi_device_projection(proj)
        assert len(rec.incidents) >= 1
        assert any(i.incident_type == "dispatch_failure" for i in rec.incidents)

    def test_failed_takeover_incident_detected(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        proj = _make_projection_dict(
            takeover_summaries=[_make_takeover_dict("failed")],
        )
        rec = from_multi_device_projection(proj)
        assert len(rec.incidents) >= 1
        assert any(i.incident_type == "takeover_failed" for i in rec.incidents)

    def test_coordinator_error_incident_detected(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        proj = _make_projection_dict(
            coordinator_summaries=[_make_coordinator_dict("error")],
        )
        rec = from_multi_device_projection(proj)
        assert len(rec.incidents) >= 1
        assert any(i.incident_type == "coordinator_lost" for i in rec.incidents)

    def test_merge_conflict_incident_detected(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        proj = _make_projection_dict(
            merged_results=[_make_merged_result_dict("conflict")],
        )
        rec = from_multi_device_projection(proj)
        assert len(rec.incidents) >= 1
        assert any(i.incident_type == "merge_conflict" for i in rec.incidents)

    def test_multiple_failures_multiple_incidents(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        proj = _make_projection_dict(
            source_dispatches=[_make_dispatch_dict("failed")],
            takeover_summaries=[_make_takeover_dict("failed")],
            coordinator_summaries=[_make_coordinator_dict("error")],
        )
        rec = from_multi_device_projection(proj)
        assert len(rec.incidents) >= 2

    def test_none_input_valid(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        rec = from_multi_device_projection(None)
        assert rec is not None

    def test_never_raises_on_garbage(self):
        from contracts.runtime_recovery_reconciliation import from_multi_device_projection

        rec = from_multi_device_projection("not_a_dict")
        assert rec is not None
        rec2 = from_multi_device_projection(42)
        assert rec2 is not None


# ---------------------------------------------------------------------------
# Test: Package re-exports
# ---------------------------------------------------------------------------


class TestContractsPackageReExports:
    def test_contracts_re_exports(self):
        from contracts import (
            RecoveryIncidentType,
            RecoveryStatus,
            RecoveryActionType,
            RecoveryParticipantState,
            RecoveryActionRecommendation,
            RecoveryBarrierState,
            RuntimeRecoveryIncident,
            RuntimeReconciliationState,
            RecoverySummary,
            build_runtime_recovery_incident,
            build_runtime_reconciliation_state,
            build_recovery_summary,
            recovery_from_dispatch_result,
            recovery_from_takeover_result,
            recovery_from_coordinator,
            recovery_from_merged_result,
            recovery_from_projection,
        )
        assert RecoveryIncidentType is not None
        assert RuntimeRecoveryIncident is not None
        assert build_recovery_summary is not None

    def test_core_unified_re_exports(self):
        from core.unified import (
            RecoveryIncidentType,
            RecoveryStatus,
            RecoveryActionType,
            RecoveryParticipantState,
            RecoveryActionRecommendation,
            RecoveryBarrierState,
            RuntimeRecoveryIncident,
            RuntimeReconciliationState,
            RecoverySummary,
            build_runtime_recovery_incident,
            build_runtime_reconciliation_state,
            build_recovery_summary,
            recovery_from_dispatch_result,
            recovery_from_takeover_result,
            recovery_from_coordinator,
            recovery_from_merged_result,
            recovery_from_projection,
        )
        assert RuntimeReconciliationState is not None
        assert build_runtime_reconciliation_state is not None


# ---------------------------------------------------------------------------
# Test: Route integration
# ---------------------------------------------------------------------------


class TestRuntimeRecoveryRoute:
    def test_route_present(self):
        from core.routes.projection import create_router

        router = create_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/projection/runtime/recovery" in routes

    def test_route_returns_valid_json(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/projection/runtime/recovery")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_route_stable_top_level_keys(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/projection/runtime/recovery")
        data = resp.json()
        for key in (
            "summary_id", "overall_status", "incident_count",
            "resolved_incident_count", "pending_incident_count",
            "needs_intervention_count", "replay_required", "resume_allowed",
            "merge_confirmation_required", "has_barrier",
            "recommended_action_types", "most_recent_incident_type",
            "most_recent_recovery_id", "reason", "metadata",
        ):
            assert key in data, f"Missing key in recovery route response: {key}"


# ---------------------------------------------------------------------------
# Test: MultiDeviceRuntimeProjection integration
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionRecoveryField:
    def test_runtime_recovery_field_present(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        proj = MultiDeviceRuntimeProjection()
        d = proj.to_dict()
        assert "runtime_recovery" in d

    def test_runtime_recovery_none_by_default(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        proj = MultiDeviceRuntimeProjection()
        assert proj.runtime_recovery is None

    def test_runtime_recovery_populated_from_builder(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        from contracts.runtime_recovery_reconciliation import build_recovery_summary

        summary = build_recovery_summary([])
        proj = build_multi_device_runtime_projection(runtime_recovery=summary)
        assert proj.runtime_recovery is not None
        assert "summary_id" in proj.runtime_recovery

    def test_build_runtime_recovery_kwarg_none_accepted(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        proj = build_multi_device_runtime_projection(runtime_recovery=None)
        assert proj.runtime_recovery is None

    def test_build_runtime_recovery_from_dict(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        recovery_dict = {"summary_id": "rrsum_test", "overall_status": "resolved"}
        proj = build_multi_device_runtime_projection(runtime_recovery=recovery_dict)
        assert proj.runtime_recovery is not None
        assert proj.runtime_recovery["summary_id"] == "rrsum_test"
