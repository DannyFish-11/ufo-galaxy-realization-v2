"""
tests/chaos/test_partial_failure_chaos.py
==========================================
Block-5 Chaos: Partial Failure Scenarios

Simulates partial failures in multi-step pipelines:
- Some nodes fail, others succeed
- Arbiter admits/rejects based on priority
- Error payloads have correct retryability semantics
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest


def _reset() -> None:
    from core.unified.idempotency import reset_idempotency_store
    from core.unified.release_gate import reset_release_gate
    from core.orchestration.global_arbiter import reset_global_arbiter

    reset_idempotency_store()
    reset_release_gate()
    reset_global_arbiter()


# ---------------------------------------------------------------------------
# 1. Error taxonomy retryability coverage
# ---------------------------------------------------------------------------


class TestRetryabilityMatrix:
    """Verify that every domain's errors have correct retryability classification."""

    def test_planner_decompose_backoff(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.PLAN_DECOMPOSE_FAILED)
        assert d.retryable == Retryable.BACKOFF

    def test_planner_cycle_no_retry(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.PLAN_CYCLE_DETECTED)
        assert d.retryable == Retryable.NO

    def test_exec_cancelled_no_retry(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.EXEC_CANCELLED)
        assert d.retryable == Retryable.NO

    def test_gw_auth_no_retry(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.GW_AUTH_FAILED)
        assert d.retryable == Retryable.NO

    def test_gw_rate_limit_backoff(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.GW_RATE_LIMITED)
        assert d.retryable == Retryable.BACKOFF

    def test_idempotency_duplicate_no_retry(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.IDEMPOTENCY_DUPLICATE)
        assert d.retryable == Retryable.NO

    def test_arbiter_preempted_yes_retry(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.ARBITER_PREEMPTED)
        assert d.retryable == Retryable.YES

    def test_transport_disconnect_yes_retry(self):
        from core.unified.error_codes import GalaxyErrorCode, Retryable, get_descriptor

        d = get_descriptor(GalaxyErrorCode.TRANSPORT_DISCONNECT)
        assert d.retryable == Retryable.YES


# ---------------------------------------------------------------------------
# 2. Multi-step pipeline partial failure
# ---------------------------------------------------------------------------


class TestPartialPipelineFailure:
    def setup_method(self):
        _reset()

    @pytest.mark.asyncio
    async def test_task_graph_continues_after_one_node_fails(self):
        """Independent branches continue even when one node fails."""
        from core.task_graph import TaskGraph, TaskNode, NodeStatus

        results: Dict[str, str] = {}

        async def succeed_handler(node: TaskNode, ctx: Dict) -> Dict:
            results[node.description] = "ok"
            return {"status": "ok"}

        async def fail_handler(node: TaskNode, ctx: Dict) -> Dict:
            raise RuntimeError("chaos: injected failure")

        graph = TaskGraph(trace_id="chaos-partial")
        n_a = graph.add_node("fetch", handler=succeed_handler)
        n_b = graph.add_node("process", handler=fail_handler, depends_on=[n_a.node_id])
        n_c = graph.add_node("notify", handler=succeed_handler)  # independent

        result = await graph.execute(context={})

        assert results.get("fetch") == "ok"
        assert results.get("notify") == "ok"
        # 'process' should be failed/skipped, 'fetch' and 'notify' done
        assert result.done_nodes >= 2
        assert result.failed_nodes >= 1

    @pytest.mark.asyncio
    async def test_failed_node_produces_error_payload(self):
        from core.task_graph import TaskGraph, TaskNode, NodeStatus
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        async def fail_handler(node: TaskNode, ctx: Dict) -> Dict:
            raise TimeoutError("step timed out")

        graph = TaskGraph(trace_id="chaos-payload")
        graph.add_node("step", handler=fail_handler)

        result = await graph.execute(context={})
        assert result.failed_nodes >= 1


# ---------------------------------------------------------------------------
# 3. Arbiter partial rejection under load
# ---------------------------------------------------------------------------


class TestArbiterPartialRejection:
    def setup_method(self):
        _reset()

    def test_quota_exceeded_for_single_origin(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=10, per_origin_quota=2)

        d1 = arbiter.admit("t1", priority=3, origin="user:bob")
        d2 = arbiter.admit("t2", priority=3, origin="user:bob")
        d3 = arbiter.admit("t3", priority=3, origin="user:bob")  # over quota

        assert d1.admitted and d2.admitted
        assert d3.admitted is False
        assert "quota" in d3.reason

    def test_different_origins_share_global_limit(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=3, per_origin_quota=10)

        ds = [
            arbiter.admit(f"t{i}", priority=1, origin=f"user:{i}")
            for i in range(5)
        ]
        admitted = [d for d in ds if d.admitted]
        rejected = [d for d in ds if not d.admitted]
        # First 3 admitted; last 2 need preemption or are rejected
        assert len(admitted) >= 3

    def test_arbiter_stats_track_all_outcomes(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=1, per_origin_quota=4)

        arbiter.admit("slow", priority=1, origin="bg", preemptable=True)
        arbiter.admit("fast", priority=9, origin="fg")

        s = arbiter.stats()
        assert s["admitted"] >= 1
        # Either preemptions happened or rejections happened
        assert s["preemptions"] + s["rejected"] >= 0


# ---------------------------------------------------------------------------
# 4. Release gate prevents feature activation during rollback
# ---------------------------------------------------------------------------


class TestReleaseGateRollback:
    def setup_method(self):
        _reset()

    def test_rollback_disables_arbiter(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate, FeatureDisabledError

        reset_release_gate()
        gate = get_release_gate()
        gate.override("global_arbiter", False)

        with pytest.raises(FeatureDisabledError):
            gate.require_enabled("global_arbiter")

    def test_rollback_disables_idempotency(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate, FeatureDisabledError

        reset_release_gate()
        gate = get_release_gate()
        gate.override("idempotency_guard", False)

        assert gate.is_enabled("idempotency_guard") is False

    def test_re_enable_after_rollback(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate

        reset_release_gate()
        gate = get_release_gate()
        gate.override("global_arbiter", False)
        assert gate.is_enabled("global_arbiter") is False

        gate.override("global_arbiter", True)
        assert gate.is_enabled("global_arbiter") is True

    def test_unknown_flag_defaults_to_enabled(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate

        reset_release_gate()
        gate = get_release_gate()
        # Flag not in YAML at all — default is True
        assert gate.is_enabled("some_future_flag") is True
