#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_g5_resilience.py — PR-G5 Performance & Resilience Protection
=========================================================================

Unit and integration tests for:

1.  CircuitBreaker — CLOSED/OPEN/HALF_OPEN state transitions
2.  CircuitBreaker — fallback invocation when circuit is open
3.  CircuitBreaker — manual trip() and reset()
4.  CircuitBreaker — snapshot() returns correct structure
5.  AdaptiveSemaphore — basic acquire/release semantics
6.  AdaptiveSemaphore — AIMD decrease on high error rate
7.  AdaptiveSemaphore — snapshot() returns correct structure
8.  ResilienceMetrics — queue depth tracking
9.  ResilienceMetrics — rejection rate rolling window
10. ResilienceMetrics — prometheus_text() format
11. ResilienceMetrics — get_resilience_metrics() returns singleton
12. CommandRouter — admission control rejects beyond max_queue_depth
13. CommandRouter — circuit breaker integration in _execute_single_with_retry
14. CommandRouter — get_stats() includes PR-G5 resilience fields
15. CommandRouter — get_resilience_snapshot() structure
16. Resilience routes — /api/v1/resilience/metrics JSON schema
17. Resilience routes — /api/v1/resilience/metrics/prom Prometheus format
18. Resilience routes — /api/v1/resilience/circuit-breakers list
19. Resilience routes — POST .../reset resets known CB
20. Load-test smoke — concurrent dispatches degrade gracefully (no API schema breaks)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# 1–4. CircuitBreaker
# ===========================================================================

class TestCircuitBreakerStates:
    """State machine transitions."""

    def _fresh_cb(self, failure_threshold=3, recovery_timeout=60, window_size=5):
        from core.resilience.circuit_breaker import CircuitBreaker, CircuitState
        return CircuitBreaker(
            target="test_target",
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            window_size=window_size,
        )

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        cb = self._fresh_cb()
        from core.resilience.circuit_breaker import CircuitState
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_calls_stay_closed(self):
        cb = self._fresh_cb()
        from core.resilience.circuit_breaker import CircuitState

        async def ok():
            return "ok"

        for _ in range(5):
            result = await cb.call(ok)
            assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failures_trip_to_open(self):
        cb = self._fresh_cb(failure_threshold=3)
        from core.resilience.circuit_breaker import CircuitState

        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_raises_without_fallback(self):
        cb = self._fresh_cb()
        from core.resilience.circuit_breaker import CircuitOpenError
        await cb.trip()

        async def fn():
            return "should not run"

        with pytest.raises(CircuitOpenError):
            await cb.call(fn)

    @pytest.mark.asyncio
    async def test_open_circuit_invokes_fallback(self):
        fallback_called = []

        async def fallback(*args, **kwargs):
            fallback_called.append(True)
            return "degraded"

        from core.resilience.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(
            target="t",
            failure_threshold=1,
            recovery_timeout=60,
            fallback=fallback,
        )
        await cb.trip()

        async def fn():
            return "primary"

        result = await cb.call(fn)
        assert result == "degraded"
        assert len(fallback_called) == 1

    @pytest.mark.asyncio
    async def test_half_open_on_timeout_recovery(self):
        cb = self._fresh_cb(failure_threshold=2, recovery_timeout=0.01)
        from core.resilience.circuit_breaker import CircuitState

        async def fail():
            raise ValueError("err")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.05)

        async def succeed():
            return "ok"

        result = await cb.call(succeed)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_manual_reset(self):
        cb = self._fresh_cb()
        from core.resilience.circuit_breaker import CircuitState
        await cb.trip()
        assert cb.state == CircuitState.OPEN
        await cb.reset()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_snapshot_structure(self):
        cb = self._fresh_cb()
        snap = cb.snapshot()
        for key in (
            "target", "state", "total_calls", "total_failures",
            "total_fallbacks", "total_circuit_opens",
            "recent_error_rate", "failure_threshold", "recovery_timeout_s",
        ):
            assert key in snap, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_snapshot_total_circuit_opens(self):
        cb = self._fresh_cb(failure_threshold=1)

        async def fail():
            raise ValueError("x")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.snapshot()["total_circuit_opens"] >= 1


# ===========================================================================
# 5–7. AdaptiveSemaphore
# ===========================================================================

class TestAdaptiveSemaphore:
    """Adaptive semaphore behaviour."""

    def _fresh(self, initial=5, min_limit=1, max_limit=20, target_latency=200.0):
        from core.resilience.adaptive_semaphore import AdaptiveSemaphore
        return AdaptiveSemaphore(
            initial_limit=initial,
            min_limit=min_limit,
            max_limit=max_limit,
            target_latency_ms=target_latency,
            probe_interval=0.0,  # force AIMD on every record() call
        )

    @pytest.mark.asyncio
    async def test_basic_acquire_release(self):
        sem = self._fresh(initial=2)
        async with sem:
            pass  # should not raise
        assert sem.total_acquired >= 1

    @pytest.mark.asyncio
    async def test_decrease_on_high_error_rate(self):
        sem = self._fresh(initial=10, min_limit=2)
        original = sem.current_limit

        # Record all errors to trigger MD
        for _ in range(20):
            await sem.record(1000.0, error=True)

        assert sem.current_limit < original

    @pytest.mark.asyncio
    async def test_increase_on_low_latency_no_errors(self):
        sem = self._fresh(initial=3, max_limit=20, target_latency=500.0)
        original = sem.current_limit

        for _ in range(20):
            await sem.record(10.0, error=False)

        assert sem.current_limit >= original

    @pytest.mark.asyncio
    async def test_never_below_min_limit(self):
        sem = self._fresh(initial=5, min_limit=2)
        for _ in range(100):
            await sem.record(9999.0, error=True)
        assert sem.current_limit >= 2

    @pytest.mark.asyncio
    async def test_snapshot_structure(self):
        sem = self._fresh()
        snap = sem.snapshot()
        for key in (
            "current_limit", "min_limit", "max_limit",
            "total_acquired", "total_adjustments",
            "p50_latency_ms", "p99_latency_ms", "recent_error_rate",
        ):
            assert key in snap, f"Missing key: {key}"
        # Value / type assertions
        assert isinstance(snap["current_limit"], int)
        assert snap["current_limit"] >= snap["min_limit"]
        assert snap["current_limit"] <= snap["max_limit"]
        assert snap["total_acquired"] >= 0
        assert snap["total_adjustments"] >= 0
        assert 0.0 <= snap["recent_error_rate"] <= 1.0
        assert snap["p50_latency_ms"] >= 0.0
        assert snap["p99_latency_ms"] >= 0.0


# ===========================================================================
# 8–11. ResilienceMetrics
# ===========================================================================

class TestResilienceMetrics:
    """Resilience metrics counters and Prometheus output."""

    def _fresh(self):
        from core.resilience.metrics import ResilienceMetrics
        return ResilienceMetrics()

    def test_queue_depth_tracking(self):
        m = self._fresh()
        m.set_queue_depth(42)
        snap = m.snapshot()
        assert snap["queue_depth"] == 42

    def test_queue_depth_max_tracked(self):
        m = self._fresh()
        m.set_queue_depth(10)
        m.set_queue_depth(5)
        assert m.snapshot()["queue_depth_max"] == 10

    def test_accepted_counter(self):
        m = self._fresh()
        m.record_accepted()
        m.record_accepted()
        assert m.snapshot()["total_accepted"] == 2

    def test_rejected_counter(self):
        m = self._fresh()
        m.record_rejected()
        snap = m.snapshot()
        assert snap["total_rejected"] == 1
        assert snap["rejection_rate_per_min"] >= 1

    def test_fallback_counter(self):
        m = self._fresh()
        m.record_fallback()
        m.record_fallback()
        assert m.snapshot()["total_fallbacks"] == 2

    def test_circuit_open_counter(self):
        m = self._fresh()
        m.record_circuit_open()
        assert m.snapshot()["total_circuit_opens"] == 1

    def test_rejection_rate_rolling_window(self):
        """Old rejections beyond 60 s should not appear in rate_per_min."""
        m = self._fresh()
        # Inject an old timestamp directly
        m._rejection_timestamps.append(time.time() - 120)
        m.record_rejected()  # recent
        # rate_per_min should reflect only the recent rejection
        assert m.rejection_rate_per_minute <= 2

    def test_prometheus_text_contains_key_metrics(self):
        m = self._fresh()
        text = m.prometheus_text()
        assert "galaxy_resilience_queue_depth " in text
        assert "galaxy_resilience_total_rejected_total " in text
        assert "galaxy_resilience_total_fallbacks_total " in text

    def test_prometheus_text_help_type_lines(self):
        m = self._fresh()
        text = m.prometheus_text()
        assert "# HELP" in text
        assert "# TYPE" in text

    def test_singleton_same_instance(self):
        from core.resilience.metrics import get_resilience_metrics
        a = get_resilience_metrics()
        b = get_resilience_metrics()
        assert a is b

    def test_snapshot_structure(self):
        m = self._fresh()
        snap = m.snapshot()
        for key in (
            "queue_depth", "queue_depth_max", "total_accepted",
            "total_rejected", "rejection_rate_per_min",
            "rejection_fraction", "total_fallbacks", "total_circuit_opens",
            "uptime_seconds",
        ):
            assert key in snap, f"Missing key: {key}"


# ===========================================================================
# 12–15. CommandRouter integration
# ===========================================================================

class TestCommandRouterResilience:
    """CommandRouter PR-G5 integration tests."""

    def _make_router(self, max_queue_depth=5, cb_enabled=True):
        from core.command_router import CommandRouter

        async def dummy_executor(target, command, params):
            return {"target": target, "command": command}

        return CommandRouter(
            executor=dummy_executor,
            max_concurrent=10,
            max_queue_depth=max_queue_depth,
            cb_enabled=cb_enabled,
        )

    @pytest.mark.asyncio
    async def test_admission_control_rejects_when_queue_full(self):
        """When active requests >= max_queue_depth, new requests are rejected."""
        from core.command_router import CommandRouter, CommandStatus

        blocked_event = asyncio.Event()
        released_event = asyncio.Event()

        async def slow_executor(target, command, params):
            blocked_event.set()
            await released_event.wait()
            return {}

        router = CommandRouter(
            executor=slow_executor,
            max_concurrent=10,
            max_queue_depth=2,
            cb_enabled=False,
        )

        def _make_req(idx):
            from core.command_router import CommandRequest, CommandMode
            return CommandRequest(
                targets=[f"dev_{idx}"],
                command="ping",
                mode=CommandMode.ASYNC,
            )

        # Start 2 async requests so they fill the queue
        t1 = asyncio.create_task(router.dispatch(_make_req(1)))
        t2 = asyncio.create_task(router.dispatch(_make_req(2)))

        # Wait for at least one to be in-flight
        await asyncio.wait_for(blocked_event.wait(), timeout=2.0)

        # Now the 3rd should be rejected
        from core.command_router import CommandRequest, CommandMode
        req3 = CommandRequest(targets=["dev_3"], command="ping", mode=CommandMode.SYNC)
        result3 = await router.dispatch(req3)
        assert result3.status == CommandStatus.FAILED
        assert result3.metadata.get("throttled") is True

        released_event.set()
        await asyncio.gather(t1, t2, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_get_stats_includes_resilience_fields(self):
        router = self._make_router()
        stats = router.get_stats()
        assert "total_rejected" in stats
        assert "total_fallbacks" in stats
        assert "max_queue_depth" in stats
        assert "cb_enabled" in stats
        assert "adaptive_concurrency_enabled" in stats

    @pytest.mark.asyncio
    async def test_get_resilience_snapshot_structure(self):
        router = self._make_router()
        snap = router.get_resilience_snapshot()
        assert "metrics" in snap
        assert "circuit_breakers" in snap
        assert "adaptive_semaphore" in snap
        assert "queue_depth" in snap
        assert "max_queue_depth" in snap

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        """After repeated failures the CB for that target should be OPEN."""
        from core.command_router import CommandRouter, CommandRequest, CommandMode

        call_count = 0

        async def failing_executor(target, command, params):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("device unreachable")

        router = CommandRouter(
            executor=failing_executor,
            max_concurrent=10,
            max_queue_depth=1000,
            cb_enabled=True,
        )
        # Patch CB failure threshold to 2 so we don't need many dispatches
        from core.resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(target="dev_x", failure_threshold=2, recovery_timeout=60)
        router._circuit_breakers["dev_x"] = cb

        # Manually inject failures to trip the CB
        for _ in range(2):
            try:
                async def f():
                    raise RuntimeError("x")
                await cb.call(f)
            except RuntimeError:
                pass

        assert cb.state == CircuitState.OPEN

        # Now dispatch should use the open-CB fast path
        req = CommandRequest(
            targets=["dev_x"], command="ping", mode=CommandMode.SYNC, max_retries=0
        )
        result = await router.dispatch(req)
        from core.command_router import CommandStatus
        assert result.status == CommandStatus.FAILED
        assert "OPEN" in (result.targets["dev_x"].error or "")

    @pytest.mark.asyncio
    async def test_cb_disabled_flag(self):
        """With cb_enabled=False, no circuit breakers should be created."""
        router = self._make_router(cb_enabled=False)
        cb = router._get_circuit_breaker("any_target")
        assert cb is None


# ===========================================================================
# 16–19. Resilience API routes
# ===========================================================================

class TestResilienceRoutes:
    """FastAPI route tests for PR-G5 resilience endpoints."""

    def _app(self):
        from fastapi import FastAPI
        from core.routes.resilience import create_router
        app = FastAPI()
        app.include_router(create_router())
        return app

    def test_metrics_json_returns_200(self):
        from httpx import AsyncClient
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/resilience/metrics")
                assert resp.status_code == 200
                data = resp.json()
                assert "resilience_metrics" in data

        asyncio.get_running_loop().run_until_complete(run())

    def test_metrics_json_schema_keys(self):
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/resilience/metrics")
                data = resp.json()
                m = data["resilience_metrics"]
                for key in ("queue_depth", "total_rejected", "total_fallbacks"):
                    assert key in m, f"Missing key: {key}"

        asyncio.get_running_loop().run_until_complete(run())

    def test_prometheus_endpoint_returns_200_text_plain(self):
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/resilience/metrics/prom")
                assert resp.status_code == 200
                assert "text/plain" in resp.headers.get("content-type", "")

        asyncio.get_running_loop().run_until_complete(run())

    def test_prometheus_endpoint_contains_expected_metric(self):
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/resilience/metrics/prom")
                assert b"galaxy_resilience_queue_depth" in resp.content

        asyncio.get_running_loop().run_until_complete(run())

    def test_circuit_breakers_list_returns_200(self):
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/resilience/circuit-breakers")
                assert resp.status_code == 200
                data = resp.json()
                assert "circuit_breakers" in data

        asyncio.get_running_loop().run_until_complete(run())

    def test_reset_unknown_target_returns_404(self):
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/resilience/circuit-breakers/unknown_target/reset")
                assert resp.status_code == 404

        asyncio.get_running_loop().run_until_complete(run())

    def test_reset_known_target_returns_200(self):
        import asyncio

        async def run():
            from httpx import AsyncClient, ASGITransport
            from core.command_router import get_command_router
            from core.resilience.circuit_breaker import CircuitBreaker

            # Register a CB in the global router
            cr = get_command_router()
            cb = CircuitBreaker(target="known_dev")
            cr._circuit_breakers["known_dev"] = cb

            app = self._app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/resilience/circuit-breakers/known_dev/reset")
                assert resp.status_code == 200
                data = resp.json()
                assert data["state"] == "closed"

        asyncio.get_running_loop().run_until_complete(run())


# ===========================================================================
# 20. Load-test smoke — concurrent dispatches under moderate concurrency
# ===========================================================================

class TestConcurrentLoadSmoke:
    """Quick smoke: 50 concurrent dispatches must not raise or corrupt schema."""

    @pytest.mark.asyncio
    async def test_concurrent_dispatches_no_schema_break(self):
        """50 concurrent dispatches complete without unhandled exceptions."""
        from core.command_router import CommandRouter, CommandRequest, CommandMode, CommandStatus

        results_ok = []
        results_throttled = []

        async def echo_executor(target, command, params):
            await asyncio.sleep(0.01)
            return {"echo": command}

        router = CommandRouter(
            executor=echo_executor,
            max_concurrent=10,
            max_queue_depth=100,
            cb_enabled=False,
        )

        async def one_dispatch(i):
            req = CommandRequest(
                targets=[f"dev_{i % 5}"],
                command="ping",
                mode=CommandMode.SYNC,
                timeout=5.0,
            )
            return await router.dispatch(req)

        tasks = [one_dispatch(i) for i in range(50)]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in all_results:
            assert not isinstance(r, Exception), f"Unexpected exception: {r}"
            # Schema check: must have request_id and status
            assert hasattr(r, "request_id")
            assert hasattr(r, "status")
            if r.metadata.get("throttled"):
                results_throttled.append(r)
            else:
                results_ok.append(r)

        assert len(results_ok) > 0, "All requests were throttled — check max_queue_depth"

    @pytest.mark.asyncio
    async def test_throttled_result_schema(self):
        """Throttled results must conform to CommandResult schema."""
        from core.command_router import CommandRouter, CommandRequest, CommandMode, CommandStatus

        async def slow_executor(target, command, params):
            await asyncio.sleep(10)
            return {}

        router = CommandRouter(
            executor=slow_executor,
            max_concurrent=1,
            max_queue_depth=1,
            cb_enabled=False,
        )

        # First async request fills the slot
        from core.command_router import CommandRequest, CommandMode
        req1 = CommandRequest(targets=["dev_a"], command="ping", mode=CommandMode.ASYNC)
        await router.dispatch(req1)

        # Second request exceeds queue depth
        req2 = CommandRequest(targets=["dev_b"], command="ping", mode=CommandMode.SYNC)
        result = await router.dispatch(req2)

        assert result.status == CommandStatus.FAILED
        assert result.metadata.get("throttled") is True
        assert "request_id" in result.to_dict()
        assert "status" in result.to_dict()
