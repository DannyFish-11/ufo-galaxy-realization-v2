#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr14_distributed_execution.py
==========================================

Tests for PR-14: Distributed Task Merge & Recovery.

Coverage
--------
A) MergeStatus enum
   - all expected status values present
   - string values are stable
   - enum is str subclass
   - MERGE_STATUS_ORDER ordering
   - merge_status_severity returns correct levels
   - worst_of returns more severe status
   - is_terminal_failure correct
   - is_successful_outcome correct

B) RecoveryPosture enum
   - all expected posture values present
   - string values are stable
   - enum is str subclass
   - POSTURE_DESCRIPTIONS covers all postures

C) RecoveryRecommendation dataclass
   - construction with all fields
   - to_dict() serialisation
   - from_dict() reconstruction
   - frozen / immutable
   - round-trip fidelity
   - __repr__ smoke test

D) recommend_recovery logic
   - success → no_recovery_needed
   - degraded_success → no_recovery_needed
   - partial_success + optional branch → skip_optional_branch
   - partial_success + confirmation required → require_confirmation
   - partial_success + retry+reroute → reroute_device
   - partial_success (default) → retry_same_device
   - timed_out + reroute → reroute_device
   - timed_out (no reroute) → retry_same_device
   - failed + no prior retry → retry_same_device
   - failed + retry + reroute → reroute_device
   - failed + optional branch → skip_optional_branch
   - failed (all options exhausted) → abort_task
   - requires_confirmation override for terminal states

E) MergeSummary dataclass
   - construction with all fields
   - to_dict() serialisation
   - from_dict() reconstruction
   - round-trip fidelity
   - EMPTY_MERGE_SUMMARY constant
   - is_successful derived property
   - is_terminal_failure derived property
   - success_rate derived property (incl. zero-total)
   - frozen / immutable
   - __repr__ smoke test
   - recovery_recommendation embedded in to_dict / from_dict

F) merge_result_envelopes helper
   - empty list → FAILED summary with warning
   - all success → SUCCESS summary
   - mixed success/failure → PARTIAL_SUCCESS
   - all failed → FAILED
   - timeout detection via error message
   - all timed out → TIMED_OUT
   - task_id / trace_id propagation from envelopes
   - task_id / trace_id override kwargs

G) merge_graph_result helper
   - None input → FAILED summary with error
   - all-done graph → SUCCESS
   - graph with failures → PARTIAL/FAILED
   - graph with skipped nodes → PARTIAL_SUCCESS
   - trace_id / runtime_session_id propagation
   - node_results and node_errors captured in payloads

H) merge_dict_results helper
   - empty list → FAILED with warning
   - all success dicts → SUCCESS
   - mixed dicts → PARTIAL_SUCCESS
   - timed_out flag in dict → timed_out counted
   - None / non-dict entries gracefully skipped
   - IDs propagated from dict fields

I) merge_any helper
   - empty list → FAILED with warning
   - single GraphExecutionResult → delegates to merge_graph_result
   - list of dicts → delegates to merge_dict_results
   - None entries gracefully filtered
   - worst_of applied across sub-summaries

J) attach_merge_summary_to_projection helper
   - adds "merge_summary" key to projection dict
   - original dict not modified
   - non-dict input handled gracefully
   - existing fields preserved

K) get_merge_hints helper
   - success summary → correct hints
   - failed summary with recovery → recovery_posture populated
   - zero total → success_rate 0.0

L) Integration: merge + recovery + summary round-trip
   - merge partial results, attach recovery, serialise, deserialise
"""

from __future__ import annotations

import dataclasses
import pytest

# ---------------------------------------------------------------------------
# Module-level imports
# ---------------------------------------------------------------------------

from core.distributed_execution.merge_status import (
    MergeStatus,
    MERGE_STATUS_ORDER,
    merge_status_severity,
    worst_of,
    is_terminal_failure,
    is_successful_outcome,
)
from core.distributed_execution.recovery_policy import (
    RecoveryPosture,
    POSTURE_DESCRIPTIONS,
    RecoveryRecommendation,
    recommend_recovery,
)
from core.distributed_execution.merge_summary import (
    MergeSummary,
    EMPTY_MERGE_SUMMARY,
    attach_merge_summary_to_projection,
    get_merge_hints,
)
from core.distributed_execution.result_merge import (
    merge_result_envelopes,
    merge_graph_result,
    merge_dict_results,
    merge_any,
)
from core.distributed_execution import (
    MergeStatus as _MSPublic,
    RecoveryPosture as _RPPublic,
    MergeSummary as _SummaryPublic,
    merge_any as _merge_any_public,
)


# ===========================================================================
# A) MergeStatus enum
# ===========================================================================

class TestMergeStatus:

    def test_all_expected_values_present(self):
        expected = {
            "success", "partial_success", "degraded_success",
            "failed", "timed_out",
        }
        actual = {s.value for s in MergeStatus}
        assert expected == actual

    def test_string_values_stable(self):
        assert MergeStatus.SUCCESS.value == "success"
        assert MergeStatus.PARTIAL_SUCCESS.value == "partial_success"
        assert MergeStatus.DEGRADED_SUCCESS.value == "degraded_success"
        assert MergeStatus.FAILED.value == "failed"
        assert MergeStatus.TIMED_OUT.value == "timed_out"

    def test_enum_is_str_subclass(self):
        assert isinstance(MergeStatus.SUCCESS, str)
        assert MergeStatus.SUCCESS == "success"

    def test_status_order_length(self):
        assert len(MERGE_STATUS_ORDER) == 5

    def test_status_order_first_and_last(self):
        assert MERGE_STATUS_ORDER[0] == MergeStatus.SUCCESS
        assert MERGE_STATUS_ORDER[-1] == MergeStatus.TIMED_OUT

    def test_severity_success_is_zero(self):
        assert merge_status_severity(MergeStatus.SUCCESS) == 0

    def test_severity_timed_out_is_highest(self):
        assert merge_status_severity(MergeStatus.TIMED_OUT) == 4

    def test_severity_ordering(self):
        sevs = [merge_status_severity(s) for s in MERGE_STATUS_ORDER]
        assert sevs == sorted(sevs)

    def test_worst_of_returns_more_severe(self):
        assert worst_of(MergeStatus.SUCCESS, MergeStatus.FAILED) == MergeStatus.FAILED
        assert worst_of(MergeStatus.PARTIAL_SUCCESS, MergeStatus.TIMED_OUT) == MergeStatus.TIMED_OUT
        assert worst_of(MergeStatus.SUCCESS, MergeStatus.SUCCESS) == MergeStatus.SUCCESS

    def test_worst_of_symmetric(self):
        a, b = MergeStatus.PARTIAL_SUCCESS, MergeStatus.DEGRADED_SUCCESS
        assert worst_of(a, b) == worst_of(b, a)

    def test_is_terminal_failure(self):
        assert is_terminal_failure(MergeStatus.FAILED)
        assert is_terminal_failure(MergeStatus.TIMED_OUT)
        assert not is_terminal_failure(MergeStatus.SUCCESS)
        assert not is_terminal_failure(MergeStatus.PARTIAL_SUCCESS)
        assert not is_terminal_failure(MergeStatus.DEGRADED_SUCCESS)

    def test_is_successful_outcome(self):
        assert is_successful_outcome(MergeStatus.SUCCESS)
        assert is_successful_outcome(MergeStatus.PARTIAL_SUCCESS)
        assert is_successful_outcome(MergeStatus.DEGRADED_SUCCESS)
        assert not is_successful_outcome(MergeStatus.FAILED)
        assert not is_successful_outcome(MergeStatus.TIMED_OUT)


# ===========================================================================
# B) RecoveryPosture enum
# ===========================================================================

class TestRecoveryPosture:

    def test_all_expected_values_present(self):
        expected = {
            "no_recovery_needed", "retry_same_device", "reroute_device",
            "skip_optional_branch", "require_confirmation", "abort_task",
        }
        actual = {p.value for p in RecoveryPosture}
        assert expected == actual

    def test_string_values_stable(self):
        assert RecoveryPosture.NO_RECOVERY_NEEDED.value == "no_recovery_needed"
        assert RecoveryPosture.RETRY_SAME_DEVICE.value == "retry_same_device"
        assert RecoveryPosture.REROUTE_DEVICE.value == "reroute_device"
        assert RecoveryPosture.SKIP_OPTIONAL_BRANCH.value == "skip_optional_branch"
        assert RecoveryPosture.REQUIRE_CONFIRMATION.value == "require_confirmation"
        assert RecoveryPosture.ABORT_TASK.value == "abort_task"

    def test_enum_is_str_subclass(self):
        assert isinstance(RecoveryPosture.RETRY_SAME_DEVICE, str)
        assert RecoveryPosture.RETRY_SAME_DEVICE == "retry_same_device"

    def test_posture_descriptions_cover_all(self):
        for posture in RecoveryPosture:
            assert posture.value in POSTURE_DESCRIPTIONS
            assert len(POSTURE_DESCRIPTIONS[posture.value]) > 10


# ===========================================================================
# C) RecoveryRecommendation dataclass
# ===========================================================================

class TestRecoveryRecommendation:

    def _build(self, **kwargs):
        defaults = dict(
            posture=RecoveryPosture.RETRY_SAME_DEVICE,
            reason="test reason",
            merge_status_trigger=MergeStatus.FAILED,
            failed_count=1,
            timed_out_count=0,
            is_optional_branch_available=False,
            task_id="t-1",
            trace_id="trace-1",
        )
        defaults.update(kwargs)
        return RecoveryRecommendation(**defaults)

    def test_construction(self):
        rec = self._build()
        assert rec.posture == RecoveryPosture.RETRY_SAME_DEVICE
        assert rec.reason == "test reason"
        assert rec.merge_status_trigger == MergeStatus.FAILED
        assert rec.failed_count == 1
        assert rec.task_id == "t-1"

    def test_to_dict_keys(self):
        rec = self._build()
        d = rec.to_dict()
        assert "posture" in d
        assert "reason" in d
        assert "merge_status_trigger" in d
        assert "failed_count" in d
        assert "timed_out_count" in d
        assert "task_id" in d
        assert "trace_id" in d

    def test_to_dict_enum_values_are_strings(self):
        rec = self._build()
        d = rec.to_dict()
        assert d["posture"] == "retry_same_device"
        assert d["merge_status_trigger"] == "failed"

    def test_from_dict_round_trip(self):
        rec = self._build(posture=RecoveryPosture.REROUTE_DEVICE)
        rec2 = RecoveryRecommendation.from_dict(rec.to_dict())
        assert rec2.posture == RecoveryPosture.REROUTE_DEVICE
        assert rec2.reason == rec.reason
        assert rec2.task_id == rec.task_id

    def test_frozen_immutable(self):
        rec = self._build()
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            rec.posture = RecoveryPosture.ABORT_TASK  # type: ignore[misc]

    def test_repr_smoke(self):
        rec = self._build()
        r = repr(rec)
        assert "RecoveryRecommendation" in r
        assert "retry_same_device" in r


# ===========================================================================
# D) recommend_recovery logic
# ===========================================================================

class TestRecommendRecovery:

    def test_success_no_recovery_needed(self):
        rec = recommend_recovery(MergeStatus.SUCCESS)
        assert rec.posture == RecoveryPosture.NO_RECOVERY_NEEDED

    def test_degraded_success_no_recovery_needed(self):
        rec = recommend_recovery(MergeStatus.DEGRADED_SUCCESS)
        assert rec.posture == RecoveryPosture.NO_RECOVERY_NEEDED

    def test_partial_success_with_optional_branch(self):
        rec = recommend_recovery(
            MergeStatus.PARTIAL_SUCCESS,
            is_optional_branch_available=True,
        )
        assert rec.posture == RecoveryPosture.SKIP_OPTIONAL_BRANCH

    def test_partial_success_confirmation_required(self):
        rec = recommend_recovery(
            MergeStatus.PARTIAL_SUCCESS,
            requires_confirmation=True,
        )
        assert rec.posture == RecoveryPosture.REQUIRE_CONFIRMATION

    def test_partial_success_retry_reroute(self):
        rec = recommend_recovery(
            MergeStatus.PARTIAL_SUCCESS,
            retry_attempted=True,
            reroute_available=True,
        )
        assert rec.posture == RecoveryPosture.REROUTE_DEVICE

    def test_partial_success_default_retry(self):
        rec = recommend_recovery(MergeStatus.PARTIAL_SUCCESS)
        assert rec.posture == RecoveryPosture.RETRY_SAME_DEVICE

    def test_timed_out_with_reroute(self):
        rec = recommend_recovery(
            MergeStatus.TIMED_OUT,
            reroute_available=True,
        )
        assert rec.posture == RecoveryPosture.REROUTE_DEVICE

    def test_timed_out_no_reroute(self):
        rec = recommend_recovery(MergeStatus.TIMED_OUT)
        assert rec.posture == RecoveryPosture.RETRY_SAME_DEVICE

    def test_failed_no_prior_retry(self):
        rec = recommend_recovery(MergeStatus.FAILED)
        assert rec.posture == RecoveryPosture.RETRY_SAME_DEVICE

    def test_failed_retry_reroute_available(self):
        rec = recommend_recovery(
            MergeStatus.FAILED,
            retry_attempted=True,
            reroute_available=True,
        )
        assert rec.posture == RecoveryPosture.REROUTE_DEVICE

    def test_failed_optional_branch_after_retry(self):
        rec = recommend_recovery(
            MergeStatus.FAILED,
            retry_attempted=True,
            is_optional_branch_available=True,
        )
        assert rec.posture == RecoveryPosture.SKIP_OPTIONAL_BRANCH

    def test_failed_all_options_exhausted_abort(self):
        rec = recommend_recovery(
            MergeStatus.FAILED,
            retry_attempted=True,
            reroute_available=False,
            is_optional_branch_available=False,
        )
        assert rec.posture == RecoveryPosture.ABORT_TASK

    def test_requires_confirmation_overrides_timed_out(self):
        rec = recommend_recovery(
            MergeStatus.TIMED_OUT,
            requires_confirmation=True,
        )
        assert rec.posture == RecoveryPosture.REQUIRE_CONFIRMATION

    def test_requires_confirmation_overrides_failed(self):
        rec = recommend_recovery(
            MergeStatus.FAILED,
            retry_attempted=True,
            requires_confirmation=True,
        )
        assert rec.posture == RecoveryPosture.REQUIRE_CONFIRMATION

    def test_trace_ids_propagated(self):
        rec = recommend_recovery(
            MergeStatus.FAILED,
            task_id="t-42",
            trace_id="trace-99",
        )
        assert rec.task_id == "t-42"
        assert rec.trace_id == "trace-99"

    def test_counts_propagated(self):
        rec = recommend_recovery(
            MergeStatus.FAILED,
            failed_count=3,
            timed_out_count=1,
        )
        assert rec.failed_count == 3
        assert rec.timed_out_count == 1


# ===========================================================================
# E) MergeSummary dataclass
# ===========================================================================

class TestMergeSummary:

    def _build(self, **kwargs):
        defaults = dict(
            merge_status=MergeStatus.SUCCESS,
            total_count=3,
            successful_count=3,
            failed_count=0,
            timed_out_count=0,
            skipped_count=0,
            merged_payloads=[{"task_id": "t1", "success": True}],
            errors=[],
            warnings=[],
            recovery_recommendation=None,
            task_id="t-123",
            trace_id="trace-abc",
            runtime_session_id="session-1",
        )
        defaults.update(kwargs)
        return MergeSummary(**defaults)

    def test_construction(self):
        s = self._build()
        assert s.merge_status == MergeStatus.SUCCESS
        assert s.total_count == 3
        assert s.task_id == "t-123"

    def test_to_dict_keys(self):
        s = self._build()
        d = s.to_dict()
        for key in [
            "merge_status", "total_count", "successful_count", "failed_count",
            "timed_out_count", "skipped_count", "success_rate", "is_successful",
            "is_terminal_failure", "merged_payloads", "errors", "warnings",
            "recovery_recommendation", "task_id", "trace_id",
            "runtime_session_id", "merged_at",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_enum_values_are_strings(self):
        s = self._build()
        d = s.to_dict()
        assert d["merge_status"] == "success"

    def test_from_dict_round_trip(self):
        s = self._build(
            merge_status=MergeStatus.PARTIAL_SUCCESS,
            failed_count=1,
            successful_count=2,
            total_count=3,
        )
        s2 = MergeSummary.from_dict(s.to_dict())
        assert s2.merge_status == MergeStatus.PARTIAL_SUCCESS
        assert s2.failed_count == 1
        assert s2.task_id == s.task_id

    def test_empty_merge_summary_constant(self):
        assert EMPTY_MERGE_SUMMARY.merge_status == MergeStatus.FAILED
        assert EMPTY_MERGE_SUMMARY.total_count == 0
        assert EMPTY_MERGE_SUMMARY.errors  # has a message

    def test_is_successful_property_true(self):
        s = self._build(merge_status=MergeStatus.SUCCESS)
        assert s.is_successful is True

    def test_is_successful_property_partial(self):
        s = self._build(merge_status=MergeStatus.PARTIAL_SUCCESS)
        assert s.is_successful is True

    def test_is_successful_property_false(self):
        s = self._build(merge_status=MergeStatus.FAILED)
        assert s.is_successful is False

    def test_is_terminal_failure_property(self):
        s_fail = self._build(merge_status=MergeStatus.FAILED)
        s_ok = self._build(merge_status=MergeStatus.SUCCESS)
        assert s_fail.is_terminal_failure is True
        assert s_ok.is_terminal_failure is False

    def test_success_rate_all_success(self):
        s = self._build(total_count=4, successful_count=4)
        assert s.success_rate == 1.0

    def test_success_rate_mixed(self):
        s = self._build(total_count=3, successful_count=2)
        assert abs(s.success_rate - 2 / 3) < 0.001

    def test_success_rate_zero_total(self):
        s = self._build(total_count=0, successful_count=0)
        assert s.success_rate == 0.0

    def test_frozen_immutable(self):
        s = self._build()
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            s.merge_status = MergeStatus.FAILED  # type: ignore[misc]

    def test_repr_smoke(self):
        s = self._build()
        r = repr(s)
        assert "MergeSummary" in r

    def test_recovery_recommendation_embedded_in_dict(self):
        rec = recommend_recovery(MergeStatus.FAILED)
        s = self._build(
            merge_status=MergeStatus.FAILED,
            recovery_recommendation=rec,
        )
        d = s.to_dict()
        assert d["recovery_recommendation"] is not None
        assert d["recovery_recommendation"]["posture"] == "retry_same_device"

    def test_recovery_recommendation_round_trip(self):
        rec = recommend_recovery(MergeStatus.FAILED)
        s = self._build(
            merge_status=MergeStatus.FAILED,
            recovery_recommendation=rec,
        )
        s2 = MergeSummary.from_dict(s.to_dict())
        assert s2.recovery_recommendation is not None
        assert s2.recovery_recommendation.posture == RecoveryPosture.RETRY_SAME_DEVICE


# ===========================================================================
# F) merge_result_envelopes helper
# ===========================================================================

class _FakeEnvelope:
    """Minimal stand-in for ResultEnvelope."""
    def __init__(self, success, error="", task_id="", trace_id="",
                 device_id="", runtime_session_id="", elapsed_ms=0.0, result=None):
        self.success = success
        self.error = error
        self.task_id = task_id
        self.trace_id = trace_id
        self.device_id = device_id
        self.runtime_session_id = runtime_session_id
        self.elapsed_ms = elapsed_ms
        self.result = result or {}


class TestMergeResultEnvelopes:

    def test_empty_list_returns_failed(self):
        s = merge_result_envelopes([])
        assert s.merge_status == MergeStatus.FAILED
        assert s.total_count == 0
        assert s.warnings

    def test_none_entries_filtered(self):
        s = merge_result_envelopes([None, None])
        assert s.merge_status == MergeStatus.FAILED

    def test_all_success(self):
        envs = [_FakeEnvelope(True, task_id="t1"), _FakeEnvelope(True, task_id="t2")]
        s = merge_result_envelopes(envs)
        assert s.merge_status == MergeStatus.SUCCESS
        assert s.successful_count == 2
        assert s.failed_count == 0

    def test_mixed_success_failure(self):
        envs = [
            _FakeEnvelope(True),
            _FakeEnvelope(False, error="bad thing happened"),
        ]
        s = merge_result_envelopes(envs)
        assert s.merge_status == MergeStatus.PARTIAL_SUCCESS
        assert s.successful_count == 1
        assert s.failed_count == 1

    def test_all_failed(self):
        envs = [_FakeEnvelope(False, error="err") for _ in range(3)]
        s = merge_result_envelopes(envs)
        assert s.merge_status == MergeStatus.FAILED

    def test_timeout_detection_via_error_message(self):
        envs = [
            _FakeEnvelope(True),
            _FakeEnvelope(False, error="operation timed_out"),
        ]
        s = merge_result_envelopes(envs)
        assert s.timed_out_count == 1

    def test_all_timed_out(self):
        envs = [_FakeEnvelope(False, error="timeout") for _ in range(2)]
        s = merge_result_envelopes(envs)
        assert s.merge_status == MergeStatus.TIMED_OUT

    def test_task_id_propagated_from_envelope(self):
        env = _FakeEnvelope(True, task_id="task-from-env", trace_id="tr-1")
        s = merge_result_envelopes([env])
        assert s.task_id == "task-from-env"
        assert s.trace_id == "tr-1"

    def test_task_id_override_via_kwarg(self):
        env = _FakeEnvelope(True, task_id="env-id")
        s = merge_result_envelopes([env], task_id="override-id")
        assert s.task_id == "override-id"

    def test_merged_payloads_count(self):
        envs = [_FakeEnvelope(True) for _ in range(4)]
        s = merge_result_envelopes(envs)
        assert len(s.merged_payloads) == 4


# ===========================================================================
# G) merge_graph_result helper
# ===========================================================================

class _FakeGraphResult:
    """Minimal stand-in for GraphExecutionResult."""
    def __init__(
        self,
        success=True,
        done_nodes=3,
        failed_nodes=0,
        skipped_nodes=0,
        total_nodes=3,
        trace_id="",
        runtime_session_id="",
        graph_id="",
        error="",
        node_results=None,
        node_errors=None,
        node_statuses=None,
    ):
        self.success = success
        self.done_nodes = done_nodes
        self.failed_nodes = failed_nodes
        self.skipped_nodes = skipped_nodes
        self.total_nodes = total_nodes
        self.trace_id = trace_id
        self.runtime_session_id = runtime_session_id
        self.graph_id = graph_id
        self.error = error
        self.node_results = node_results or {}
        self.node_errors = node_errors or {}
        self.node_statuses = node_statuses or {}


class TestMergeGraphResult:

    def test_none_input_returns_failed(self):
        s = merge_graph_result(None)
        assert s.merge_status == MergeStatus.FAILED
        assert s.errors

    def test_all_done_no_skipped_is_success(self):
        gr = _FakeGraphResult(success=True, done_nodes=3, total_nodes=3)
        s = merge_graph_result(gr)
        assert s.merge_status == MergeStatus.SUCCESS
        assert s.successful_count == 3

    def test_skipped_nodes_causes_partial_success(self):
        gr = _FakeGraphResult(
            success=True,
            done_nodes=2,
            skipped_nodes=1,
            total_nodes=3,
        )
        s = merge_graph_result(gr)
        assert s.merge_status == MergeStatus.PARTIAL_SUCCESS

    def test_failed_nodes_gives_failed_status(self):
        gr = _FakeGraphResult(
            success=False,
            done_nodes=0,
            failed_nodes=2,
            total_nodes=2,
        )
        s = merge_graph_result(gr)
        assert s.merge_status == MergeStatus.FAILED

    def test_trace_id_propagated(self):
        gr = _FakeGraphResult(trace_id="tr-graph")
        s = merge_graph_result(gr)
        assert s.trace_id == "tr-graph"

    def test_trace_id_override(self):
        gr = _FakeGraphResult(trace_id="old-tr")
        s = merge_graph_result(gr, trace_id="new-tr")
        assert s.trace_id == "new-tr"

    def test_node_errors_captured_in_errors_list(self):
        gr = _FakeGraphResult(
            success=False,
            done_nodes=1,
            failed_nodes=1,
            total_nodes=2,
            node_results={"n1": {"ok": True}, "n2": None},
            node_errors={"n1": "", "n2": "handler failed"},
            node_statuses={"n1": "done", "n2": "failed"},
        )
        s = merge_graph_result(gr)
        assert any("handler failed" in e for e in s.errors)

    def test_zero_total_nodes_is_failed(self):
        gr = _FakeGraphResult(total_nodes=0, done_nodes=0, failed_nodes=0)
        s = merge_graph_result(gr)
        assert s.merge_status == MergeStatus.FAILED


# ===========================================================================
# H) merge_dict_results helper
# ===========================================================================

class TestMergeDictResults:

    def test_empty_list_returns_failed(self):
        s = merge_dict_results([])
        assert s.merge_status == MergeStatus.FAILED
        assert s.warnings

    def test_non_dict_entries_skipped(self):
        s = merge_dict_results([None, "bad", 42])
        assert s.merge_status == MergeStatus.FAILED

    def test_all_success(self):
        s = merge_dict_results([
            {"success": True},
            {"success": True},
            {"success": True},
        ])
        assert s.merge_status == MergeStatus.SUCCESS
        assert s.successful_count == 3

    def test_mixed_success_failure(self):
        s = merge_dict_results([
            {"success": True},
            {"success": False, "error": "bad"},
        ])
        assert s.merge_status == MergeStatus.PARTIAL_SUCCESS

    def test_timed_out_flag(self):
        s = merge_dict_results([
            {"success": False, "timed_out": True},
        ])
        assert s.timed_out_count == 1
        assert s.merge_status == MergeStatus.TIMED_OUT

    def test_task_id_from_dict(self):
        s = merge_dict_results([{"success": True, "task_id": "t-dict"}])
        assert s.task_id == "t-dict"

    def test_task_id_override(self):
        s = merge_dict_results(
            [{"success": True, "task_id": "t-dict"}],
            task_id="override",
        )
        assert s.task_id == "override"

    def test_errors_list_populated_on_failure(self):
        s = merge_dict_results([
            {"success": False, "error": "something went wrong", "device_id": "dev-x"}
        ])
        assert any("something went wrong" in e for e in s.errors)


# ===========================================================================
# I) merge_any helper
# ===========================================================================

class TestMergeAny:

    def test_empty_list_returns_failed(self):
        s = merge_any([])
        assert s.merge_status == MergeStatus.FAILED

    def test_none_entries_filtered(self):
        s = merge_any([None, None])
        assert s.merge_status == MergeStatus.FAILED

    def test_single_graph_result_delegates(self):
        try:
            from core.task_graph import GraphExecutionResult
            gr = GraphExecutionResult(
                graph_id="g1",
                trace_id="tr-1",
                runtime_session_id="",
                total_nodes=2,
                done_nodes=2,
                failed_nodes=0,
                skipped_nodes=0,
                success=True,
            )
            s = merge_any([gr])
            assert s.merge_status == MergeStatus.SUCCESS
            assert s.successful_count == 2
        except ImportError:
            pytest.skip("core.task_graph not importable in this environment")

    def test_list_of_dicts(self):
        s = merge_any([
            {"success": True},
            {"success": False, "error": "oops"},
        ])
        assert s.merge_status == MergeStatus.PARTIAL_SUCCESS

    def test_worst_of_applied(self):
        # One group succeeds, one fails → overall FAILED (worst)
        gr_ok = _FakeGraphResult(success=True, done_nodes=2, total_nodes=2)
        s = merge_any([
            gr_ok,
            {"success": False, "error": "err"},
        ])
        # Should be at least partial_success or worse
        assert not is_successful_outcome(s.merge_status) or s.merge_status in (
            MergeStatus.PARTIAL_SUCCESS,
            MergeStatus.DEGRADED_SUCCESS,
        )


# ===========================================================================
# J) attach_merge_summary_to_projection helper
# ===========================================================================

class TestAttachMergeSummaryToProjection:

    def test_adds_merge_summary_key(self):
        s = MergeSummary(
            merge_status=MergeStatus.SUCCESS,
            total_count=1,
            successful_count=1,
        )
        proj = {"tri_state_phase": "manifest"}
        result = attach_merge_summary_to_projection(proj, s)
        assert "merge_summary" in result

    def test_original_dict_not_modified(self):
        s = MergeSummary()
        proj = {"phase": "silent"}
        attach_merge_summary_to_projection(proj, s)
        assert "merge_summary" not in proj

    def test_existing_fields_preserved(self):
        s = MergeSummary()
        proj = {"phase": "liminal", "domain": "local"}
        result = attach_merge_summary_to_projection(proj, s)
        assert result["phase"] == "liminal"
        assert result["domain"] == "local"

    def test_non_dict_input_handled(self):
        s = MergeSummary()
        result = attach_merge_summary_to_projection(None, s)
        assert "merge_summary" in result


# ===========================================================================
# K) get_merge_hints helper
# ===========================================================================

class TestGetMergeHints:

    def test_success_summary_hints(self):
        s = MergeSummary(
            merge_status=MergeStatus.SUCCESS,
            total_count=3,
            successful_count=3,
            task_id="t-1",
            trace_id="tr-1",
        )
        hints = get_merge_hints(s)
        assert hints["merge_status"] == "success"
        assert hints["is_successful"] is True
        assert hints["is_terminal_failure"] is False
        assert hints["has_errors"] is False
        assert hints["success_rate"] == 1.0
        assert hints["has_recovery_recommendation"] is False
        assert hints["recovery_posture"] is None
        assert hints["total_count"] == 3
        assert hints["task_id"] == "t-1"
        assert hints["trace_id"] == "tr-1"

    def test_failed_with_recovery_hints(self):
        rec = recommend_recovery(MergeStatus.FAILED)
        s = MergeSummary(
            merge_status=MergeStatus.FAILED,
            recovery_recommendation=rec,
        )
        hints = get_merge_hints(s)
        assert hints["is_successful"] is False
        assert hints["is_terminal_failure"] is True
        assert hints["has_recovery_recommendation"] is True
        assert hints["recovery_posture"] == "retry_same_device"

    def test_zero_total_success_rate(self):
        s = MergeSummary(merge_status=MergeStatus.FAILED, total_count=0)
        hints = get_merge_hints(s)
        assert hints["success_rate"] == 0.0


# ===========================================================================
# L) Integration: merge + recovery + summary round-trip
# ===========================================================================

class TestIntegration:

    def test_merge_partial_then_attach_recovery_and_serialise(self):
        """Full round-trip: merge → recovery → attach → serialise → deserialise."""
        # 1. Merge partial results
        results = [
            {"success": True, "task_id": "t1", "trace_id": "tr-1"},
            {"success": False, "error": "connection refused", "task_id": "t2"},
            {"success": True, "task_id": "t3"},
        ]
        summary = merge_dict_results(results, task_id="t1", trace_id="tr-1")
        assert summary.merge_status == MergeStatus.PARTIAL_SUCCESS
        assert summary.successful_count == 2
        assert summary.failed_count == 1

        # 2. Get recovery recommendation
        rec = recommend_recovery(
            summary.merge_status,
            failed_count=summary.failed_count,
            timed_out_count=summary.timed_out_count,
            total_count=summary.total_count,
            task_id=summary.task_id,
            trace_id=summary.trace_id,
        )
        assert rec.posture == RecoveryPosture.RETRY_SAME_DEVICE

        # 3. Attach recommendation to summary
        summary_with_rec = dataclasses.replace(summary, recovery_recommendation=rec)

        # 4. Serialise
        d = summary_with_rec.to_dict()
        assert d["recovery_recommendation"]["posture"] == "retry_same_device"
        assert d["merge_status"] == "partial_success"

        # 5. Deserialise round-trip
        restored = MergeSummary.from_dict(d)
        assert restored.merge_status == MergeStatus.PARTIAL_SUCCESS
        assert restored.recovery_recommendation is not None
        assert restored.recovery_recommendation.posture == RecoveryPosture.RETRY_SAME_DEVICE

    def test_public_api_re_exports(self):
        """Verify __init__ re-exports are consistent."""
        assert _MSPublic is MergeStatus
        assert _RPPublic is RecoveryPosture
        assert _SummaryPublic is MergeSummary
        assert _merge_any_public is merge_any

    def test_merge_graph_then_recommend_abort(self):
        """Graph with all failures + retry done → abort."""
        gr = _FakeGraphResult(
            success=False,
            done_nodes=0,
            failed_nodes=3,
            total_nodes=3,
        )
        summary = merge_graph_result(gr)
        assert summary.merge_status == MergeStatus.FAILED

        rec = recommend_recovery(
            summary.merge_status,
            failed_count=summary.failed_count,
            retry_attempted=True,
            reroute_available=False,
            is_optional_branch_available=False,
        )
        assert rec.posture == RecoveryPosture.ABORT_TASK
