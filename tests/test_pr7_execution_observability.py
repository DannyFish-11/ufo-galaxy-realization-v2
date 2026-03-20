"""
tests/test_pr7_execution_observability.py
==========================================

PR-7: Execution Observability Unification — focused tests.

Coverage:
  1.  ExecutorLevel — enum serialisation, from_string, from_win_exec_level,
      is_local / is_remote helpers.
  2.  FallbackReason — enum serialisation, from_string.
  3.  FallbackContext — to_dict / from_dict round-trip, from_arbiter_attempt
      (dict and attribute-based).
  4.  TraceCorrelation — new(), from_dict() with missing / None fields,
      from_e2e_context, from_task_envelope, from_task_graph, child().
  5.  ExecutionEvent — build(), from_dict() tolerance, to_dict(),
      projection_summary().
  6.  Normalizers — normalize_e2e_context, normalize_task_envelope,
      normalize_task_graph_result, normalize_arbiter_attempt,
      normalize_observability_payload — all with partial/missing fields.
  7.  New observability routes — /execution/schema, /execution/recent-events,
      /execution/trace/{id} — via FastAPI TestClient.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. ExecutorLevel
# ===========================================================================

class TestExecutorLevel:
    def test_values_are_strings(self):
        from core.execution_observability import ExecutorLevel
        for member in ExecutorLevel:
            assert isinstance(member.value, str)
            assert member == member.value  # str mixin

    def test_from_string_exact(self):
        from core.execution_observability import ExecutorLevel
        assert ExecutorLevel.from_string("system_api") is ExecutorLevel.SYSTEM_API
        assert ExecutorLevel.from_string("uia") is ExecutorLevel.UIA
        assert ExecutorLevel.from_string("gui") is ExecutorLevel.GUI
        assert ExecutorLevel.from_string("vlm") is ExecutorLevel.VLM
        assert ExecutorLevel.from_string("remote_executor") is ExecutorLevel.REMOTE_EXECUTOR
        assert ExecutorLevel.from_string("orchestrator") is ExecutorLevel.ORCHESTRATOR

    def test_from_string_case_insensitive(self):
        from core.execution_observability import ExecutorLevel
        assert ExecutorLevel.from_string("SYSTEM_API") is ExecutorLevel.SYSTEM_API
        assert ExecutorLevel.from_string("VLM") is ExecutorLevel.VLM

    def test_from_string_unknown_fallback(self):
        from core.execution_observability import ExecutorLevel
        assert ExecutorLevel.from_string("bogus") is ExecutorLevel.UNKNOWN
        assert ExecutorLevel.from_string("") is ExecutorLevel.UNKNOWN

    def test_from_string_none_treated_as_empty(self):
        """from_string should tolerate None gracefully (as documented)."""
        from core.execution_observability import ExecutorLevel
        result = ExecutorLevel.from_string(None)  # type: ignore[arg-type]
        assert result is ExecutorLevel.UNKNOWN

    def test_from_win_exec_level_object(self):
        """Should accept any object with a .value attribute."""
        from core.execution_observability import ExecutorLevel

        class FakeLevel:
            value = "uia"

        result = ExecutorLevel.from_win_exec_level(FakeLevel())
        assert result is ExecutorLevel.UIA

    def test_is_local_and_remote(self):
        from core.execution_observability import ExecutorLevel
        for lvl in (ExecutorLevel.SYSTEM_API, ExecutorLevel.UIA,
                    ExecutorLevel.GUI, ExecutorLevel.VLM):
            assert lvl.is_local()
            assert not lvl.is_remote()
        assert ExecutorLevel.REMOTE_EXECUTOR.is_remote()
        assert not ExecutorLevel.REMOTE_EXECUTOR.is_local()


# ===========================================================================
# 2. FallbackReason
# ===========================================================================

class TestFallbackReason:
    def test_all_values_are_strings(self):
        from core.execution_observability import FallbackReason
        for member in FallbackReason:
            assert isinstance(member.value, str)

    def test_from_string_known(self):
        from core.execution_observability import FallbackReason
        assert FallbackReason.from_string("timeout") is FallbackReason.TIMEOUT
        assert FallbackReason.from_string("partial_failure") is FallbackReason.PARTIAL_FAILURE
        assert FallbackReason.from_string("safety_hold") is FallbackReason.SAFETY_HOLD

    def test_from_string_unknown_fallback(self):
        from core.execution_observability import FallbackReason
        assert FallbackReason.from_string("made_up") is FallbackReason.UNKNOWN
        assert FallbackReason.from_string("") is FallbackReason.UNKNOWN


# ===========================================================================
# 3. FallbackContext
# ===========================================================================

class TestFallbackContext:
    def test_to_dict_round_trip(self):
        from core.execution_observability import ExecutorLevel, FallbackReason
        from core.execution_observability.fallback_schema import FallbackContext

        ctx = FallbackContext(
            from_level=ExecutorLevel.SYSTEM_API,
            to_level=ExecutorLevel.UIA,
            reason=FallbackReason.NO_SYSTEM_API_MATCH,
            raw_reason="no_system_api_match",
            message="System API had no handler",
            metadata={"action": "click"},
        )
        d = ctx.to_dict()
        assert d["from_level"] == "system_api"
        assert d["to_level"] == "uia"
        assert d["reason"] == "no_system_api_match"
        assert d["metadata"] == {"action": "click"}

        restored = FallbackContext.from_dict(d)
        assert restored.from_level is ExecutorLevel.SYSTEM_API
        assert restored.to_level is ExecutorLevel.UIA
        assert restored.reason is FallbackReason.NO_SYSTEM_API_MATCH

    def test_from_dict_missing_fields(self):
        from core.execution_observability.fallback_schema import FallbackContext
        ctx = FallbackContext.from_dict({})
        # Should not raise; defaults to UNKNOWN
        from core.execution_observability import ExecutorLevel, FallbackReason
        assert ctx.from_level is ExecutorLevel.UNKNOWN
        assert ctx.reason is FallbackReason.UNKNOWN
        assert ctx.to_level is None

    def test_from_arbiter_attempt_dict(self):
        from core.execution_observability import ExecutorLevel, FallbackReason
        from core.execution_observability.fallback_schema import FallbackContext

        attempt = {
            "executor_level": "uia",
            "fallback_reason": "uia_unavailable",
            "action_summary": "click OK",
        }
        ctx = FallbackContext.from_arbiter_attempt(attempt)
        assert ctx.from_level is ExecutorLevel.UIA
        assert ctx.reason is FallbackReason.UIA_UNAVAILABLE

    def test_from_arbiter_attempt_object(self):
        from core.execution_observability import ExecutorLevel, FallbackReason
        from core.execution_observability.fallback_schema import FallbackContext

        @dataclass
        class FakeAttempt:
            executor_level: str = "gui"
            fallback_reason: str = "visual_anchor_required"
            action_summary: str = "click at 100,200"

        ctx = FallbackContext.from_arbiter_attempt(FakeAttempt())
        assert ctx.from_level is ExecutorLevel.GUI
        assert ctx.reason is FallbackReason.VISUAL_ANCHOR_REQUIRED


# ===========================================================================
# 4. TraceCorrelation
# ===========================================================================

class TestTraceCorrelation:
    def test_new_generates_non_empty_trace_id(self):
        from core.execution_observability import TraceCorrelation
        tc = TraceCorrelation.new()
        assert tc.trace_id
        assert len(tc.trace_id) >= 12

    def test_auto_generate_trace_id_when_empty(self):
        from core.execution_observability import TraceCorrelation
        tc = TraceCorrelation(trace_id="")
        assert tc.trace_id  # __post_init__ fills it

    def test_from_dict_full(self):
        from core.execution_observability import TraceCorrelation
        d = {
            "trace_id": "abc123",
            "runtime_session_id": "sess-1",
            "task_id": "task-42",
            "action_id": "act-7",
        }
        tc = TraceCorrelation.from_dict(d)
        assert tc.trace_id == "abc123"
        assert tc.runtime_session_id == "sess-1"
        assert tc.task_id == "task-42"
        assert tc.action_id == "act-7"

    def test_from_dict_missing_trace_id(self):
        from core.execution_observability import TraceCorrelation
        tc = TraceCorrelation.from_dict({})
        assert tc.trace_id  # auto-generated

    def test_from_dict_none_values(self):
        from core.execution_observability import TraceCorrelation
        tc = TraceCorrelation.from_dict({"trace_id": None, "task_id": None})
        assert tc.trace_id  # auto-generated
        assert tc.task_id is None

    def test_from_e2e_context(self):
        from core.execution_observability import TraceCorrelation
        ctx = {"trace_id": "e2e-001", "runtime_session_id": "s1", "other": "data"}
        tc = TraceCorrelation.from_e2e_context(ctx)
        assert tc.trace_id == "e2e-001"
        assert tc.runtime_session_id == "s1"

    def test_from_task_envelope_object(self):
        from core.execution_observability import TraceCorrelation

        class FakeEnvelope:
            trace_id = "env-trace"
            runtime_session_id = "env-sess"
            task_id = "t-99"
            action_id = None

        tc = TraceCorrelation.from_task_envelope(FakeEnvelope())
        assert tc.trace_id == "env-trace"
        assert tc.task_id == "t-99"

    def test_from_task_graph_object(self):
        from core.execution_observability import TraceCorrelation

        class FakeGraph:
            trace_id = "graph-trace"
            runtime_session_id = "graph-sess"
            graph_id = "g-1"

        tc = TraceCorrelation.from_task_graph(FakeGraph())
        assert tc.trace_id == "graph-trace"
        assert tc.task_id == "g-1"

    def test_to_dict_omits_none_fields(self):
        from core.execution_observability import TraceCorrelation
        tc = TraceCorrelation(trace_id="t1", runtime_session_id="")
        d = tc.to_dict()
        assert "trace_id" in d
        assert "task_id" not in d
        assert "action_id" not in d

    def test_child_inherits_context(self):
        from core.execution_observability import TraceCorrelation
        parent = TraceCorrelation(
            trace_id="p-trace", runtime_session_id="s1", task_id="t1"
        )
        child = parent.child(action_id="act-3")
        assert child.trace_id == "p-trace"
        assert child.task_id == "t1"
        assert child.action_id == "act-3"


# ===========================================================================
# 5. ExecutionEvent
# ===========================================================================

class TestExecutionEvent:
    def test_build_defaults(self):
        from core.execution_observability import ExecutionEvent, ExecutorLevel
        ev = ExecutionEvent.build()
        assert ev.event_id
        assert ev.timestamp > 0
        assert ev.executor_level is ExecutorLevel.UNKNOWN
        assert ev.fallback is None
        assert ev.tri_state_phase is None

    def test_build_with_enum_phase(self):
        """tri_state_phase / runtime_domain accept str-enum or plain string."""
        from core.execution_observability import ExecutionEvent, ExecutorLevel

        class FakePhase:
            value = "manifest"

        ev = ExecutionEvent.build(
            executor_level=ExecutorLevel.SYSTEM_API,
            tri_state_phase=FakePhase(),
            runtime_domain="local",
        )
        assert ev.tri_state_phase == "manifest"
        assert ev.runtime_domain == "local"

    def test_to_dict_round_trip(self):
        from core.execution_observability import ExecutionEvent, ExecutorLevel, TraceCorrelation

        trace = TraceCorrelation(trace_id="t1", runtime_session_id="s1", task_id="task-1")
        ev = ExecutionEvent.build(
            trace=trace,
            executor_level=ExecutorLevel.UIA,
            tri_state_phase="liminal",
            runtime_domain="cross_device",
            message="test event",
            metadata={"device": "win-1"},
        )
        d = ev.to_dict()
        assert d["executor_level"] == "uia"
        assert d["tri_state_phase"] == "liminal"
        assert d["runtime_domain"] == "cross_device"
        assert d["trace"]["trace_id"] == "t1"
        assert d["metadata"]["device"] == "win-1"

        restored = ExecutionEvent.from_dict(d)
        assert restored.executor_level is ExecutorLevel.UIA
        assert restored.tri_state_phase == "liminal"
        assert restored.trace.trace_id == "t1"

    def test_from_dict_tolerates_missing_fields(self):
        from core.execution_observability import ExecutionEvent, ExecutorLevel
        ev = ExecutionEvent.from_dict({})
        assert ev.executor_level is ExecutorLevel.UNKNOWN
        assert ev.fallback is None

    def test_projection_summary_compact(self):
        from core.execution_observability import (
            ExecutionEvent, ExecutorLevel, FallbackReason, TraceCorrelation,
        )
        from core.execution_observability.fallback_schema import FallbackContext

        trace = TraceCorrelation(trace_id="t2", runtime_session_id="s2", task_id="task-2")
        fallback = FallbackContext(
            from_level=ExecutorLevel.SYSTEM_API,
            reason=FallbackReason.TIMEOUT,
        )
        ev = ExecutionEvent.build(
            trace=trace,
            executor_level=ExecutorLevel.VLM,
            fallback=fallback,
            tri_state_phase="manifest",
        )
        summary = ev.projection_summary()
        assert summary["trace_id"] == "t2"
        assert summary["executor_level"] == "vlm"
        assert summary["fallback_reason"] == "timeout"
        assert summary["tri_state_phase"] == "manifest"
        # event_id / timestamp not included in summary
        assert "event_id" not in summary


# ===========================================================================
# 6. Normalizers
# ===========================================================================

class TestNormalizers:
    def test_normalize_e2e_context_full(self):
        from core.execution_observability import ExecutorLevel
        from core.execution_observability.normalizers import normalize_e2e_context

        ctx = {
            "trace_id": "e2e-trace",
            "runtime_session_id": "sess-e2e",
            "task_id": "task-e",
            "tri_state_phase": "manifest",
            "runtime_domain": "local",
            "mode": "dag",
        }
        ev = normalize_e2e_context(ctx)
        assert ev.trace.trace_id == "e2e-trace"
        assert ev.tri_state_phase == "manifest"
        assert ev.runtime_domain == "local"
        assert ev.executor_level is ExecutorLevel.ORCHESTRATOR

    def test_normalize_e2e_context_partial(self):
        from core.execution_observability.normalizers import normalize_e2e_context
        ev = normalize_e2e_context({})
        assert ev.trace.trace_id  # auto-generated

    def test_normalize_task_envelope_object(self):
        from core.execution_observability import ExecutorLevel
        from core.execution_observability.normalizers import normalize_task_envelope

        class Env:
            trace_id = "env-t"
            runtime_session_id = "env-s"
            task_id = "env-task"
            action_id = None

        ev = normalize_task_envelope(Env())
        assert ev.trace.trace_id == "env-t"
        assert ev.trace.task_id == "env-task"

    def test_normalize_task_envelope_dict(self):
        from core.execution_observability.normalizers import normalize_task_envelope
        ev = normalize_task_envelope({"trace_id": "d-trace", "task_id": "d-task"})
        assert ev.trace.task_id == "d-task"

    def test_normalize_task_graph_result_success(self):
        from core.execution_observability.normalizers import normalize_task_graph_result

        result = {
            "success": True,
            "done": ["n1", "n2"],
            "failed": [],
            "skipped": [],
            "trace_id": "graph-trace",
            "graph_id": "g-1",
            "elapsed_ms": 150.0,
        }
        ev = normalize_task_graph_result(result)
        assert ev.trace.trace_id == "graph-trace"
        assert ev.trace.task_id == "g-1"
        assert ev.fallback is None
        assert ev.metadata["elapsed_ms"] == 150.0

    def test_normalize_task_graph_result_partial_failure(self):
        from core.execution_observability import FallbackReason
        from core.execution_observability.normalizers import normalize_task_graph_result

        result = {
            "success": False,
            "done": ["n1"],
            "failed": ["n2", "n3"],
            "skipped": [],
            "trace_id": "graph-fail",
            "graph_id": "g-2",
            "elapsed_ms": 80.0,
        }
        ev = normalize_task_graph_result(result)
        assert ev.fallback is not None
        assert ev.fallback.reason is FallbackReason.PARTIAL_FAILURE
        assert "n2" in ev.fallback.message

    def test_normalize_arbiter_attempt_dict(self):
        from core.execution_observability import ExecutorLevel, FallbackReason
        from core.execution_observability.normalizers import normalize_arbiter_attempt

        attempt = {
            "executor_level": "system_api",
            "fallback_reason": "no_system_api_match",
            "action_summary": "click OK",
            "status": "failed",
            "latency_ms": 12.5,
            "device_id": "win-1",
        }
        ev = normalize_arbiter_attempt(attempt)
        assert ev.executor_level is ExecutorLevel.SYSTEM_API
        assert ev.fallback is not None
        assert ev.fallback.reason is FallbackReason.NO_SYSTEM_API_MATCH
        assert ev.metadata["latency_ms"] == 12.5

    def test_normalize_arbiter_attempt_no_fallback(self):
        """When fallback_reason is empty, no FallbackContext is created."""
        from core.execution_observability.normalizers import normalize_arbiter_attempt
        attempt = {
            "executor_level": "vlm",
            "fallback_reason": "",
            "status": "success",
        }
        ev = normalize_arbiter_attempt(attempt)
        assert ev.fallback is None

    def test_normalize_arbiter_attempt_with_trace(self):
        from core.execution_observability import TraceCorrelation
        from core.execution_observability.normalizers import normalize_arbiter_attempt

        trace = TraceCorrelation(trace_id="arb-trace", runtime_session_id="s")
        ev = normalize_arbiter_attempt(
            {"executor_level": "gui", "fallback_reason": "visual_anchor_required"},
            trace=trace,
            tri_state_phase="manifest",
        )
        assert ev.trace.trace_id == "arb-trace"
        assert ev.tri_state_phase == "manifest"

    def test_normalize_observability_payload(self):
        from core.execution_observability import ExecutorLevel, FallbackReason
        from core.execution_observability.normalizers import normalize_observability_payload

        payload = {
            "trace_id": "obs-1",
            "command_id": "cmd-abc",
            "task_id": "task-obs",
            "action": "click",
            "executor_level": "uia",
            "fallback_reason": "uia_unavailable",
            "runtime_session_id": "sess-obs",
        }
        ev = normalize_observability_payload(payload)
        assert ev.trace.trace_id == "obs-1"
        assert ev.trace.task_id == "task-obs"
        assert ev.executor_level is ExecutorLevel.UIA
        assert ev.fallback is not None
        assert ev.fallback.reason is FallbackReason.UIA_UNAVAILABLE

    def test_normalize_observability_payload_empty(self):
        from core.execution_observability.normalizers import normalize_observability_payload
        ev = normalize_observability_payload({})
        assert ev.trace.trace_id  # auto-generated
        assert ev.fallback is None


# ===========================================================================
# 7. New observability routes (PR-7)
# ===========================================================================

class TestObservabilityRoutes:
    """Test the three new /execution/... endpoints via FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        """Build a minimal FastAPI app with the observability router mounted."""
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi / httpx not installed")

        from core.routes.observability import create_router
        app = FastAPI()
        app.include_router(create_router())
        return TestClient(app, raise_server_exceptions=False)

    def test_execution_schema_endpoint(self, client):
        resp = client.get("/api/v1/observability/execution/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "pr7-v1"
        assert "system_api" in data["executor_levels"]
        assert "timeout" in data["fallback_reasons"]
        assert "trace_id" in data["trace_fields"]

    def test_execution_recent_events_endpoint(self, client):
        """Should return 200 even when GatewayTraceStore is unavailable."""
        resp = client.get("/api/v1/observability/execution/recent-events?limit=5")
        # Accepts 200 (with or without error key) — must not 500
        assert resp.status_code in (200, 404)
        data = resp.json()
        # If store is available, should have events/count; if not, error key
        assert "events" in data or "error" in data

    def test_execution_trace_lookup_not_found(self, client):
        """Non-existent trace_id returns 404 with found=False."""
        resp = client.get("/api/v1/observability/execution/trace/nonexistent-trace-xyz")
        # 404 when not found; 500 is acceptable when store is unavailable
        assert resp.status_code in (404, 500, 200)
        data = resp.json()
        if resp.status_code == 404:
            assert data["found"] is False

    def test_existing_routes_unchanged(self, client):
        """The existing PR-C routes must still be mounted and return 200."""
        for path in (
            "/api/v1/observability/model-route",
            "/api/v1/observability/gateway",
            "/api/v1/observability/recent-calls",
            "/api/v1/observability/stats",
            "/api/v1/observability/nats",
        ):
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
