#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr54_local_execution_chain.py
=========================================
PR-4 — Formalize Local & Cross-Device Execution Chains

Validates:
  1.  LocalChainStep enum has exactly 6 steps.
  2.  LOCAL_CHAIN_ORDER matches expected step ordering.
  3.  LOCAL_CHAIN_ORDER starts with openclawd_dispatch.
  4.  LOCAL_CHAIN_ORDER ends with openclawd_feedback.
  5.  agent_kernel_plan appears before command_router_local.
  6.  command_router_local appears before local_executor.
  7.  local_executor appears before result_capture.
  8.  result_capture appears before openclawd_feedback.
  9.  LOCAL_CHAIN_STEP_AUTHORITIES covers all steps.
 10.  Every authority string is non-empty.
 11.  openclawd_dispatch authority is core.openclawd.
 12.  openclawd_feedback authority is core.openclawd.
 13.  command_router_local authority is core.command_router.
 14.  agent_kernel_plan authority is core.agent.kernel.
 15.  LocalExecutionResult: default construction succeeds.
 16.  LocalExecutionResult: to_dict produces expected keys.
 17.  LocalExecutionResult: from_dict round-trip is stable.
 18.  LocalExecutionResult: openclawd_merged defaults to False.
 19.  LocalExecutionResult: result_id is auto-generated uuid hex.
 20.  build_local_execution_result: success=True for "completed" status.
 21.  build_local_execution_result: success=True for "success" status.
 22.  build_local_execution_result: success=False for "failed" status.
 23.  build_local_execution_result: normalises payload from 'result' subdict.
 24.  build_local_execution_result: normalises payload from 'data' subdict.
 25.  build_local_execution_result: excludes image_base64 from payload.
 26.  build_local_execution_result: propagates task_id from raw dict.
 27.  build_local_execution_result: propagates session_id kwarg.
 28.  build_local_execution_result: chain_step is always result_capture.
 29.  LocalExecutionRecord: default construction succeeds.
 30.  LocalExecutionRecord: to_dict produces expected keys.
 31.  LocalExecutionRecord: from_dict round-trip is stable.
 32.  LocalExecutionRecord: is_canonical False when legacy_path_used set.
 33.  build_local_execution_record: canonical when steps match LOCAL_CHAIN_ORDER.
 34.  build_local_execution_record: non-canonical when legacy_path_used given.
 35.  build_local_execution_record: steps default to LOCAL_CHAIN_ORDER when canonical.
 36.  build_local_execution_record: steps default to [] when legacy path.
 37.  build_local_execution_record: completed_at set when result provided.
 38.  build_local_execution_record: completed_at None when no result.
 39.  LocalChainSnapshot: to_dict produces expected keys.
 40.  LocalChainSnapshot: canonical_chain_order matches LOCAL_CHAIN_ORDER values.
 41.  LocalChainSnapshot: chain_authority_map has all step keys.
 42.  LocalExecutionChainSingleton: initial state has zero counts.
 43.  LocalExecutionChainSingleton: append increments total count.
 44.  LocalExecutionChainSingleton: append increments canonical count for canonical record.
 45.  LocalExecutionChainSingleton: append increments legacy count for legacy record.
 46.  LocalExecutionChainSingleton: snapshot recent_records bounded by max_recent.
 47.  LocalExecutionChainSingleton: records are bounded at max_records.
 48.  LocalExecutionChainSingleton: clear resets all counts.
 49.  record_local_execution: appends to global singleton.
 50.  record_local_execution: marks result openclawd_merged on canonical path.
 51.  record_local_execution: does not mark openclawd_merged for legacy path.
 52.  record_local_execution: emits warning for legacy paths.
 53.  record_local_execution: no warning for canonical paths.
 54.  get_local_execution_chain: returns LocalExecutionChainSingleton.
 55.  reset_local_execution_chain: produces a fresh singleton.
 56.  build_local_chain_snapshot: returns a LocalChainSnapshot.
 57.  build_local_chain_snapshot: snapshot_id is non-empty.
 58.  build_local_chain_snapshot: total_executions reflects recorded items.
 59.  LocalExecutionResult.from_dict: handles unknown chain_step gracefully.
 60.  LocalExecutionRecord.from_dict: handles unknown step values gracefully.
 61.  Two-chain model: LOCAL_CHAIN_ORDER step count is 6 (not 7 like cross-device).
 62.  Two-chain model: cross-device CANONICAL_CHAIN_ORDER has 7 steps.
 63.  Two-chain model: both chains share openclawd_dispatch as first step value.
 64.  Two-chain model: both chains share openclawd_feedback as last step value.
 65.  Two-chain model: local result type differs from cross-device ResultEnvelope.
 66.  Two-chain model: local snapshot type differs from CrossDeviceChainSnapshot.
 67.  Two-chain model: singletons are independent instances.
 68.  docs/LOCAL_EXECUTION_CHAIN.md exists on disk.
 69.  docs/CROSS_DEVICE_EXECUTION_CHAIN.md exists on disk.
 70.  docs/LOCAL_EXECUTION_CHAIN.md contains canonical step names.
 71.  docs/CROSS_DEVICE_EXECUTION_CHAIN.md contains canonical step names.
 72.  desktop_presence_runtime module docstring mentions LOCAL EXECUTION CHAIN.
 73.  desktop_presence_runtime module docstring mentions CROSS-DEVICE EXECUTION CHAIN.
 74.  cross_device_execution_chain module docstring mentions LOCAL EXECUTION CHAIN.
 75.  cross_device_execution_chain module docstring mentions two first-class chains.
 76.  LocalExecutionResult to_dict is JSON-serialisable (stdlib json).
 77.  LocalExecutionRecord to_dict is JSON-serialisable (stdlib json).
 78.  LocalChainSnapshot to_dict is JSON-serialisable (stdlib json).
 79.  build_local_execution_result: success via bool True in raw dict.
 80.  build_local_execution_result: error field from 'error_message' key.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset():
    from core.local_execution_chain import reset_local_execution_chain
    reset_local_execution_chain()


# ---------------------------------------------------------------------------
# 1-8. LocalChainStep enum and LOCAL_CHAIN_ORDER ordering
# ---------------------------------------------------------------------------


class TestLocalChainStep:
    def test_step_count_is_6(self):
        from core.local_execution_chain import LocalChainStep
        assert len(LocalChainStep) == 6

    def test_chain_order_matches_expected(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        expected = [
            "openclawd_dispatch",
            "agent_kernel_plan",
            "command_router_local",
            "local_executor",
            "result_capture",
            "openclawd_feedback",
        ]
        assert [s.value for s in LOCAL_CHAIN_ORDER] == expected

    def test_first_step_is_openclawd_dispatch(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_ORDER
        assert LOCAL_CHAIN_ORDER[0] is LocalChainStep.openclawd_dispatch

    def test_last_step_is_openclawd_feedback(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_ORDER
        assert LOCAL_CHAIN_ORDER[-1] is LocalChainStep.openclawd_feedback

    def test_agent_kernel_before_command_router(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        steps = [s.value for s in LOCAL_CHAIN_ORDER]
        assert steps.index("agent_kernel_plan") < steps.index("command_router_local")

    def test_command_router_before_local_executor(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        steps = [s.value for s in LOCAL_CHAIN_ORDER]
        assert steps.index("command_router_local") < steps.index("local_executor")

    def test_local_executor_before_result_capture(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        steps = [s.value for s in LOCAL_CHAIN_ORDER]
        assert steps.index("local_executor") < steps.index("result_capture")

    def test_result_capture_before_openclawd_feedback(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        steps = [s.value for s in LOCAL_CHAIN_ORDER]
        assert steps.index("result_capture") < steps.index("openclawd_feedback")


# ---------------------------------------------------------------------------
# 9-13. LOCAL_CHAIN_STEP_AUTHORITIES
# ---------------------------------------------------------------------------


class TestLocalChainStepAuthorities:
    def test_all_steps_covered(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_STEP_AUTHORITIES
        for step in LocalChainStep:
            assert step in LOCAL_CHAIN_STEP_AUTHORITIES

    def test_all_authority_strings_non_empty(self):
        from core.local_execution_chain import LOCAL_CHAIN_STEP_AUTHORITIES
        for step, authority in LOCAL_CHAIN_STEP_AUTHORITIES.items():
            assert isinstance(authority, str) and len(authority) > 0, (
                f"Step {step} has empty authority"
            )

    def test_openclawd_dispatch_authority(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_STEP_AUTHORITIES
        assert LOCAL_CHAIN_STEP_AUTHORITIES[LocalChainStep.openclawd_dispatch] == "core.openclawd"

    def test_openclawd_feedback_authority(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_STEP_AUTHORITIES
        assert LOCAL_CHAIN_STEP_AUTHORITIES[LocalChainStep.openclawd_feedback] == "core.openclawd"

    def test_command_router_authority(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_STEP_AUTHORITIES
        assert LOCAL_CHAIN_STEP_AUTHORITIES[LocalChainStep.command_router_local] == "core.command_router"

    def test_agent_kernel_authority(self):
        from core.local_execution_chain import LocalChainStep, LOCAL_CHAIN_STEP_AUTHORITIES
        assert LOCAL_CHAIN_STEP_AUTHORITIES[LocalChainStep.agent_kernel_plan] == "core.agent.kernel"


# ---------------------------------------------------------------------------
# 15-28. LocalExecutionResult
# ---------------------------------------------------------------------------


class TestLocalExecutionResult:
    def test_default_construction(self):
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult()
        assert r.task_id == ""
        assert r.success is False
        assert r.status == "unknown"

    def test_to_dict_keys(self):
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="t1", success=True, status="completed")
        d = r.to_dict()
        for key in ("task_id", "chain_step", "success", "status", "payload",
                    "error", "executor_module", "session_id", "result_id",
                    "timestamp", "extra", "openclawd_merged"):
            assert key in d

    def test_from_dict_round_trip(self):
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="rt1", success=True, status="done")
        d = r.to_dict()
        r2 = LocalExecutionResult.from_dict(d)
        assert r2.task_id == r.task_id
        assert r2.success == r.success
        assert r2.status == r.status
        assert r2.result_id == r.result_id

    def test_openclawd_merged_defaults_false(self):
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult()
        assert r.openclawd_merged is False

    def test_result_id_auto_generated(self):
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult()
        assert isinstance(r.result_id, str) and len(r.result_id) > 0

    def test_build_result_success_completed(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "completed"})
        assert r.success is True

    def test_build_result_success_success(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "success"})
        assert r.success is True

    def test_build_result_failure(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "failed"})
        assert r.success is False

    def test_build_result_payload_from_result_subdict(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "ok", "result": {"x": 1}})
        assert r.payload == {"x": 1}

    def test_build_result_payload_from_data_subdict(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "ok", "data": {"y": 2}})
        assert r.payload == {"y": 2}

    def test_build_result_excludes_image_base64(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "ok", "image_base64": "abc=="})
        assert "image_base64" not in r.payload

    def test_build_result_propagates_task_id_from_raw(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "ok", "task_id": "mytask"})
        assert r.task_id == "mytask"

    def test_build_result_propagates_session_id_kwarg(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "ok"}, session_id="sess1")
        assert r.session_id == "sess1"

    def test_build_result_chain_step_is_result_capture(self):
        from core.local_execution_chain import build_local_execution_result, LocalChainStep
        r = build_local_execution_result({"status": "ok"})
        assert r.chain_step is LocalChainStep.result_capture

    def test_build_result_success_via_bool_true(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": True})
        assert r.success is True

    def test_build_result_error_from_error_message(self):
        from core.local_execution_chain import build_local_execution_result
        r = build_local_execution_result({"status": "failed", "error_message": "oops"})
        assert r.error == "oops"


# ---------------------------------------------------------------------------
# 29-38. LocalExecutionRecord
# ---------------------------------------------------------------------------


class TestLocalExecutionRecord:
    def test_default_construction(self):
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord()
        assert r.task_id == ""
        assert r.is_canonical is False

    def test_to_dict_keys(self):
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord(task_id="t1")
        d = r.to_dict()
        for key in ("task_id", "session_id", "executor_module", "steps_completed",
                    "is_canonical", "legacy_path_used", "result", "record_id",
                    "dispatched_at", "completed_at", "extra"):
            assert key in d

    def test_from_dict_round_trip(self):
        from core.local_execution_chain import LocalExecutionRecord, LOCAL_CHAIN_ORDER
        r = LocalExecutionRecord(
            task_id="rt1", steps_completed=list(LOCAL_CHAIN_ORDER), is_canonical=True,
        )
        d = r.to_dict()
        r2 = LocalExecutionRecord.from_dict(d)
        assert r2.task_id == r.task_id
        assert r2.is_canonical == r.is_canonical
        assert [s.value for s in r2.steps_completed] == [s.value for s in r.steps_completed]

    def test_is_canonical_false_when_legacy_path_used(self):
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord(legacy_path_used="some_legacy")
        assert r.is_canonical is False

    def test_build_record_canonical_when_steps_match_order(self):
        from core.local_execution_chain import build_local_execution_record, LOCAL_CHAIN_ORDER
        r = build_local_execution_record(steps_completed=list(LOCAL_CHAIN_ORDER))
        assert r.is_canonical is True

    def test_build_record_non_canonical_with_legacy_path(self):
        from core.local_execution_chain import build_local_execution_record
        r = build_local_execution_record(legacy_path_used="old_adapter")
        assert r.is_canonical is False

    def test_build_record_steps_default_to_canonical_order(self):
        from core.local_execution_chain import build_local_execution_record, LOCAL_CHAIN_ORDER
        r = build_local_execution_record()
        assert r.steps_completed == list(LOCAL_CHAIN_ORDER)

    def test_build_record_steps_default_to_empty_for_legacy(self):
        from core.local_execution_chain import build_local_execution_record
        r = build_local_execution_record(legacy_path_used="old_path")
        assert r.steps_completed == []

    def test_build_record_completed_at_set_when_result_provided(self):
        from core.local_execution_chain import build_local_execution_record, LocalExecutionResult
        result = LocalExecutionResult(success=True, status="done")
        r = build_local_execution_record(result=result)
        assert r.completed_at is not None

    def test_build_record_completed_at_none_without_result(self):
        from core.local_execution_chain import build_local_execution_record
        r = build_local_execution_record()
        assert r.completed_at is None


# ---------------------------------------------------------------------------
# 39-41. LocalChainSnapshot
# ---------------------------------------------------------------------------


class TestLocalChainSnapshot:
    def test_to_dict_keys(self):
        from core.local_execution_chain import LocalChainSnapshot
        s = LocalChainSnapshot()
        d = s.to_dict()
        for key in ("total_executions", "canonical_executions", "legacy_executions",
                    "recent_records", "chain_authority_map", "canonical_chain_order",
                    "snapshot_id", "timestamp"):
            assert key in d

    def test_canonical_chain_order_values(self):
        from core.local_execution_chain import build_local_chain_snapshot, LOCAL_CHAIN_ORDER
        _reset()
        snap = build_local_chain_snapshot()
        assert snap.canonical_chain_order == [s.value for s in LOCAL_CHAIN_ORDER]

    def test_chain_authority_map_all_step_keys(self):
        from core.local_execution_chain import build_local_chain_snapshot, LocalChainStep
        _reset()
        snap = build_local_chain_snapshot()
        for step in LocalChainStep:
            assert step.value in snap.chain_authority_map


# ---------------------------------------------------------------------------
# 42-48. LocalExecutionChainSingleton
# ---------------------------------------------------------------------------


class TestLocalExecutionChainSingleton:
    def setup_method(self):
        _reset()

    def test_initial_total_zero(self):
        from core.local_execution_chain import get_local_execution_chain
        chain = get_local_execution_chain()
        snap = chain.snapshot()
        assert snap.total_executions == 0

    def test_append_increments_total(self):
        from core.local_execution_chain import get_local_execution_chain, LocalExecutionRecord, LOCAL_CHAIN_ORDER
        chain = get_local_execution_chain()
        rec = LocalExecutionRecord(steps_completed=list(LOCAL_CHAIN_ORDER), is_canonical=True)
        chain.append(rec)
        assert chain.snapshot().total_executions == 1

    def test_append_increments_canonical_count(self):
        from core.local_execution_chain import get_local_execution_chain, LocalExecutionRecord, LOCAL_CHAIN_ORDER
        chain = get_local_execution_chain()
        rec = LocalExecutionRecord(steps_completed=list(LOCAL_CHAIN_ORDER), is_canonical=True)
        chain.append(rec)
        assert chain.snapshot().canonical_executions == 1

    def test_append_increments_legacy_count(self):
        from core.local_execution_chain import get_local_execution_chain, LocalExecutionRecord
        chain = get_local_execution_chain()
        rec = LocalExecutionRecord(legacy_path_used="old", is_canonical=False)
        chain.append(rec)
        assert chain.snapshot().legacy_executions == 1

    def test_snapshot_recent_records_bounded(self):
        from core.local_execution_chain import get_local_execution_chain, LocalExecutionRecord
        chain = get_local_execution_chain()
        for i in range(30):
            chain.append(LocalExecutionRecord(task_id=f"t{i}"))
        snap = chain.snapshot(max_recent=5)
        assert len(snap.recent_records) == 5

    def test_singleton_records_bounded_at_max(self):
        from core.local_execution_chain import LocalExecutionChainSingleton, LocalExecutionRecord
        chain = LocalExecutionChainSingleton(max_records=5)
        for i in range(10):
            chain.append(LocalExecutionRecord(task_id=f"t{i}"))
        assert len(chain._records) == 5

    def test_clear_resets_counts(self):
        from core.local_execution_chain import get_local_execution_chain, LocalExecutionRecord, LOCAL_CHAIN_ORDER
        chain = get_local_execution_chain()
        chain.append(LocalExecutionRecord(steps_completed=list(LOCAL_CHAIN_ORDER), is_canonical=True))
        chain.clear()
        snap = chain.snapshot()
        assert snap.total_executions == 0
        assert snap.canonical_executions == 0
        assert snap.recent_records == []


# ---------------------------------------------------------------------------
# 49-58. record_local_execution and builder functions
# ---------------------------------------------------------------------------


class TestRecordLocalExecution:
    def setup_method(self):
        _reset()

    def test_record_appends_to_singleton(self):
        from core.local_execution_chain import record_local_execution, get_local_execution_chain
        record_local_execution(task_id="t1")
        assert get_local_execution_chain().snapshot().total_executions == 1

    def test_record_marks_openclawd_merged_for_canonical(self):
        from core.local_execution_chain import (
            record_local_execution, LocalExecutionResult, LOCAL_CHAIN_ORDER
        )
        result = LocalExecutionResult(success=True)
        rec = record_local_execution(
            task_id="t2",
            steps_completed=list(LOCAL_CHAIN_ORDER),
            result=result,
        )
        assert rec.result.openclawd_merged is True

    def test_record_does_not_mark_merged_for_legacy(self):
        from core.local_execution_chain import record_local_execution, LocalExecutionResult
        result = LocalExecutionResult(success=True)
        rec = record_local_execution(
            task_id="t3",
            legacy_path_used="old_adapter",
            result=result,
        )
        assert rec.result.openclawd_merged is False

    def test_record_emits_warning_for_legacy(self, caplog):
        from core.local_execution_chain import record_local_execution
        with caplog.at_level(logging.WARNING, logger="Galaxy.LocalExecutionChain"):
            record_local_execution(task_id="t4", legacy_path_used="bad_path")
        assert any("LEGACY LOCAL CHAIN PATH" in msg for msg in caplog.messages)

    def test_record_no_warning_for_canonical(self, caplog):
        from core.local_execution_chain import record_local_execution, LOCAL_CHAIN_ORDER
        with caplog.at_level(logging.WARNING, logger="Galaxy.LocalExecutionChain"):
            record_local_execution(task_id="t5", steps_completed=list(LOCAL_CHAIN_ORDER))
        assert not any("LEGACY LOCAL CHAIN PATH" in msg for msg in caplog.messages)

    def test_get_local_execution_chain_returns_singleton(self):
        from core.local_execution_chain import get_local_execution_chain, LocalExecutionChainSingleton
        chain = get_local_execution_chain()
        assert isinstance(chain, LocalExecutionChainSingleton)

    def test_reset_produces_fresh_singleton(self):
        from core.local_execution_chain import (
            get_local_execution_chain, reset_local_execution_chain, LocalExecutionRecord
        )
        get_local_execution_chain().append(LocalExecutionRecord(task_id="before"))
        reset_local_execution_chain()
        assert get_local_execution_chain().snapshot().total_executions == 0

    def test_build_local_chain_snapshot_returns_snapshot(self):
        from core.local_execution_chain import build_local_chain_snapshot, LocalChainSnapshot
        snap = build_local_chain_snapshot()
        assert isinstance(snap, LocalChainSnapshot)

    def test_build_local_chain_snapshot_id_non_empty(self):
        from core.local_execution_chain import build_local_chain_snapshot
        snap = build_local_chain_snapshot()
        assert len(snap.snapshot_id) > 0

    def test_build_local_chain_snapshot_total_reflects_records(self):
        from core.local_execution_chain import record_local_execution, build_local_chain_snapshot
        record_local_execution(task_id="counted1")
        record_local_execution(task_id="counted2")
        snap = build_local_chain_snapshot()
        assert snap.total_executions == 2


# ---------------------------------------------------------------------------
# 59-60. from_dict graceful handling of unknown values
# ---------------------------------------------------------------------------


class TestFromDictGraceful:
    def test_result_from_dict_unknown_chain_step(self):
        from core.local_execution_chain import LocalExecutionResult, LocalChainStep
        d = {
            "task_id": "x",
            "chain_step": "nonexistent_step",
            "success": True,
            "status": "ok",
        }
        r = LocalExecutionResult.from_dict(d)
        assert r.chain_step is LocalChainStep.result_capture

    def test_record_from_dict_unknown_step_values(self):
        from core.local_execution_chain import LocalExecutionRecord
        d = {
            "task_id": "x",
            "steps_completed": ["unknown_step_1", "openclawd_dispatch"],
            "is_canonical": False,
        }
        rec = LocalExecutionRecord.from_dict(d)
        # Unknown steps are skipped; only valid one remains
        valid_steps = [s.value for s in rec.steps_completed]
        assert "openclawd_dispatch" in valid_steps
        assert "unknown_step_1" not in valid_steps


# ---------------------------------------------------------------------------
# 61-67. Two-chain model symmetry
# ---------------------------------------------------------------------------


class TestTwoChainModel:
    def test_local_chain_has_6_steps(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        assert len(LOCAL_CHAIN_ORDER) == 6

    def test_cross_device_chain_has_7_steps(self):
        from core.cross_device_execution_chain import CANONICAL_CHAIN_ORDER
        assert len(CANONICAL_CHAIN_ORDER) == 7

    def test_both_chains_start_with_openclawd_dispatch(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        from core.cross_device_execution_chain import CANONICAL_CHAIN_ORDER
        assert LOCAL_CHAIN_ORDER[0].value == "openclawd_dispatch"
        assert CANONICAL_CHAIN_ORDER[0].value == "openclawd_dispatch"

    def test_both_chains_end_with_openclawd_feedback(self):
        from core.local_execution_chain import LOCAL_CHAIN_ORDER
        from core.cross_device_execution_chain import CANONICAL_CHAIN_ORDER
        assert LOCAL_CHAIN_ORDER[-1].value == "openclawd_feedback"
        assert CANONICAL_CHAIN_ORDER[-1].value == "openclawd_feedback"

    def test_local_result_type_differs_from_cross_device(self):
        from core.local_execution_chain import LocalExecutionResult
        from core.cross_device_execution_chain import ResultEnvelope
        assert LocalExecutionResult is not ResultEnvelope

    def test_local_snapshot_type_differs_from_cross_device(self):
        from core.local_execution_chain import LocalChainSnapshot
        from core.cross_device_execution_chain import CrossDeviceChainSnapshot
        assert LocalChainSnapshot is not CrossDeviceChainSnapshot

    def test_singletons_are_independent(self):
        from core.local_execution_chain import get_local_execution_chain, reset_local_execution_chain
        from core.cross_device_execution_chain import get_cross_device_chain, reset_cross_device_chain
        reset_local_execution_chain()
        reset_cross_device_chain()
        assert get_local_execution_chain() is not get_cross_device_chain()


# ---------------------------------------------------------------------------
# 68-75. Docs and runtime-comment presence
# ---------------------------------------------------------------------------


class TestDocsAndCommentPresence:
    def test_local_execution_chain_doc_exists(self):
        doc_path = os.path.join(_PROJECT_ROOT, "docs", "LOCAL_EXECUTION_CHAIN.md")
        assert os.path.isfile(doc_path), "docs/LOCAL_EXECUTION_CHAIN.md must exist"

    def test_cross_device_execution_chain_doc_exists(self):
        doc_path = os.path.join(_PROJECT_ROOT, "docs", "CROSS_DEVICE_EXECUTION_CHAIN.md")
        assert os.path.isfile(doc_path), "docs/CROSS_DEVICE_EXECUTION_CHAIN.md must exist"

    def test_local_chain_doc_contains_canonical_step_names(self):
        doc_path = os.path.join(_PROJECT_ROOT, "docs", "LOCAL_EXECUTION_CHAIN.md")
        content = open(doc_path).read()
        for step_name in ("openclawd_dispatch", "agent_kernel_plan",
                          "command_router_local", "local_executor",
                          "result_capture", "openclawd_feedback"):
            assert step_name in content, f"LOCAL_EXECUTION_CHAIN.md missing step: {step_name}"

    def test_cross_device_chain_doc_contains_canonical_step_names(self):
        doc_path = os.path.join(_PROJECT_ROOT, "docs", "CROSS_DEVICE_EXECUTION_CHAIN.md")
        content = open(doc_path).read()
        for step_name in ("openclawd_dispatch", "command_router", "task_envelope",
                          "gateway_substrate", "worker_executor",
                          "result_envelope", "openclawd_feedback"):
            assert step_name in content, f"CROSS_DEVICE_EXECUTION_CHAIN.md missing step: {step_name}"

    def test_desktop_presence_runtime_mentions_local_chain(self):
        dpr_path = os.path.join(_PROJECT_ROOT, "core", "desktop_presence_runtime.py")
        content = open(dpr_path).read()
        assert "LOCAL EXECUTION CHAIN" in content

    def test_desktop_presence_runtime_mentions_cross_device_chain(self):
        dpr_path = os.path.join(_PROJECT_ROOT, "core", "desktop_presence_runtime.py")
        content = open(dpr_path).read()
        assert "CROSS-DEVICE EXECUTION CHAIN" in content

    def test_cross_device_chain_module_mentions_local_chain(self):
        cdc_path = os.path.join(_PROJECT_ROOT, "core", "cross_device_execution_chain.py")
        content = open(cdc_path).read()
        assert "LOCAL EXECUTION CHAIN" in content

    def test_cross_device_chain_module_mentions_two_chains(self):
        cdc_path = os.path.join(_PROJECT_ROOT, "core", "cross_device_execution_chain.py")
        content = open(cdc_path).read()
        assert "two first-class" in content or "first-class runtime chains" in content


# ---------------------------------------------------------------------------
# 76-78. JSON-serialisability guardrails
# ---------------------------------------------------------------------------


class TestJsonSerialisability:
    def test_local_execution_result_to_dict_json_serialisable(self):
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="j1", success=True, status="ok",
                                  payload={"a": 1}, error=None)
        json.dumps(r.to_dict())

    def test_local_execution_record_to_dict_json_serialisable(self):
        from core.local_execution_chain import LocalExecutionRecord, LOCAL_CHAIN_ORDER
        r = LocalExecutionRecord(
            task_id="j2",
            steps_completed=list(LOCAL_CHAIN_ORDER),
            is_canonical=True,
        )
        json.dumps(r.to_dict())

    def test_local_chain_snapshot_to_dict_json_serialisable(self):
        _reset()
        from core.local_execution_chain import build_local_chain_snapshot
        snap = build_local_chain_snapshot()
        json.dumps(snap.to_dict())
