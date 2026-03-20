"""
tests/chaos/test_latency_chaos.py
===================================
Block-5 Chaos: Latency Spike Scenarios

Verifies that the system correctly handles and classifies latency-induced
timeout errors, and that the error taxonomy correctly marks them as retryable
with back-off.
"""

from __future__ import annotations

import asyncio
import time

import pytest


def _reset() -> None:
    from core.unified.idempotency import reset_idempotency_store
    from core.unified.release_gate import reset_release_gate
    from core.orchestration.global_arbiter import reset_global_arbiter

    reset_idempotency_store()
    reset_release_gate()
    reset_global_arbiter()


# ---------------------------------------------------------------------------
# 1. Timeout errors are correctly classified
# ---------------------------------------------------------------------------


class TestTimeoutErrorClassification:
    def setup_method(self):
        _reset()

    def test_stdlib_timeout_error_maps_to_exec_timeout(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        exc = TimeoutError("operation timed out")
        payload = ErrorMapper.from_exception(exc, trace_id="lat-001")
        assert payload.code == GalaxyErrorCode.EXEC_TASK_TIMEOUT.value

    def test_asyncio_timeout_is_backoff_retryable(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        desc = get_descriptor(GalaxyErrorCode.EXEC_TASK_TIMEOUT)
        assert desc is not None
        assert desc.retryable == Retryable.BACKOFF

    def test_device_timeout_maps_from_legacy_executor(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        payload = ErrorMapper.from_legacy_executor_error(
            "executor timeout after 30s", trace_id="lat-002"
        )
        assert payload.code == GalaxyErrorCode.EXEC_TASK_TIMEOUT.value
        assert payload.retryable is True

    def test_timeout_payload_has_error_id(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        p1 = ErrorPayload.from_code(GalaxyErrorCode.EXEC_TASK_TIMEOUT)
        p2 = ErrorPayload.from_code(GalaxyErrorCode.EXEC_TASK_TIMEOUT)
        # Every payload gets a unique error_id
        assert p1.error_id != p2.error_id


# ---------------------------------------------------------------------------
# 2. Latency spike causes arbiter slot to eventually be reclaimed
# ---------------------------------------------------------------------------


class TestArbiterUnderLatency:
    def setup_method(self):
        _reset()

    def test_high_priority_admitted_while_slow_task_runs(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=1, per_origin_quota=4)

        # Low-priority "slow" task
        d_slow = arbiter.admit("slow-task", priority=1, origin="sys:bg", preemptable=True)
        assert d_slow.admitted is True

        # High-priority urgent task preempts the slow one
        d_urgent = arbiter.admit("urgent-task", priority=9, origin="user:alice")
        assert d_urgent.admitted is True
        assert d_urgent.preempted_task_id == "slow-task"

    def test_preemption_recorded_in_decisions(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=1, per_origin_quota=4)

        arbiter.admit("bg-task", priority=1, origin="sys", preemptable=True)
        arbiter.admit("hp-task", priority=10, origin="user")

        decisions = arbiter.recent_decisions()
        preemption = next(
            (d for d in decisions if d.get("preempted_task_id") == "bg-task"), None
        )
        assert preemption is not None
        assert preemption["outcome"] == "preempted_other"

    def test_non_preemptable_task_survives_high_priority_arrival(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=1, per_origin_quota=4)

        # Non-preemptable critical background task
        d_crit = arbiter.admit("crit-task", priority=5, origin="sys", preemptable=False)
        assert d_crit.admitted is True

        # Even higher priority task cannot preempt a non-preemptable task
        d_new = arbiter.admit("new-task", priority=10, origin="user")
        assert d_new.admitted is False


# ---------------------------------------------------------------------------
# 3. Release gate blocks feature under simulated canary rollout
# ---------------------------------------------------------------------------


class TestReleaseGateRolloutSimulation:
    def setup_method(self):
        _reset()

    def test_flag_off_blocks_feature(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate

        reset_release_gate()
        gate = get_release_gate()
        gate.override("global_arbiter", False)

        assert gate.is_enabled("global_arbiter", context_key="task-001") is False

    def test_flag_on_allows_feature(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate

        reset_release_gate()
        gate = get_release_gate()
        gate.override("global_arbiter", True)

        assert gate.is_enabled("global_arbiter", context_key="task-002") is True

    def test_clear_override_restores_yaml_default(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate

        reset_release_gate()
        gate = get_release_gate()
        gate.override("idempotency_guard", False)
        assert gate.is_enabled("idempotency_guard") is False

        gate.clear_override("idempotency_guard")
        # Without override, default is True (flag not in YAML or enabled=true)
        assert gate.is_enabled("idempotency_guard") is True
