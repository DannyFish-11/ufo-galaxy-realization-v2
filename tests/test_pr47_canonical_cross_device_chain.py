#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr47_canonical_cross_device_chain.py
=================================================
PR-7 — Canonicalize OpenClawd Cross-Device Execution Chain

Validates:
  1. CanonicalChainStep enum and CANONICAL_CHAIN_ORDER ordering.
  2. CHAIN_STEP_AUTHORITIES maps all steps to non-empty authority strings.
  3. ResultEnvelope: construction, to_dict/from_dict round-trip, field defaults.
  4. build_result_envelope: normalises raw result dicts correctly.
  5. ChainExecutionRecord: is_canonical detection, to_dict/from_dict round-trip.
  6. build_chain_execution_record: canonical vs legacy path detection.
  7. record_chain_execution: appends to singleton, marks envelope openclawd_merged.
  8. CrossDeviceChainSingleton: append, snapshot counts, clear.
  9. build_cross_device_chain_snapshot: structure and authority map.
 10. get_cross_device_chain / reset_cross_device_chain: singleton lifecycle.
 11. Legacy path entries: PR-7 entries are present in LEGACY_PATH_REGISTRY.
 12. Legacy path entries: galaxy_orchestrator is classified LEGACY_COMPATIBILITY.
 13. Legacy path entries: device_router.route_task is classified LEGACY_COMPATIBILITY.
 14. openclawd_memory_backflow.store_result_envelope: canonical backflow path.
 15. openclawd_memory_backflow.store_result_envelope: graceful when chain unavailable.
 16. Cross-device policy: legacy authority role still blocks expansion.
 17. Cross-device policy: resolve_routing returns canonical posture for cross_device domain.
 18. GalaxyOrchestrator class docstring demoted.
 19. record_chain_execution: emits warning for legacy paths.
 20. record_chain_execution: no warning for canonical paths.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

import os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# 1. CanonicalChainStep enum and CANONICAL_CHAIN_ORDER ordering
# ---------------------------------------------------------------------------


class TestCanonicalChainStep:
    def test_all_steps_present(self):
        from core.cross_device_execution_chain import CanonicalChainStep, CANONICAL_CHAIN_ORDER

        expected = [
            "openclawd_dispatch",
            "command_router",
            "task_envelope",
            "gateway_substrate",
            "worker_executor",
            "result_envelope",
            "openclawd_feedback",
        ]
        assert [s.value for s in CANONICAL_CHAIN_ORDER] == expected

    def test_step_count(self):
        from core.cross_device_execution_chain import CanonicalChainStep
        assert len(CanonicalChainStep) == 7

    def test_step_values_are_strings(self):
        from core.cross_device_execution_chain import CanonicalChainStep
        for step in CanonicalChainStep:
            assert isinstance(step.value, str)
            assert len(step.value) > 0

    def test_openclawd_is_first(self):
        from core.cross_device_execution_chain import CanonicalChainStep, CANONICAL_CHAIN_ORDER
        assert CANONICAL_CHAIN_ORDER[0] is CanonicalChainStep.openclawd_dispatch

    def test_openclawd_feedback_is_last(self):
        from core.cross_device_execution_chain import CanonicalChainStep, CANONICAL_CHAIN_ORDER
        assert CANONICAL_CHAIN_ORDER[-1] is CanonicalChainStep.openclawd_feedback

    def test_command_router_before_gateway(self):
        from core.cross_device_execution_chain import CanonicalChainStep, CANONICAL_CHAIN_ORDER
        steps = [s.value for s in CANONICAL_CHAIN_ORDER]
        assert steps.index("command_router") < steps.index("gateway_substrate")

    def test_gateway_before_worker(self):
        from core.cross_device_execution_chain import CanonicalChainStep, CANONICAL_CHAIN_ORDER
        steps = [s.value for s in CANONICAL_CHAIN_ORDER]
        assert steps.index("gateway_substrate") < steps.index("worker_executor")

    def test_result_envelope_after_worker(self):
        from core.cross_device_execution_chain import CanonicalChainStep, CANONICAL_CHAIN_ORDER
        steps = [s.value for s in CANONICAL_CHAIN_ORDER]
        assert steps.index("worker_executor") < steps.index("result_envelope")


# ---------------------------------------------------------------------------
# 2. CHAIN_STEP_AUTHORITIES
# ---------------------------------------------------------------------------


class TestChainStepAuthorities:
    def test_all_steps_have_authority(self):
        from core.cross_device_execution_chain import (
            CanonicalChainStep,
            CHAIN_STEP_AUTHORITIES,
        )
        for step in CanonicalChainStep:
            assert step in CHAIN_STEP_AUTHORITIES
            assert isinstance(CHAIN_STEP_AUTHORITIES[step], str)
            assert len(CHAIN_STEP_AUTHORITIES[step]) > 0

    def test_openclawd_owns_dispatch_and_feedback(self):
        from core.cross_device_execution_chain import (
            CanonicalChainStep,
            CHAIN_STEP_AUTHORITIES,
        )
        assert "OpenClawd" in CHAIN_STEP_AUTHORITIES[CanonicalChainStep.openclawd_dispatch]
        assert "OpenClawd" in CHAIN_STEP_AUTHORITIES[CanonicalChainStep.openclawd_feedback]

    def test_command_router_owns_router_step(self):
        from core.cross_device_execution_chain import (
            CanonicalChainStep,
            CHAIN_STEP_AUTHORITIES,
        )
        assert "CommandRouter" in CHAIN_STEP_AUTHORITIES[CanonicalChainStep.command_router]

    def test_gateway_is_substrate_only(self):
        from core.cross_device_execution_chain import (
            CanonicalChainStep,
            CHAIN_STEP_AUTHORITIES,
        )
        # Gateway is substrate only, not a planning authority.
        authority = CHAIN_STEP_AUTHORITIES[CanonicalChainStep.gateway_substrate]
        assert "substrate" in authority.lower() or "galaxy_gateway" in authority.lower()

    def test_worker_is_executor_only(self):
        from core.cross_device_execution_chain import (
            CanonicalChainStep,
            CHAIN_STEP_AUTHORITIES,
        )
        authority = CHAIN_STEP_AUTHORITIES[CanonicalChainStep.worker_executor]
        assert "executor" in authority.lower() or "worker" in authority.lower()


# ---------------------------------------------------------------------------
# 3. ResultEnvelope construction and round-trip
# ---------------------------------------------------------------------------


class TestResultEnvelope:
    def test_defaults(self):
        from core.cross_device_execution_chain import ResultEnvelope, CanonicalChainStep
        env = ResultEnvelope()
        assert env.task_id == ""
        assert env.device_id == ""
        assert env.chain_step is CanonicalChainStep.result_envelope
        assert env.success is False
        assert env.openclawd_merged is False
        assert env.projected is False
        assert env.audited is False
        assert env.memory_backflow_stored is False
        assert isinstance(env.result_id, str) and len(env.result_id) > 0

    def test_to_dict_keys(self):
        from core.cross_device_execution_chain import ResultEnvelope
        env = ResultEnvelope(task_id="t1", device_id="d1", success=True, status="success")
        d = env.to_dict()
        expected_keys = {
            "result_id", "task_id", "device_id", "chain_step", "success",
            "status", "payload", "error", "trace_id", "session_id", "route_mode",
            "openclawd_merged", "projected", "audited", "memory_backflow_stored",
            "timestamp", "extra",
        }
        assert expected_keys == set(d.keys())
        assert d["task_id"] == "t1"
        assert d["device_id"] == "d1"
        assert d["success"] is True

    def test_from_dict_round_trip(self):
        from core.cross_device_execution_chain import ResultEnvelope
        env = ResultEnvelope(
            task_id="t2",
            device_id="d2",
            success=True,
            status="completed",
            route_mode="hybrid",
            trace_id="tr123",
        )
        d = env.to_dict()
        env2 = ResultEnvelope.from_dict(d)
        assert env2.task_id == "t2"
        assert env2.device_id == "d2"
        assert env2.success is True
        assert env2.status == "completed"
        assert env2.route_mode == "hybrid"
        assert env2.trace_id == "tr123"

    def test_from_dict_unknown_chain_step_defaults(self):
        from core.cross_device_execution_chain import ResultEnvelope, CanonicalChainStep
        env = ResultEnvelope.from_dict({"chain_step": "nonexistent_step"})
        assert env.chain_step is CanonicalChainStep.result_envelope

    def test_result_id_is_unique(self):
        from core.cross_device_execution_chain import ResultEnvelope
        ids = {ResultEnvelope().result_id for _ in range(10)}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# 4. build_result_envelope
# ---------------------------------------------------------------------------


class TestBuildResultEnvelope:
    def test_success_from_status_string(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope(
            {"status": "success", "data": {"val": 1}},
            task_id="t1",
            device_id="d1",
        )
        assert env.success is True
        assert env.task_id == "t1"
        assert env.device_id == "d1"

    def test_completed_is_success(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({"status": "completed"})
        assert env.success is True

    def test_failure_status(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({"status": "failed", "error": "timeout"})
        assert env.success is False
        assert env.error == "timeout"

    def test_payload_from_result_sub_dict(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({"status": "ok", "result": {"screenshot": "abc"}})
        assert "screenshot" in env.payload

    def test_large_fields_excluded_from_payload(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({
            "status": "ok",
            "image_base64": "VERYLARGE",
            "other": "kept",
        })
        assert "image_base64" not in env.payload
        assert "other" in env.payload

    def test_trace_id_from_arg_takes_precedence(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope(
            {"status": "ok", "trace_id": "from_raw"},
            trace_id="from_arg",
        )
        assert env.trace_id == "from_arg"

    def test_trace_id_from_raw_result(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({"status": "ok", "trace_id": "raw_trace"})
        assert env.trace_id == "raw_trace"

    def test_bool_true_status(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({"status": True})
        assert env.success is True

    def test_bool_false_status(self):
        from core.cross_device_execution_chain import build_result_envelope
        env = build_result_envelope({"status": False})
        assert env.success is False


# ---------------------------------------------------------------------------
# 5–6. ChainExecutionRecord and build_chain_execution_record
# ---------------------------------------------------------------------------


class TestChainExecutionRecord:
    def test_is_canonical_full_chain(self):
        from core.cross_device_execution_chain import (
            build_chain_execution_record,
            CANONICAL_CHAIN_ORDER,
        )
        rec = build_chain_execution_record(
            task_id="t1",
            device_id="d1",
            steps_completed=list(CANONICAL_CHAIN_ORDER),
        )
        assert rec.is_canonical is True
        assert rec.legacy_path_used is None

    def test_is_not_canonical_partial_steps(self):
        from core.cross_device_execution_chain import (
            build_chain_execution_record,
            CanonicalChainStep,
        )
        rec = build_chain_execution_record(
            task_id="t2",
            steps_completed=[CanonicalChainStep.openclawd_dispatch],
        )
        assert rec.is_canonical is False

    def test_legacy_path_used_marks_non_canonical(self):
        from core.cross_device_execution_chain import (
            build_chain_execution_record,
            CANONICAL_CHAIN_ORDER,
        )
        rec = build_chain_execution_record(
            task_id="t3",
            legacy_path_used="galaxy_gateway.orchestrator.galaxy_orchestrator",
            steps_completed=list(CANONICAL_CHAIN_ORDER),
        )
        assert rec.is_canonical is False
        assert rec.legacy_path_used == "galaxy_gateway.orchestrator.galaxy_orchestrator"

    def test_no_steps_provided_defaults_to_canonical(self):
        from core.cross_device_execution_chain import (
            build_chain_execution_record,
            CANONICAL_CHAIN_ORDER,
        )
        rec = build_chain_execution_record(task_id="t4")
        assert rec.steps_completed == list(CANONICAL_CHAIN_ORDER)
        assert rec.is_canonical is True

    def test_no_steps_provided_legacy_path_defaults_empty(self):
        from core.cross_device_execution_chain import build_chain_execution_record
        rec = build_chain_execution_record(
            task_id="t5",
            legacy_path_used="some.legacy.path",
        )
        assert rec.steps_completed == []
        assert rec.is_canonical is False

    def test_completed_at_set_when_result_envelope_provided(self):
        from core.cross_device_execution_chain import (
            build_chain_execution_record,
            ResultEnvelope,
        )
        env = ResultEnvelope(task_id="t6", success=True)
        rec = build_chain_execution_record(task_id="t6", result_envelope=env)
        assert rec.completed_at is not None
        assert rec.completed_at <= time.time()

    def test_to_dict_keys(self):
        from core.cross_device_execution_chain import build_chain_execution_record
        rec = build_chain_execution_record(task_id="t7", device_id="d7")
        d = rec.to_dict()
        expected_keys = {
            "record_id", "task_id", "trace_id", "device_id", "route_mode",
            "steps_completed", "is_canonical", "legacy_path_used",
            "result_envelope", "dispatched_at", "completed_at", "extra",
        }
        assert expected_keys == set(d.keys())

    def test_from_dict_round_trip(self):
        from core.cross_device_execution_chain import build_chain_execution_record, ResultEnvelope
        env = ResultEnvelope(task_id="t8", success=True)
        rec = build_chain_execution_record(
            task_id="t8",
            device_id="d8",
            route_mode="hybrid",
            result_envelope=env,
        )
        d = rec.to_dict()
        rec2 = rec.__class__.from_dict(d)
        assert rec2.task_id == "t8"
        assert rec2.device_id == "d8"
        assert rec2.route_mode == "hybrid"
        assert rec2.result_envelope is not None
        assert rec2.result_envelope.task_id == "t8"

    def test_from_dict_unknown_step_skipped(self):
        from core.cross_device_execution_chain import ChainExecutionRecord
        rec = ChainExecutionRecord.from_dict({
            "steps_completed": ["openclawd_dispatch", "UNKNOWN_STEP", "result_envelope"],
        })
        step_values = [s.value for s in rec.steps_completed]
        assert "UNKNOWN_STEP" not in step_values
        assert "openclawd_dispatch" in step_values
        assert "result_envelope" in step_values


# ---------------------------------------------------------------------------
# 7. record_chain_execution
# ---------------------------------------------------------------------------


class TestRecordChainExecution:
    def setup_method(self):
        from core.cross_device_execution_chain import reset_cross_device_chain
        reset_cross_device_chain()

    def test_record_appended_to_singleton(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            get_cross_device_chain,
        )
        record_chain_execution(task_id="task_rc1", device_id="dev1")
        chain = get_cross_device_chain()
        snap = chain.snapshot()
        assert snap.total_executions == 1

    def test_canonical_record_marks_envelope_merged(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            ResultEnvelope,
            CANONICAL_CHAIN_ORDER,
        )
        env = ResultEnvelope(task_id="t_merge", success=True)
        assert env.openclawd_merged is False
        record_chain_execution(
            task_id="t_merge",
            steps_completed=list(CANONICAL_CHAIN_ORDER),
            result_envelope=env,
        )
        assert env.openclawd_merged is True

    def test_legacy_path_does_not_mark_envelope_merged(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            ResultEnvelope,
        )
        env = ResultEnvelope(task_id="t_leg", success=True)
        record_chain_execution(
            task_id="t_leg",
            legacy_path_used="galaxy_gateway.orchestrator.galaxy_orchestrator",
            result_envelope=env,
        )
        assert env.openclawd_merged is False

    def test_legacy_path_emits_warning(self, caplog):
        import logging
        from core.cross_device_execution_chain import record_chain_execution
        with caplog.at_level(logging.WARNING, logger="Galaxy.CrossDeviceExecutionChain"):
            record_chain_execution(
                task_id="t_warn",
                legacy_path_used="some.legacy.path",
            )
        assert any("LEGACY CHAIN PATH" in r.message for r in caplog.records)

    def test_canonical_path_does_not_emit_warning(self, caplog):
        import logging
        from core.cross_device_execution_chain import record_chain_execution, CANONICAL_CHAIN_ORDER
        with caplog.at_level(logging.WARNING, logger="Galaxy.CrossDeviceExecutionChain"):
            record_chain_execution(
                task_id="t_no_warn",
                steps_completed=list(CANONICAL_CHAIN_ORDER),
            )
        legacy_warnings = [
            r for r in caplog.records
            if "LEGACY CHAIN PATH" in r.message
        ]
        assert len(legacy_warnings) == 0

    def test_returns_chain_execution_record(self):
        from core.cross_device_execution_chain import record_chain_execution, ChainExecutionRecord
        rec = record_chain_execution(task_id="t_ret", device_id="d_ret")
        assert isinstance(rec, ChainExecutionRecord)


# ---------------------------------------------------------------------------
# 8. CrossDeviceChainSingleton counts
# ---------------------------------------------------------------------------


class TestCrossDeviceChainSingleton:
    def setup_method(self):
        from core.cross_device_execution_chain import reset_cross_device_chain
        reset_cross_device_chain()

    def test_canonical_count(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            get_cross_device_chain,
            CANONICAL_CHAIN_ORDER,
        )
        record_chain_execution(task_id="c1", steps_completed=list(CANONICAL_CHAIN_ORDER))
        record_chain_execution(task_id="c2", steps_completed=list(CANONICAL_CHAIN_ORDER))
        snap = get_cross_device_chain().snapshot()
        assert snap.canonical_executions == 2
        assert snap.legacy_executions == 0

    def test_legacy_count(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            get_cross_device_chain,
        )
        record_chain_execution(
            task_id="l1",
            legacy_path_used="galaxy_gateway.orchestrator.galaxy_orchestrator",
        )
        snap = get_cross_device_chain().snapshot()
        assert snap.canonical_executions == 0
        assert snap.legacy_executions == 1

    def test_total_count(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            get_cross_device_chain,
            CANONICAL_CHAIN_ORDER,
        )
        for i in range(5):
            record_chain_execution(
                task_id=f"t{i}",
                steps_completed=list(CANONICAL_CHAIN_ORDER),
            )
        snap = get_cross_device_chain().snapshot()
        assert snap.total_executions == 5

    def test_clear_resets_counts(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            get_cross_device_chain,
        )
        record_chain_execution(task_id="c1")
        get_cross_device_chain().clear()
        snap = get_cross_device_chain().snapshot()
        assert snap.total_executions == 0
        assert snap.canonical_executions == 0
        assert snap.legacy_executions == 0

    def test_max_records_bounded(self):
        from core.cross_device_execution_chain import CrossDeviceChainSingleton, build_chain_execution_record
        small = CrossDeviceChainSingleton(max_records=3)
        for i in range(10):
            small.append(build_chain_execution_record(task_id=f"t{i}"))
        assert len(small._records) == 3

    def test_recent_records_limited(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            get_cross_device_chain,
            CANONICAL_CHAIN_ORDER,
        )
        for i in range(25):
            record_chain_execution(
                task_id=f"tr{i}",
                steps_completed=list(CANONICAL_CHAIN_ORDER),
            )
        snap = get_cross_device_chain().snapshot(max_recent=10)
        assert len(snap.recent_records) == 10


# ---------------------------------------------------------------------------
# 9. build_cross_device_chain_snapshot
# ---------------------------------------------------------------------------


class TestBuildCrossDeviceChainSnapshot:
    def setup_method(self):
        from core.cross_device_execution_chain import reset_cross_device_chain
        reset_cross_device_chain()

    def test_snapshot_structure(self):
        from core.cross_device_execution_chain import build_cross_device_chain_snapshot
        snap = build_cross_device_chain_snapshot()
        d = snap.to_dict()
        expected_keys = {
            "snapshot_id", "total_executions", "canonical_executions",
            "legacy_executions", "recent_records", "chain_authority_map",
            "canonical_chain_order", "timestamp",
        }
        assert expected_keys == set(d.keys())

    def test_canonical_chain_order_in_snapshot(self):
        from core.cross_device_execution_chain import (
            build_cross_device_chain_snapshot,
            CANONICAL_CHAIN_ORDER,
        )
        snap = build_cross_device_chain_snapshot()
        assert snap.canonical_chain_order == [s.value for s in CANONICAL_CHAIN_ORDER]

    def test_authority_map_in_snapshot(self):
        from core.cross_device_execution_chain import (
            build_cross_device_chain_snapshot,
            CanonicalChainStep,
        )
        snap = build_cross_device_chain_snapshot()
        assert "openclawd_dispatch" in snap.chain_authority_map
        assert "command_router" in snap.chain_authority_map
        assert "gateway_substrate" in snap.chain_authority_map


# ---------------------------------------------------------------------------
# 10. get_cross_device_chain / reset_cross_device_chain
# ---------------------------------------------------------------------------


class TestSingletonLifecycle:
    def test_get_returns_same_instance(self):
        from core.cross_device_execution_chain import get_cross_device_chain
        a = get_cross_device_chain()
        b = get_cross_device_chain()
        assert a is b

    def test_reset_creates_new_instance(self):
        from core.cross_device_execution_chain import (
            get_cross_device_chain,
            reset_cross_device_chain,
        )
        a = get_cross_device_chain()
        reset_cross_device_chain()
        b = get_cross_device_chain()
        assert a is not b

    def test_reset_clears_state(self):
        from core.cross_device_execution_chain import (
            record_chain_execution,
            reset_cross_device_chain,
            build_cross_device_chain_snapshot,
        )
        record_chain_execution(task_id="before_reset")
        reset_cross_device_chain()
        snap = build_cross_device_chain_snapshot()
        assert snap.total_executions == 0


# ---------------------------------------------------------------------------
# 11–13. Legacy path entries in LEGACY_PATH_REGISTRY (PR-7 additions)
# ---------------------------------------------------------------------------


class TestLegacyPathRegistryPR7:
    def test_galaxy_orchestrator_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "galaxy_gateway.orchestrator.galaxy_orchestrator" in LEGACY_PATH_REGISTRY

    def test_task_orchestrator_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator"
            in LEGACY_PATH_REGISTRY
        )

    def test_device_router_route_task_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "galaxy_gateway.device_router.DeviceRouter.route_task" in LEGACY_PATH_REGISTRY

    def test_cross_device_coordinator_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator"
            in LEGACY_PATH_REGISTRY
        )

    def test_galaxy_orchestrator_is_legacy_compatibility(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.orchestrator.galaxy_orchestrator"]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_all_pr7_entries_have_pr7_guardrail(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        pr7_paths = [
            "galaxy_gateway.orchestrator.galaxy_orchestrator",
            "galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator",
            "galaxy_gateway.device_router.DeviceRouter.route_task",
            "galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator",
        ]
        for path in pr7_paths:
            entry = LEGACY_PATH_REGISTRY[path]
            assert entry.pr_guardrail_added == "PR-7", (
                f"{path} should have pr_guardrail_added='PR-7'"
            )

    def test_pr7_entries_have_recommendation(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        pr7_paths = [
            "galaxy_gateway.orchestrator.galaxy_orchestrator",
            "galaxy_gateway.device_router.DeviceRouter.route_task",
        ]
        for path in pr7_paths:
            entry = LEGACY_PATH_REGISTRY[path]
            assert len(entry.recommendation) > 20

    def test_is_legacy_path_returns_true_for_pr7(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.orchestrator.galaxy_orchestrator")

    def test_classify_path_status_returns_legacy_for_pr7(self):
        from core.orchestration_authority.legacy_paths import (
            classify_path_status,
            LegacyPathStatus,
        )
        status = classify_path_status("galaxy_gateway.orchestrator.galaxy_orchestrator")
        assert status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_to_dict_serialises_pr7_entry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.orchestrator.galaxy_orchestrator"]
        d = entry.to_dict()
        assert d["pr_guardrail_added"] == "PR-7"
        assert d["status"] == "legacy_compatibility"


# ---------------------------------------------------------------------------
# 14. openclawd_memory_backflow.store_result_envelope — canonical backflow
# ---------------------------------------------------------------------------


class TestStoreResultEnvelope:
    def setup_method(self):
        from core.cross_device_execution_chain import reset_cross_device_chain
        reset_cross_device_chain()

    def test_store_result_envelope_returns_true_on_success(self):
        from core.cross_device_execution_chain import ResultEnvelope
        from core.openclawd_memory_backflow import store_result_envelope

        env = ResultEnvelope(task_id="t_bf1", device_id="d1", success=True)

        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=None):
            result = asyncio.get_running_loop().run_until_complete(
                store_result_envelope(env)
            )

        assert result is True

    def test_store_result_envelope_records_chain_execution(self):
        from core.cross_device_execution_chain import ResultEnvelope, get_cross_device_chain
        from core.openclawd_memory_backflow import store_result_envelope

        env = ResultEnvelope(task_id="t_chain_rec", device_id="d2", success=True)

        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=None):
            asyncio.get_running_loop().run_until_complete(store_result_envelope(env))

        snap = get_cross_device_chain().snapshot()
        assert snap.total_executions == 1
        assert snap.canonical_executions == 1

    def test_store_result_envelope_writes_to_task_memory(self):
        from core.cross_device_execution_chain import ResultEnvelope
        from core.openclawd_memory_backflow import store_result_envelope

        mock_mem = MagicMock()
        env = ResultEnvelope(task_id="t_mem", device_id="d3", success=True)

        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            asyncio.get_running_loop().run_until_complete(store_result_envelope(env))

        assert mock_mem.record_task.called

    def test_store_result_envelope_marks_memory_backflow_stored(self):
        from core.cross_device_execution_chain import ResultEnvelope
        from core.openclawd_memory_backflow import store_result_envelope

        mock_mem = MagicMock()
        env = ResultEnvelope(task_id="t_mark", success=True)

        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            asyncio.get_running_loop().run_until_complete(store_result_envelope(env))

        assert env.memory_backflow_stored is True

    def test_store_result_envelope_passes_chain_metadata(self):
        from core.cross_device_execution_chain import ResultEnvelope, get_cross_device_chain
        from core.openclawd_memory_backflow import store_result_envelope

        env = ResultEnvelope(task_id="t_meta", success=True)
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=None):
            asyncio.get_running_loop().run_until_complete(
                store_result_envelope(env, chain_metadata={"authority_role": "subject_core"})
            )

        snap = get_cross_device_chain().snapshot()
        assert snap.total_executions == 1
        rec = snap.recent_records[0]
        assert rec.extra.get("authority_role") == "subject_core"


# ---------------------------------------------------------------------------
# 15. store_result_envelope graceful degradation
# ---------------------------------------------------------------------------


class TestStoreResultEnvelopeGracefulDegradation:
    def test_returns_false_when_chain_unavailable(self):
        import importlib
        import sys

        # Temporarily hide the chain module by patching _CHAIN_AVAILABLE
        import core.openclawd_memory_backflow as bf_mod
        original = bf_mod._CHAIN_AVAILABLE
        bf_mod._CHAIN_AVAILABLE = False
        try:
            env = MagicMock()
            env.task_id = "t_unavail"
            result = asyncio.get_running_loop().run_until_complete(
                bf_mod.store_result_envelope(env)
            )
            assert result is False
        finally:
            bf_mod._CHAIN_AVAILABLE = original


# ---------------------------------------------------------------------------
# 16. Cross-device policy: legacy authority blocks expansion
# ---------------------------------------------------------------------------


class TestCrossDevicePolicyLegacyAuthority:
    def test_legacy_authority_blocks_cross_device(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True, "requires_confirmation": False}
        result = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            authority_role="legacy_compatibility",
        )
        assert result.posture is RoutingPosture.LOCAL_PREFERRED
        assert result.expansion_allowed_by_execution_policy is False

    def test_deprecated_authority_blocks_cross_device(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        result = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            authority_role="deprecated",
        )
        assert result.posture is RoutingPosture.LOCAL_PREFERRED
        assert result.expansion_allowed_by_execution_policy is False


# ---------------------------------------------------------------------------
# 17. Cross-device policy: canonical posture for cross_device domain
# ---------------------------------------------------------------------------


class TestCrossDevicePolicyCanonical:
    def test_cross_device_domain_allows_expansion(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        result = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=policy,
            authority_role="subject_decision_authority",
        )
        assert result.posture is not RoutingPosture.LOCAL_PREFERRED
        assert result.expansion_allowed_by_execution_policy is True

    def test_local_domain_does_not_expand(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture

        policy = {"cross_device_allowed": True}
        result = resolve_routing(
            runtime_domain="local",
            execution_policy=policy,
        )
        assert result.posture is RoutingPosture.LOCAL_PREFERRED

    def test_policy_from_openclawd_not_gateway(self):
        """
        cross_device_policy is interpreted by the routing/authority layer
        (OpenClawd / CommandRouter), not by the gateway.  The resolver
        accepts the policy dict as a signal — the gateway does not invoke it.
        """
        from core.cross_device_policy import resolve_routing, RoutingPosture

        # Simulate a policy that would be set by OpenClawd / CommandRouter
        openclawd_policy = {
            "cross_device_allowed": True,
            "requires_confirmation": False,
        }
        result = resolve_routing(
            runtime_domain="cross_device",
            execution_policy=openclawd_policy,
            authority_role="subject_decision_authority",
            source_device_id="local",
            target_device_ids=["remote_phone"],
        )
        assert result.expansion_allowed_by_execution_policy is True
        assert result.primary_execution_device_id == "remote_phone"


# ---------------------------------------------------------------------------
# 18. GalaxyOrchestrator class docstring demoted
# ---------------------------------------------------------------------------


class TestGalaxyOrchestratorDemoted:
    def test_class_docstring_mentions_deprecated(self):
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
        doc = GalaxyOrchestrator.__doc__ or ""
        # Docstring should mention the deprecation / canonical chain
        assert "PR-7" in doc or "deprecated" in doc.lower() or "legacy" in doc.lower()

    def test_class_docstring_mentions_canonical_chain(self):
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
        doc = GalaxyOrchestrator.__doc__ or ""
        assert "CommandRouter" in doc or "canonical" in doc.lower()

    def test_init_emits_legacy_guardrail(self, caplog):
        import logging
        from unittest.mock import MagicMock, patch
        # GalaxyOrchestrator.__init__ tries to connect to AI gateway/device manager.
        # We patch those out to test only the guardrail emission.
        with patch(
            "galaxy_gateway.orchestrator.galaxy_orchestrator.AIGateway",
            return_value=MagicMock(),
        ), patch(
            "galaxy_gateway.orchestrator.galaxy_orchestrator.DeviceManager",
            return_value=MagicMock(),
        ):
            with caplog.at_level(logging.WARNING, logger="Galaxy.OrchestrationAuthority"):
                try:
                    from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
                    GalaxyOrchestrator(config={})
                except Exception:
                    pass  # Construction errors are not what we're testing
        legacy_records = [
            r for r in caplog.records
            if "LEGACY PATH GUARDRAIL" in r.message
        ]
        assert len(legacy_records) >= 1


# ---------------------------------------------------------------------------
# 19–20. Warning emission for legacy vs canonical paths (already covered in
#         TestRecordChainExecution tests 4 and 5 above, but add direct tests)
# ---------------------------------------------------------------------------


class TestLegacyPathWarning:
    def setup_method(self):
        from core.cross_device_execution_chain import reset_cross_device_chain
        reset_cross_device_chain()

    def test_galaxy_orchestrator_legacy_path_emits_warning(self, caplog):
        import logging
        from core.cross_device_execution_chain import record_chain_execution

        with caplog.at_level(logging.WARNING, logger="Galaxy.CrossDeviceExecutionChain"):
            record_chain_execution(
                task_id="t_gw_warn",
                legacy_path_used="galaxy_gateway.orchestrator.galaxy_orchestrator",
            )
        legacy_msgs = [
            r for r in caplog.records
            if "LEGACY CHAIN PATH" in r.message
        ]
        assert len(legacy_msgs) >= 1

    def test_device_router_legacy_path_emits_warning(self, caplog):
        import logging
        from core.cross_device_execution_chain import record_chain_execution

        with caplog.at_level(logging.WARNING, logger="Galaxy.CrossDeviceExecutionChain"):
            record_chain_execution(
                task_id="t_dr_warn",
                legacy_path_used="galaxy_gateway.device_router.DeviceRouter.route_task",
            )
        legacy_msgs = [
            r for r in caplog.records
            if "LEGACY CHAIN PATH" in r.message
        ]
        assert len(legacy_msgs) >= 1
