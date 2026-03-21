"""tests/test_pr36_cross_runtime_result_merge.py
=================================================
Tests for PR-36: Cross-Runtime Result Merge Contract.

Coverage:
  1.  RuntimeResultRole — all enum values present.
  2.  RuntimeResultStatus — all enum values present.
  3.  ResultMergePolicy — all enum values present.
  4.  RuntimeResultProvenance — serialisation stability.
  5.  RuntimeResultUnit — serialisation stability (to_dict/to_json/from_dict).
  6.  RuntimeResultUnit — stable field names.
  7.  RuntimeResultUnit — result_unit_id is UUID4.
  8.  ResultMergeInput — serialisation stability.
  9.  ResultMergeInput — stable field names.
  10. MergedRuntimeResult — serialisation stability (to_dict/to_json/from_dict).
  11. MergedRuntimeResult — stable field names.
  12. MergedRuntimeResult — to_compact_summary helper.
  13. ResultMergeSummary — serialisation stability.
  14. ResultMergeSummary — stable field names.
  15. from_local_takeover_result — adapter from dict.
  16. from_local_takeover_result — adapter from object with to_dict.
  17. from_local_takeover_result — graceful handling of None/empty.
  18. from_source_dispatch_result — adapter from dict.
  19. from_source_dispatch_result — adapter from object with to_dict.
  20. from_source_dispatch_result — graceful handling of None/empty.
  21. from_execution_output — local success path.
  22. from_execution_output — local failure path.
  23. from_execution_output — blocked / readiness_gate path.
  24. from_execution_output — graceful with None input.
  25. build_merged_runtime_result — convenience factory.
  26. build_merged_runtime_result — never raises on bad input.
  27. merge_runtime_results — local-only (single unit, primary_wins).
  28. merge_runtime_results — remote-only (single target unit).
  29. merge_runtime_results — primary_wins with two units (one failed).
  30. merge_runtime_results — first_success policy.
  31. merge_runtime_results — last_success policy.
  32. merge_runtime_results — all_required policy, all succeed.
  33. merge_runtime_results — all_required policy, one fails.
  34. merge_runtime_results — best_effort policy.
  35. merge_runtime_results — fallback_chain policy.
  36. merge_runtime_results — fallback used when primary fails.
  37. merge_runtime_results — empty units list.
  38. merge_runtime_results — graceful with None units.
  39. merge_runtime_results — conflict detection.
  40. build_result_merge_summary — from MergedRuntimeResult.
  41. build_result_merge_summary — direct kwargs.
  42. build_result_merge_summary — never raises.
  43. contracts package root re-exports.
  44. core.unified package re-exports.
  45. core.runtime package re-exports.
  46. Projection endpoint — GET /api/v1/runtime/result-merge-summary (additive).
  47. MergedRuntimeResult.from_dict round-trip with all fields.
  48. Graceful handling of missing provenance/context.
  49. Provenance refs collected from units.
  50. from_local_takeover_result + from_source_dispatch_result combined merge.
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


def _make_takeover_result_dict(
    success: bool = True,
    trace_id: str = "trace_001",
    task_id: str = "task_001",
    session_id: str = "sess_001",
    status: str = "succeeded",
    result: Optional[Dict[str, Any]] = None,
    errors: Optional[list] = None,
    reason: Optional[str] = None,
) -> dict:
    return {
        "result_id": str(uuid.uuid4()),
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "runtime_session_id": "runtime_sess_001",
        "success": success,
        "status": status,
        "result": result or {"action_taken": "click", "success": success},
        "execution_trace": {
            "trace_id": trace_id,
            "snapshot_id": "snapshot_001",
        },
        "governance_snapshot": {
            "snapshot_id": "gov_001",
            "execution_allowed": True,
        },
        "policy_alignment": {
            "alignment_id": "policy_001",
            "aligned": True,
            "blocked": False,
        },
        "session_context": None,
        "errors": errors or [],
        "reason": reason,
        "timestamp": 1700000000.0,
        "metadata": {},
    }


def _make_dispatch_result_dict(
    success: bool = True,
    trace_id: str = "trace_001",
    task_id: str = "task_001",
    session_id: str = "sess_001",
    mode: str = "local",
    source_device_id: str = "device_src",
    errors: Optional[list] = None,
    decision_reason: str = "default_local",
) -> dict:
    return {
        "result_id": str(uuid.uuid4()),
        "dispatch_id": str(uuid.uuid4()),
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "source_device_id": source_device_id,
        "source_runtime_id": "runtime_src",
        "mode": mode,
        "selected_target": None,
        "success": success,
        "result": {"output": "done"} if success else None,
        "execution_trace": {
            "trace_id": trace_id,
        },
        "takeover_result": None,
        "governance_snapshot": {
            "snapshot_id": "gov_002",
        },
        "policy_alignment": {
            "alignment_id": "policy_002",
        },
        "mesh_session": None,
        "errors": errors or [],
        "decision_reason": decision_reason,
        "timestamp": 1700000000.0,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# 1. RuntimeResultRole — enum values
# ---------------------------------------------------------------------------


class TestRuntimeResultRoleEnum:
    def test_all_values_present(self):
        from contracts.cross_runtime_result_merge import RuntimeResultRole

        expected = {"source", "target", "primary", "support", "fallback", "partial", "unknown"}
        actual = {r.value for r in RuntimeResultRole}
        assert expected == actual

    def test_enum_values_are_strings(self):
        from contracts.cross_runtime_result_merge import RuntimeResultRole

        for role in RuntimeResultRole:
            assert isinstance(role.value, str)


# ---------------------------------------------------------------------------
# 2. RuntimeResultStatus — enum values
# ---------------------------------------------------------------------------


class TestRuntimeResultStatusEnum:
    def test_all_values_present(self):
        from contracts.cross_runtime_result_merge import RuntimeResultStatus

        expected = {"succeeded", "failed", "partial", "blocked", "skipped", "timeout", "unknown"}
        actual = {s.value for s in RuntimeResultStatus}
        assert expected == actual


# ---------------------------------------------------------------------------
# 3. ResultMergePolicy — enum values
# ---------------------------------------------------------------------------


class TestResultMergePolicyEnum:
    def test_all_values_present(self):
        from contracts.cross_runtime_result_merge import ResultMergePolicy

        expected = {
            "primary_wins", "first_success", "last_success",
            "all_required", "best_effort", "fallback_chain", "unknown",
        }
        actual = {p.value for p in ResultMergePolicy}
        assert expected == actual


# ---------------------------------------------------------------------------
# 4. RuntimeResultProvenance — serialisation
# ---------------------------------------------------------------------------


class TestRuntimeResultProvenance:
    def test_to_dict_returns_dict(self):
        from contracts.cross_runtime_result_merge import RuntimeResultProvenance

        p = RuntimeResultProvenance(
            device_id="device_001",
            runtime_id="runtime_001",
            session_id="sess_001",
            trace_id="trace_001",
            execution_path="local",
        )
        d = p.to_dict()
        assert isinstance(d, dict)
        assert d["device_id"] == "device_001"
        assert d["execution_path"] == "local"

    def test_all_fields_optional(self):
        from contracts.cross_runtime_result_merge import RuntimeResultProvenance

        p = RuntimeResultProvenance()
        d = p.to_dict()
        assert d["device_id"] is None
        assert d["runtime_id"] is None
        assert d["trace_id"] is None


# ---------------------------------------------------------------------------
# 5. RuntimeResultUnit — serialisation stability
# ---------------------------------------------------------------------------


class TestRuntimeResultUnitSerialisation:
    def test_to_dict_returns_dict(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit, RuntimeResultRole, RuntimeResultStatus

        u = RuntimeResultUnit(
            role=RuntimeResultRole.primary,
            status=RuntimeResultStatus.succeeded,
            output={"action_taken": "click"},
        )
        d = u.to_dict()
        assert isinstance(d, dict)

    def test_to_json_is_valid_json(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit

        u = RuntimeResultUnit()
        j = u.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_from_dict_round_trip(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit, RuntimeResultRole, RuntimeResultStatus

        original = RuntimeResultUnit(
            role=RuntimeResultRole.target,
            status=RuntimeResultStatus.failed,
            trace_id="trace_abc",
            task_id="task_rt",
            error="executor_unavailable",
        )
        d = original.to_dict()
        restored = RuntimeResultUnit.from_dict(d)
        assert restored.trace_id == "trace_abc"
        assert restored.task_id == "task_rt"
        assert restored.role == RuntimeResultRole.target
        assert restored.status == RuntimeResultStatus.failed
        assert restored.error == "executor_unavailable"

    def test_to_json_indent(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit

        u = RuntimeResultUnit(trace_id="t1")
        j = u.to_json(indent=2)
        assert "\n" in j


# ---------------------------------------------------------------------------
# 6. RuntimeResultUnit — stable field names
# ---------------------------------------------------------------------------


class TestRuntimeResultUnitFieldNames:
    REQUIRED_FIELDS = [
        "result_unit_id", "device_id", "runtime_id", "role", "status",
        "output", "error", "reason", "trace_id", "task_id", "session_id",
        "mesh_session_id", "execution_trace", "governance_snapshot",
        "policy_alignment", "provenance", "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit

        d = RuntimeResultUnit().to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"

    def test_role_serialised_as_string(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit, RuntimeResultRole

        d = RuntimeResultUnit(role=RuntimeResultRole.source).to_dict()
        assert d["role"] == "source"

    def test_status_serialised_as_string(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit, RuntimeResultStatus

        d = RuntimeResultUnit(status=RuntimeResultStatus.succeeded).to_dict()
        assert d["status"] == "succeeded"


# ---------------------------------------------------------------------------
# 7. RuntimeResultUnit — result_unit_id is UUID4
# ---------------------------------------------------------------------------


class TestRuntimeResultUnitId:
    def test_result_unit_id_is_uuid4(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit

        u = RuntimeResultUnit()
        uuid.UUID(u.result_unit_id)  # should not raise

    def test_timestamp_is_float(self):
        from contracts.cross_runtime_result_merge import RuntimeResultUnit

        u = RuntimeResultUnit()
        assert isinstance(u.timestamp, float)
        assert u.timestamp > 0


# ---------------------------------------------------------------------------
# 8. ResultMergeInput — serialisation stability
# ---------------------------------------------------------------------------


class TestResultMergeInputSerialisation:
    def test_to_dict(self):
        from contracts.cross_runtime_result_merge import ResultMergeInput, ResultMergePolicy

        inp = ResultMergeInput(
            merge_policy=ResultMergePolicy.first_success,
            trace_id="trace_merge",
        )
        d = inp.to_dict()
        assert isinstance(d, dict)
        assert d["merge_policy"] == "first_success"

    def test_to_json_valid(self):
        from contracts.cross_runtime_result_merge import ResultMergeInput

        inp = ResultMergeInput()
        j = inp.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict_round_trip(self):
        from contracts.cross_runtime_result_merge import ResultMergeInput, ResultMergePolicy

        original = ResultMergeInput(
            trace_id="trace_rt",
            merge_policy=ResultMergePolicy.all_required,
            merge_reason="coordinator_merge",
        )
        restored = ResultMergeInput.from_dict(original.to_dict())
        assert restored.trace_id == "trace_rt"
        assert restored.merge_policy == ResultMergePolicy.all_required
        assert restored.merge_reason == "coordinator_merge"


# ---------------------------------------------------------------------------
# 9. ResultMergeInput — stable field names
# ---------------------------------------------------------------------------


class TestResultMergeInputFieldNames:
    REQUIRED_FIELDS = [
        "merge_id", "trace_id", "task_id", "session_id", "mesh_session_id",
        "result_units", "merge_policy", "primary_result_unit_id",
        "execution_trace_refs", "governance_snapshot_refs", "policy_alignment_refs",
        "merge_reason", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.cross_runtime_result_merge import ResultMergeInput

        d = ResultMergeInput().to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 10. MergedRuntimeResult — serialisation stability
# ---------------------------------------------------------------------------


class TestMergedRuntimeResultSerialisation:
    def test_to_dict(self):
        from contracts.cross_runtime_result_merge import MergedRuntimeResult, ResultMergePolicy

        r = MergedRuntimeResult(
            merge_policy=ResultMergePolicy.primary_wins,
            success=True,
            merged_output={"done": True},
        )
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["success"] is True

    def test_to_json_valid(self):
        from contracts.cross_runtime_result_merge import MergedRuntimeResult

        r = MergedRuntimeResult()
        j = r.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict_round_trip(self):
        from contracts.cross_runtime_result_merge import MergedRuntimeResult, ResultMergePolicy

        original = MergedRuntimeResult(
            trace_id="trace_merge",
            task_id="task_merge",
            session_id="sess_merge",
            merge_policy=ResultMergePolicy.best_effort,
            success=True,
            partial=True,
            fallback_applied=False,
            merge_reason="multi_device_merge",
        )
        restored = MergedRuntimeResult.from_dict(original.to_dict())
        assert restored.trace_id == "trace_merge"
        assert restored.task_id == "task_merge"
        assert restored.merge_policy == ResultMergePolicy.best_effort
        assert restored.success is True
        assert restored.partial is True
        assert restored.merge_reason == "multi_device_merge"


# ---------------------------------------------------------------------------
# 11. MergedRuntimeResult — stable field names
# ---------------------------------------------------------------------------


class TestMergedRuntimeResultFieldNames:
    REQUIRED_FIELDS = [
        "merge_id", "trace_id", "task_id", "session_id", "mesh_session_id",
        "result_units", "primary_result_unit_id", "merge_policy", "merged_output",
        "success", "partial", "fallback_applied", "conflicts",
        "execution_trace_refs", "governance_snapshot_refs", "policy_alignment_refs",
        "merge_reason", "errors", "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.cross_runtime_result_merge import MergedRuntimeResult

        d = MergedRuntimeResult().to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 12. MergedRuntimeResult — to_compact_summary
# ---------------------------------------------------------------------------


class TestMergedRuntimeResultCompactSummary:
    def test_compact_summary_fields(self):
        from contracts.cross_runtime_result_merge import MergedRuntimeResult, ResultMergePolicy

        r = MergedRuntimeResult(
            trace_id="trace_cs",
            merge_policy=ResultMergePolicy.primary_wins,
            success=True,
            partial=False,
            fallback_applied=False,
            merged_output={"done": True},
            merge_reason="test_merge",
        )
        s = r.to_compact_summary()
        assert s["trace_id"] == "trace_cs"
        assert s["merge_policy"] == "primary_wins"
        assert s["success"] is True
        assert s["has_merged_output"] is True
        assert s["merge_reason"] == "test_merge"
        assert "unit_count" in s
        assert "conflict_count" in s
        assert "error_count" in s


# ---------------------------------------------------------------------------
# 13. ResultMergeSummary — serialisation stability
# ---------------------------------------------------------------------------


class TestResultMergeSummarySerialisation:
    def test_to_dict(self):
        from contracts.cross_runtime_result_merge import ResultMergeSummary, ResultMergePolicy

        s = ResultMergeSummary(
            merge_policy=ResultMergePolicy.primary_wins,
            success=True,
            unit_count=2,
            succeeded_unit_count=1,
        )
        d = s.to_dict()
        assert isinstance(d, dict)
        assert d["merge_policy"] == "primary_wins"
        assert d["success"] is True
        assert d["unit_count"] == 2

    def test_to_json_valid(self):
        from contracts.cross_runtime_result_merge import ResultMergeSummary

        s = ResultMergeSummary()
        j = s.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict_round_trip(self):
        from contracts.cross_runtime_result_merge import ResultMergeSummary, ResultMergePolicy

        original = ResultMergeSummary(
            merge_id="merge_001",
            trace_id="trace_s",
            merge_policy=ResultMergePolicy.fallback_chain,
            success=True,
            fallback_applied=True,
            merge_reason="fallback_used",
        )
        restored = ResultMergeSummary.from_dict(original.to_dict())
        assert restored.merge_id == "merge_001"
        assert restored.trace_id == "trace_s"
        assert restored.merge_policy == ResultMergePolicy.fallback_chain
        assert restored.success is True
        assert restored.fallback_applied is True


# ---------------------------------------------------------------------------
# 14. ResultMergeSummary — stable field names
# ---------------------------------------------------------------------------


class TestResultMergeSummaryFieldNames:
    REQUIRED_FIELDS = [
        "summary_id", "merge_id", "trace_id", "task_id", "session_id",
        "merge_policy", "success", "partial", "fallback_applied",
        "unit_count", "succeeded_unit_count", "failed_unit_count",
        "conflict_count", "error_count", "has_merged_output",
        "merge_reason", "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.cross_runtime_result_merge import ResultMergeSummary

        d = ResultMergeSummary().to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 15. from_local_takeover_result — adapter from dict
# ---------------------------------------------------------------------------


class TestFromLocalTakeoverResultDict:
    def test_success_path(self):
        from contracts.cross_runtime_result_merge import (
            from_local_takeover_result, RuntimeResultRole, RuntimeResultStatus,
        )

        d = _make_takeover_result_dict(success=True)
        unit = from_local_takeover_result(d, role=RuntimeResultRole.target)
        assert unit.status == RuntimeResultStatus.succeeded
        assert unit.role == RuntimeResultRole.target
        assert unit.trace_id == d["trace_id"]
        assert unit.task_id == d["task_id"]

    def test_failure_path(self):
        from contracts.cross_runtime_result_merge import (
            from_local_takeover_result, RuntimeResultStatus,
        )

        d = _make_takeover_result_dict(success=False, status="failed", reason="executor_unavailable")
        unit = from_local_takeover_result(d)
        assert unit.status == RuntimeResultStatus.failed

    def test_provenance_populated(self):
        from contracts.cross_runtime_result_merge import from_local_takeover_result

        d = _make_takeover_result_dict(success=True)
        unit = from_local_takeover_result(d)
        assert unit.provenance is not None
        assert unit.provenance.execution_path == "remote_handoff"


# ---------------------------------------------------------------------------
# 16. from_local_takeover_result — adapter from object with to_dict
# ---------------------------------------------------------------------------


class TestFromLocalTakeoverResultObject:
    def test_object_with_to_dict(self):
        from contracts.cross_runtime_result_merge import (
            from_local_takeover_result, RuntimeResultStatus,
        )

        obj = MagicMock()
        obj.to_dict.return_value = _make_takeover_result_dict(success=True)
        unit = from_local_takeover_result(obj)
        assert unit.status == RuntimeResultStatus.succeeded


# ---------------------------------------------------------------------------
# 17. from_local_takeover_result — graceful handling of None/empty
# ---------------------------------------------------------------------------


class TestFromLocalTakeoverResultGraceful:
    def test_none_input(self):
        from contracts.cross_runtime_result_merge import from_local_takeover_result

        unit = from_local_takeover_result(None)
        assert unit is not None

    def test_empty_dict(self):
        from contracts.cross_runtime_result_merge import from_local_takeover_result

        unit = from_local_takeover_result({})
        assert unit is not None

    def test_mesh_session_id_propagated(self):
        from contracts.cross_runtime_result_merge import from_local_takeover_result

        d = _make_takeover_result_dict()
        unit = from_local_takeover_result(d, mesh_session_id="mesh_001")
        assert unit.mesh_session_id == "mesh_001"


# ---------------------------------------------------------------------------
# 18. from_source_dispatch_result — adapter from dict
# ---------------------------------------------------------------------------


class TestFromSourceDispatchResultDict:
    def test_success_path(self):
        from contracts.cross_runtime_result_merge import (
            from_source_dispatch_result, RuntimeResultRole, RuntimeResultStatus,
        )

        d = _make_dispatch_result_dict(success=True)
        unit = from_source_dispatch_result(d, role=RuntimeResultRole.source)
        assert unit.status == RuntimeResultStatus.succeeded
        assert unit.role == RuntimeResultRole.source
        assert unit.trace_id == d["trace_id"]
        assert unit.device_id == d["source_device_id"]

    def test_failure_path(self):
        from contracts.cross_runtime_result_merge import (
            from_source_dispatch_result, RuntimeResultStatus,
        )

        d = _make_dispatch_result_dict(success=False, errors=["dispatch_failed"])
        unit = from_source_dispatch_result(d)
        assert unit.status == RuntimeResultStatus.failed

    def test_provenance_execution_path(self):
        from contracts.cross_runtime_result_merge import from_source_dispatch_result

        d = _make_dispatch_result_dict(mode="remote_handoff")
        unit = from_source_dispatch_result(d)
        assert unit.provenance is not None
        assert unit.provenance.execution_path == "remote_handoff"


# ---------------------------------------------------------------------------
# 19. from_source_dispatch_result — adapter from object with to_dict
# ---------------------------------------------------------------------------


class TestFromSourceDispatchResultObject:
    def test_object_with_to_dict(self):
        from contracts.cross_runtime_result_merge import (
            from_source_dispatch_result, RuntimeResultStatus,
        )

        obj = MagicMock()
        obj.to_dict.return_value = _make_dispatch_result_dict(success=True)
        unit = from_source_dispatch_result(obj)
        assert unit.status == RuntimeResultStatus.succeeded


# ---------------------------------------------------------------------------
# 20. from_source_dispatch_result — graceful handling of None/empty
# ---------------------------------------------------------------------------


class TestFromSourceDispatchResultGraceful:
    def test_none_input(self):
        from contracts.cross_runtime_result_merge import from_source_dispatch_result

        unit = from_source_dispatch_result(None)
        assert unit is not None

    def test_empty_dict(self):
        from contracts.cross_runtime_result_merge import from_source_dispatch_result

        unit = from_source_dispatch_result({})
        assert unit is not None


# ---------------------------------------------------------------------------
# 21. from_execution_output — local success path
# ---------------------------------------------------------------------------


class TestFromExecutionOutputSuccess:
    def test_success(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, RuntimeResultStatus, RuntimeResultRole,
        )

        out = {"success": True, "action_taken": "click"}
        unit = from_execution_output(
            out, trace_id="trace_local", task_id="task_local",
            session_id="sess_local", role=RuntimeResultRole.primary,
        )
        assert unit.status == RuntimeResultStatus.succeeded
        assert unit.role == RuntimeResultRole.primary
        assert unit.trace_id == "trace_local"
        assert unit.output == out

    def test_provenance_execution_path_local(self):
        from contracts.cross_runtime_result_merge import from_execution_output

        out = {"success": True, "action_taken": "type"}
        unit = from_execution_output(out)
        assert unit.provenance is not None
        assert unit.provenance.execution_path == "local"


# ---------------------------------------------------------------------------
# 22. from_execution_output — local failure path
# ---------------------------------------------------------------------------


class TestFromExecutionOutputFailure:
    def test_failure(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, RuntimeResultStatus,
        )

        out = {"success": False, "action_taken": "error"}
        unit = from_execution_output(out)
        assert unit.status == RuntimeResultStatus.failed

    def test_failure_without_action(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, RuntimeResultStatus,
        )

        out = {"success": False}
        unit = from_execution_output(out)
        assert unit.status == RuntimeResultStatus.failed


# ---------------------------------------------------------------------------
# 23. from_execution_output — blocked / readiness_gate path
# ---------------------------------------------------------------------------


class TestFromExecutionOutputBlocked:
    def test_readiness_gate_blocked(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, RuntimeResultStatus,
        )

        out = {"success": False, "skipped_reason": "readiness_gate:device_busy"}
        unit = from_execution_output(out)
        assert unit.status == RuntimeResultStatus.blocked

    def test_skipped(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, RuntimeResultStatus,
        )

        out = {"success": False, "skipped_reason": "policy_skip"}
        unit = from_execution_output(out)
        assert unit.status == RuntimeResultStatus.skipped


# ---------------------------------------------------------------------------
# 24. from_execution_output — graceful with None input
# ---------------------------------------------------------------------------


class TestFromExecutionOutputGraceful:
    def test_none_input(self):
        from contracts.cross_runtime_result_merge import from_execution_output, RuntimeResultStatus

        unit = from_execution_output(None)
        assert unit is not None
        assert unit.status == RuntimeResultStatus.failed  # no success=True → failed

    def test_execution_trace_extracted(self):
        from contracts.cross_runtime_result_merge import from_execution_output

        trace_dict = {"trace_id": "trace_inner"}
        out = {"success": True, "action_taken": "click", "execution_trace": trace_dict}
        unit = from_execution_output(out)
        assert unit.execution_trace is not None
        assert unit.execution_trace["trace_id"] == "trace_inner"


# ---------------------------------------------------------------------------
# 25. build_merged_runtime_result — convenience factory
# ---------------------------------------------------------------------------


class TestBuildMergedRuntimeResult:
    def test_basic_build(self):
        from contracts.cross_runtime_result_merge import (
            build_merged_runtime_result, ResultMergePolicy,
        )

        r = build_merged_runtime_result(
            trace_id="trace_build",
            task_id="task_build",
            merge_policy=ResultMergePolicy.primary_wins,
            success=True,
            merged_output={"done": True},
        )
        assert r.trace_id == "trace_build"
        assert r.success is True
        assert r.merged_output == {"done": True}

    def test_merge_id_generated_if_not_provided(self):
        from contracts.cross_runtime_result_merge import build_merged_runtime_result

        r = build_merged_runtime_result()
        uuid.UUID(r.merge_id)  # should not raise

    def test_lists_initialised_empty(self):
        from contracts.cross_runtime_result_merge import build_merged_runtime_result

        r = build_merged_runtime_result()
        assert r.result_units == []
        assert r.conflicts == []
        assert r.errors == []


# ---------------------------------------------------------------------------
# 26. build_merged_runtime_result — never raises on bad input
# ---------------------------------------------------------------------------


class TestBuildMergedRuntimeResultSafety:
    def test_invalid_units_type_handled(self):
        from contracts.cross_runtime_result_merge import build_merged_runtime_result

        # Should not raise even when given unusual metadata
        r = build_merged_runtime_result(metadata=None)
        assert r is not None

    def test_returns_merged_runtime_result_type(self):
        from contracts.cross_runtime_result_merge import build_merged_runtime_result, MergedRuntimeResult

        r = build_merged_runtime_result()
        assert isinstance(r, MergedRuntimeResult)


# ---------------------------------------------------------------------------
# 27. merge_runtime_results — local-only (single unit, primary_wins)
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsLocalOnly:
    def test_single_local_unit(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit = from_execution_output(
            {"success": True, "action_taken": "click"},
            trace_id="trace_local",
        )
        merged = merge_runtime_results(
            [unit],
            trace_id="trace_local",
            merge_policy=ResultMergePolicy.primary_wins,
        )
        assert merged.success is True
        assert merged.fallback_applied is False
        assert merged.partial is False
        assert len(merged.result_units) == 1

    def test_single_unit_output_preserved(self):
        from contracts.cross_runtime_result_merge import from_execution_output, merge_runtime_results

        out = {"success": True, "action_taken": "type", "text": "hello"}
        unit = from_execution_output(out)
        merged = merge_runtime_results([unit])
        assert merged.merged_output == out


# ---------------------------------------------------------------------------
# 28. merge_runtime_results — remote-only (single target unit)
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsRemoteOnly:
    def test_single_remote_unit(self):
        from contracts.cross_runtime_result_merge import (
            from_local_takeover_result, merge_runtime_results, RuntimeResultStatus,
        )

        d = _make_takeover_result_dict(success=True)
        unit = from_local_takeover_result(d)
        merged = merge_runtime_results([unit], trace_id=d["trace_id"])
        assert merged.success is True
        assert merged.primary_result_unit_id == unit.result_unit_id


# ---------------------------------------------------------------------------
# 29. merge_runtime_results — primary_wins with two units (one failed)
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsPrimaryWins:
    def test_primary_wins_one_failed(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, from_local_takeover_result,
            merge_runtime_results, ResultMergePolicy, RuntimeResultRole,
        )

        local_unit = from_execution_output(
            {"success": True, "action_taken": "click"},
            role=RuntimeResultRole.primary,
        )
        remote_unit = from_local_takeover_result(
            _make_takeover_result_dict(success=False, status="failed"),
            role=RuntimeResultRole.target,
        )
        merged = merge_runtime_results(
            [local_unit, remote_unit],
            merge_policy=ResultMergePolicy.primary_wins,
        )
        assert merged.success is True
        assert merged.partial is True  # one unit failed
        assert merged.primary_result_unit_id == local_unit.result_unit_id


# ---------------------------------------------------------------------------
# 30. merge_runtime_results — first_success policy
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsFirstSuccess:
    def test_first_success_wins(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click"})
        unit2 = from_execution_output({"success": True, "action_taken": "type"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.first_success,
        )
        assert merged.success is True
        assert merged.primary_result_unit_id == unit1.result_unit_id

    def test_first_success_with_leading_failure(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        fail_unit = from_execution_output({"success": False, "action_taken": "error"})
        success_unit = from_execution_output({"success": True, "action_taken": "click"})
        merged = merge_runtime_results(
            [fail_unit, success_unit],
            merge_policy=ResultMergePolicy.first_success,
        )
        assert merged.success is True
        assert merged.primary_result_unit_id == success_unit.result_unit_id


# ---------------------------------------------------------------------------
# 31. merge_runtime_results — last_success policy
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsLastSuccess:
    def test_last_success_wins(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click"})
        unit2 = from_execution_output({"success": True, "action_taken": "type"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.last_success,
        )
        assert merged.success is True
        assert merged.primary_result_unit_id == unit2.result_unit_id


# ---------------------------------------------------------------------------
# 32. merge_runtime_results — all_required policy, all succeed
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsAllRequired:
    def test_all_succeed(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click"})
        unit2 = from_execution_output({"success": True, "action_taken": "type"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.all_required,
        )
        assert merged.success is True
        assert merged.errors == []

    def test_one_fails(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click"})
        unit2 = from_execution_output({"success": False, "action_taken": "error"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.all_required,
        )
        assert merged.success is False
        assert len(merged.errors) > 0


# ---------------------------------------------------------------------------
# 34. merge_runtime_results — best_effort policy
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsBestEffort:
    def test_partial_success(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click"})
        unit2 = from_execution_output({"success": False, "action_taken": "error"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.best_effort,
        )
        assert merged.success is True
        assert merged.partial is True
        assert len(merged.errors) > 0  # failed unit recorded

    def test_all_fail(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": False})
        unit2 = from_execution_output({"success": False})
        merged = merge_runtime_results([unit1, unit2], merge_policy=ResultMergePolicy.best_effort)
        assert merged.success is False
        assert merged.partial is True


# ---------------------------------------------------------------------------
# 35. merge_runtime_results — fallback_chain policy
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsFallbackChain:
    def test_first_unit_succeeds(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click"})
        unit2 = from_execution_output({"success": True, "action_taken": "type"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.fallback_chain,
        )
        assert merged.success is True
        assert merged.primary_result_unit_id == unit1.result_unit_id


# ---------------------------------------------------------------------------
# 36. merge_runtime_results — fallback used when primary fails
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsFallbackUsed:
    def test_fallback_applied(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
            RuntimeResultUnit, RuntimeResultRole, RuntimeResultStatus,
        )

        primary = from_execution_output({"success": False}, role=RuntimeResultRole.primary)
        fallback = RuntimeResultUnit(
            role=RuntimeResultRole.fallback,
            status=RuntimeResultStatus.succeeded,
            output={"action_taken": "fallback_click"},
        )
        merged = merge_runtime_results(
            [primary, fallback],
            merge_policy=ResultMergePolicy.primary_wins,
        )
        assert merged.success is True
        assert merged.fallback_applied is True
        assert merged.primary_result_unit_id == fallback.result_unit_id


# ---------------------------------------------------------------------------
# 37. merge_runtime_results — empty units list
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsEmpty:
    def test_empty_units(self):
        from contracts.cross_runtime_result_merge import merge_runtime_results

        merged = merge_runtime_results([])
        assert merged.success is False
        assert len(merged.errors) > 0


# ---------------------------------------------------------------------------
# 38. merge_runtime_results — graceful with None units
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsNone:
    def test_none_units(self):
        from contracts.cross_runtime_result_merge import merge_runtime_results

        merged = merge_runtime_results(None)
        assert merged is not None
        assert merged.success is False


# ---------------------------------------------------------------------------
# 39. merge_runtime_results — conflict detection
# ---------------------------------------------------------------------------


class TestMergeRuntimeResultsConflicts:
    def test_conflicting_outputs_detected(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        unit1 = from_execution_output({"success": True, "action_taken": "click", "result": "A"})
        unit2 = from_execution_output({"success": True, "action_taken": "type", "result": "B"})
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.primary_wins,
        )
        # Both units have different outputs — conflict should be detected
        assert len(merged.conflicts) > 0

    def test_identical_outputs_no_conflict(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, ResultMergePolicy,
        )

        same_out = {"success": True, "action_taken": "click"}
        unit1 = from_execution_output(same_out.copy())
        unit2 = from_execution_output(same_out.copy())
        merged = merge_runtime_results(
            [unit1, unit2],
            merge_policy=ResultMergePolicy.primary_wins,
        )
        assert len(merged.conflicts) == 0


# ---------------------------------------------------------------------------
# 40. build_result_merge_summary — from MergedRuntimeResult
# ---------------------------------------------------------------------------


class TestBuildResultMergeSummaryFromResult:
    def test_from_result(self):
        from contracts.cross_runtime_result_merge import (
            from_execution_output, merge_runtime_results, build_result_merge_summary,
        )

        unit = from_execution_output({"success": True, "action_taken": "click"})
        merged = merge_runtime_results([unit], trace_id="trace_summary")
        summary = build_result_merge_summary(merged)
        assert summary.merge_id == merged.merge_id
        assert summary.trace_id == "trace_summary"
        assert summary.success == merged.success
        assert summary.unit_count == 1
        assert summary.succeeded_unit_count == 1


# ---------------------------------------------------------------------------
# 41. build_result_merge_summary — direct kwargs
# ---------------------------------------------------------------------------


class TestBuildResultMergeSummaryDirect:
    def test_direct_kwargs(self):
        from contracts.cross_runtime_result_merge import (
            build_result_merge_summary, ResultMergePolicy,
        )

        summary = build_result_merge_summary(
            merge_policy=ResultMergePolicy.best_effort,
            success=True,
            partial=True,
            unit_count=3,
            succeeded_unit_count=2,
            failed_unit_count=1,
            has_merged_output=True,
            merge_reason="partial_mesh",
        )
        assert summary.merge_policy == ResultMergePolicy.best_effort
        assert summary.success is True
        assert summary.partial is True
        assert summary.unit_count == 3
        assert summary.failed_unit_count == 1


# ---------------------------------------------------------------------------
# 42. build_result_merge_summary — never raises
# ---------------------------------------------------------------------------


class TestBuildResultMergeSummaryNeverRaises:
    def test_none_input(self):
        from contracts.cross_runtime_result_merge import build_result_merge_summary

        summary = build_result_merge_summary(None)
        assert summary is not None

    def test_returns_result_merge_summary_type(self):
        from contracts.cross_runtime_result_merge import build_result_merge_summary, ResultMergeSummary

        summary = build_result_merge_summary()
        assert isinstance(summary, ResultMergeSummary)


# ---------------------------------------------------------------------------
# 43. contracts package root re-exports
# ---------------------------------------------------------------------------


class TestContractsPackageRootReexports:
    def test_pr36_exports(self):
        import contracts

        expected = [
            "RuntimeResultRole",
            "RuntimeResultStatus",
            "ResultMergePolicy",
            "RuntimeResultProvenance",
            "RuntimeResultUnit",
            "ResultMergeInput",
            "MergedRuntimeResult",
            "ResultMergeSummary",
            "merge_unit_from_takeover_result",
            "merge_unit_from_dispatch_result",
            "merge_unit_from_execution_output",
            "build_merged_runtime_result",
            "merge_runtime_results",
            "build_result_merge_summary",
        ]
        for name in expected:
            assert hasattr(contracts, name), f"contracts missing: {name}"
            assert name in contracts.__all__, f"contracts.__all__ missing: {name}"


# ---------------------------------------------------------------------------
# 44. core.unified package re-exports
# ---------------------------------------------------------------------------


class TestCoreUnifiedPackageReexports:
    def test_pr36_exports(self):
        import core.unified as cu

        expected = [
            "RuntimeResultRole",
            "RuntimeResultStatus",
            "ResultMergePolicy",
            "RuntimeResultProvenance",
            "RuntimeResultUnit",
            "ResultMergeInput",
            "MergedRuntimeResult",
            "ResultMergeSummary",
            "merge_unit_from_takeover_result",
            "merge_unit_from_dispatch_result",
            "merge_unit_from_execution_output",
            "build_merged_runtime_result",
            "merge_runtime_results",
            "build_result_merge_summary",
        ]
        for name in expected:
            assert hasattr(cu, name), f"core.unified missing: {name}"
            assert name in cu.__all__, f"core.unified.__all__ missing: {name}"


# ---------------------------------------------------------------------------
# 45. core.runtime package re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimePackageReexports:
    def test_pr36_exports(self):
        import core.runtime as cr

        expected = [
            "RuntimeResultRole",
            "RuntimeResultStatus",
            "ResultMergePolicy",
            "RuntimeResultUnit",
            "MergedRuntimeResult",
            "ResultMergeSummary",
            "merge_unit_from_takeover_result",
            "merge_unit_from_dispatch_result",
            "merge_unit_from_execution_output",
            "build_merged_runtime_result",
            "merge_runtime_results",
            "build_result_merge_summary",
        ]
        for name in expected:
            assert hasattr(cr, name), f"core.runtime missing: {name}"
            assert name in cr.__all__, f"core.runtime.__all__ missing: {name}"


# ---------------------------------------------------------------------------
# 46. Projection endpoint — GET /api/v1/runtime/result-merge-summary
# ---------------------------------------------------------------------------


class TestProjectionEndpointResultMergeSummary:
    def test_endpoint_returns_200(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/runtime/result-merge-summary")
        assert resp.status_code == 200

    def test_endpoint_returns_valid_json(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/runtime/result-merge-summary")
        body = resp.json()
        assert isinstance(body, dict)

    def test_endpoint_has_required_fields(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/runtime/result-merge-summary")
        body = resp.json()
        for field in ["summary_id", "merge_policy", "success", "timestamp"]:
            assert field in body, f"Missing field in response: {field}"

    def test_endpoint_merge_reason_no_active_merge(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        resp = client.get("/api/v1/runtime/result-merge-summary")
        body = resp.json()
        assert body.get("merge_reason") == "no_active_merge"


# ---------------------------------------------------------------------------
# 47. MergedRuntimeResult.from_dict round-trip with all fields
# ---------------------------------------------------------------------------


class TestMergedRuntimeResultFullRoundTrip:
    def test_full_round_trip(self):
        from contracts.cross_runtime_result_merge import (
            MergedRuntimeResult, ResultMergePolicy, RuntimeResultUnit,
            RuntimeResultRole, RuntimeResultStatus, RuntimeResultProvenance,
        )

        prov = RuntimeResultProvenance(
            device_id="device_001",
            execution_path="local",
        )
        unit = RuntimeResultUnit(
            role=RuntimeResultRole.primary,
            status=RuntimeResultStatus.succeeded,
            output={"done": True},
            trace_id="trace_full",
            provenance=prov,
        )
        original = MergedRuntimeResult(
            trace_id="trace_full",
            task_id="task_full",
            session_id="sess_full",
            mesh_session_id="mesh_full",
            result_units=[unit],
            primary_result_unit_id=unit.result_unit_id,
            merge_policy=ResultMergePolicy.primary_wins,
            merged_output={"done": True},
            success=True,
            partial=False,
            fallback_applied=False,
            conflicts=[],
            execution_trace_refs=["trace_full"],
            governance_snapshot_refs=["gov_001"],
            policy_alignment_refs=["policy_001"],
            merge_reason="test_full",
            errors=[],
            metadata={"source": "test"},
        )
        restored = MergedRuntimeResult.from_dict(original.to_dict())
        assert restored.trace_id == "trace_full"
        assert restored.task_id == "task_full"
        assert restored.session_id == "sess_full"
        assert restored.mesh_session_id == "mesh_full"
        assert len(restored.result_units) == 1
        assert restored.result_units[0].role == RuntimeResultRole.primary
        assert restored.success is True
        assert restored.merge_reason == "test_full"
        assert restored.metadata == {"source": "test"}


# ---------------------------------------------------------------------------
# 48. Graceful handling of missing provenance/context
# ---------------------------------------------------------------------------


class TestGracefulMissingProvenance:
    def test_unit_without_provenance(self):
        from contracts.cross_runtime_result_merge import (
            RuntimeResultUnit, merge_runtime_results,
            RuntimeResultRole, RuntimeResultStatus,
        )

        unit = RuntimeResultUnit(
            role=RuntimeResultRole.primary,
            status=RuntimeResultStatus.succeeded,
            output={"done": True},
            provenance=None,  # explicitly no provenance
        )
        merged = merge_runtime_results([unit])
        assert merged.success is True
        assert merged.execution_trace_refs == []
        assert merged.governance_snapshot_refs == []
        assert merged.policy_alignment_refs == []

    def test_unit_with_empty_provenance(self):
        from contracts.cross_runtime_result_merge import (
            RuntimeResultUnit, RuntimeResultProvenance,
            merge_runtime_results, RuntimeResultRole, RuntimeResultStatus,
        )

        prov = RuntimeResultProvenance()
        unit = RuntimeResultUnit(
            role=RuntimeResultRole.primary,
            status=RuntimeResultStatus.succeeded,
            output={"done": True},
            provenance=prov,
        )
        merged = merge_runtime_results([unit])
        assert merged.success is True
        assert merged.execution_trace_refs == []


# ---------------------------------------------------------------------------
# 49. Provenance refs collected from units
# ---------------------------------------------------------------------------


class TestProvenanceRefsCollected:
    def test_refs_aggregated(self):
        from contracts.cross_runtime_result_merge import (
            RuntimeResultUnit, RuntimeResultProvenance,
            merge_runtime_results, RuntimeResultRole, RuntimeResultStatus,
        )

        prov1 = RuntimeResultProvenance(
            execution_trace_ref="trace_ref_1",
            governance_snapshot_ref="gov_ref_1",
            policy_alignment_ref="policy_ref_1",
        )
        prov2 = RuntimeResultProvenance(
            execution_trace_ref="trace_ref_2",
            governance_snapshot_ref="gov_ref_2",
        )
        unit1 = RuntimeResultUnit(
            role=RuntimeResultRole.primary,
            status=RuntimeResultStatus.succeeded,
            output={"done": True},
            provenance=prov1,
        )
        unit2 = RuntimeResultUnit(
            role=RuntimeResultRole.support,
            status=RuntimeResultStatus.succeeded,
            output={"done": True},
            provenance=prov2,
        )
        merged = merge_runtime_results([unit1, unit2])
        assert "trace_ref_1" in merged.execution_trace_refs
        assert "trace_ref_2" in merged.execution_trace_refs
        assert "gov_ref_1" in merged.governance_snapshot_refs
        assert "gov_ref_2" in merged.governance_snapshot_refs
        assert "policy_ref_1" in merged.policy_alignment_refs


# ---------------------------------------------------------------------------
# 50. from_local_takeover_result + from_source_dispatch_result combined merge
# ---------------------------------------------------------------------------


class TestCombinedTakeoverAndDispatchMerge:
    def test_combined_merge(self):
        from contracts.cross_runtime_result_merge import (
            from_local_takeover_result, from_source_dispatch_result,
            merge_runtime_results, ResultMergePolicy,
            RuntimeResultRole, RuntimeResultStatus,
        )

        dispatch_unit = from_source_dispatch_result(
            _make_dispatch_result_dict(success=True, mode="remote_handoff"),
            role=RuntimeResultRole.source,
        )
        takeover_unit = from_local_takeover_result(
            _make_takeover_result_dict(success=True),
            role=RuntimeResultRole.target,
        )
        merged = merge_runtime_results(
            [dispatch_unit, takeover_unit],
            merge_policy=ResultMergePolicy.primary_wins,
            trace_id="trace_combined",
            merge_reason="handoff_merge",
        )
        assert merged.success is True
        assert merged.trace_id == "trace_combined"
        assert merged.merge_reason == "handoff_merge"
        assert len(merged.result_units) == 2
