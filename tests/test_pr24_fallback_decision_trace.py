"""
tests/test_pr24_fallback_decision_trace.py
=============================================
Focused tests for PR-24: Fallback Decision Trace.

Coverage
--------
1. FallbackOutcome
   - enum values are stable strings
   - from_string normalisation and unknown fallback

2. FallbackDecisionSource
   - enum values are stable strings
   - from_string normalisation and unknown fallback

3. FallbackCandidate
   - construction with defaults
   - to_dict / from_dict round-trip

4. FallbackDecisionTrace
   - construction with defaults (safe minimal)
   - construction with all fields specified
   - serialisation stability: to_dict is JSON-serialisable
   - to_json / to_dict round-trip preserves fields
   - compact_summary() contains expected keys and values
   - timestamp field is auto-populated

5. FallbackDecisionResult
   - construction with defaults
   - to_dict / to_json round-trip

6. build_fallback_trace()
   (a) Primary blocked → readiness gate (missing_target)
       - outcome is blocked
       - decision_source is readiness_gate
       - primary_block_reason reflects the readiness reason
   (b) Primary blocked → observe-only (policy)
       - outcome is noop
       - fallback_path is noop
   (c) Executor unavailable → degraded
       - outcome is degraded
       - fallback_path is local_fallback
   (d) Remote fallback (bridge fell back to local)
       - outcome is selected
       - fallback_path is local_fallback
       - decision_source is bridge
   (e) Internal error → failed
       - outcome is failed
   (f) Successful execution → selected
       - outcome is selected
   (g) Missing metadata (all None inputs)
       - returns a valid FallbackDecisionTrace with defaults
       - never raises
   (h) Malformed inputs (non-dict execution_result, garbage intent_profile)
       - returns a valid FallbackDecisionTrace with defaults
       - never raises

7. summarize_fallback_trace()
   - returns a dict with expected keys
   - works even when trace has minimal fields

8. Integration with ExecutionIntentProfile (PR-22)
   - intent_id propagated to trace
   - action_level extracted correctly

9. Integration with ReadinessResult (PR-23)
   - blocked_by=missing_target → decision_source=readiness_gate
   - blocked_by=policy → decision_source=policy
   - blocked_by=hitl → decision_source=policy
   - blocked_by=runtime_phase → decision_source=runtime

10. OpenClawd._build_fallback_trace() integration
    - returns a compact dict for a valid execution result
    - returns None gracefully when module raises
    - _run_execution() result dict includes "fallback_trace" key
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.execution.fallback_trace import (
    FallbackCandidate,
    FallbackDecisionResult,
    FallbackDecisionSource,
    FallbackDecisionTrace,
    FallbackOutcome,
    build_fallback_trace,
    summarize_fallback_trace,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_intent_profile(
    intent_id: str = "test-intent-001",
    action_level: str = "execute",
    runtime_session_id: str = "sess-abc",
    device_scope: Optional[str] = "local",
    runtime_domain: Optional[str] = "local",
) -> MagicMock:
    profile = MagicMock()
    profile.intent_id = intent_id
    profile.action_level = action_level
    profile.runtime_session_id = runtime_session_id
    profile.device_scope = device_scope
    profile.runtime_domain = runtime_domain
    return profile


def _make_readiness_result(
    ready: bool = False,
    status: str = "blocked",
    blocked_by: str = "missing_target",
    reason: str = "execution target is required but was not resolved",
) -> MagicMock:
    result = MagicMock()
    result.ready = ready
    result.status = status
    result.blocked_by = blocked_by
    result.reason = reason
    return result


# ---------------------------------------------------------------------------
# 1. FallbackOutcome
# ---------------------------------------------------------------------------


class TestFallbackOutcome:
    def test_enum_values_are_stable_strings(self):
        assert FallbackOutcome.SELECTED.value == "selected"
        assert FallbackOutcome.BLOCKED.value == "blocked"
        assert FallbackOutcome.NOOP.value == "noop"
        assert FallbackOutcome.DEGRADED.value == "degraded"
        assert FallbackOutcome.FAILED.value == "failed"

    def test_from_string_known_value(self):
        assert FallbackOutcome.from_string("selected") is FallbackOutcome.SELECTED
        assert FallbackOutcome.from_string("noop") is FallbackOutcome.NOOP
        assert FallbackOutcome.from_string("BLOCKED") is FallbackOutcome.BLOCKED

    def test_from_string_unknown_falls_back_to_blocked(self):
        assert FallbackOutcome.from_string("nonexistent") is FallbackOutcome.BLOCKED
        assert FallbackOutcome.from_string("") is FallbackOutcome.BLOCKED
        assert FallbackOutcome.from_string(None) is FallbackOutcome.BLOCKED  # type: ignore[arg-type]

    def test_is_str_mixin(self):
        # Should be usable as a plain string in JSON
        assert json.dumps({"outcome": FallbackOutcome.SELECTED}) == '{"outcome": "selected"}'


# ---------------------------------------------------------------------------
# 2. FallbackDecisionSource
# ---------------------------------------------------------------------------


class TestFallbackDecisionSource:
    def test_enum_values_are_stable_strings(self):
        assert FallbackDecisionSource.POLICY.value == "policy"
        assert FallbackDecisionSource.READINESS_GATE.value == "readiness_gate"
        assert FallbackDecisionSource.RUNTIME.value == "runtime"
        assert FallbackDecisionSource.BRIDGE.value == "bridge"
        assert FallbackDecisionSource.EXECUTOR.value == "executor"
        assert FallbackDecisionSource.UNKNOWN.value == "unknown"

    def test_from_string_known_value(self):
        assert FallbackDecisionSource.from_string("policy") is FallbackDecisionSource.POLICY
        assert FallbackDecisionSource.from_string("BRIDGE") is FallbackDecisionSource.BRIDGE

    def test_from_string_unknown_falls_back_to_unknown(self):
        assert FallbackDecisionSource.from_string("bogus") is FallbackDecisionSource.UNKNOWN
        assert FallbackDecisionSource.from_string("") is FallbackDecisionSource.UNKNOWN

    def test_is_str_mixin(self):
        assert json.dumps({"src": FallbackDecisionSource.EXECUTOR}) == '{"src": "executor"}'


# ---------------------------------------------------------------------------
# 3. FallbackCandidate
# ---------------------------------------------------------------------------


class TestFallbackCandidate:
    def test_default_construction(self):
        c = FallbackCandidate()
        assert c.path == "unknown"
        assert c.executor_level is None
        assert c.reason_blocked is None
        assert c.evaluated is True
        assert c.selected is False
        assert c.metadata == {}

    def test_full_construction(self):
        c = FallbackCandidate(
            path="local_executor",
            executor_level="system_api",
            reason_blocked="policy_blocked",
            evaluated=True,
            selected=False,
            metadata={"detail": "OBSERVE_ONLY band"},
        )
        assert c.path == "local_executor"
        assert c.executor_level == "system_api"
        assert c.reason_blocked == "policy_blocked"
        assert c.metadata == {"detail": "OBSERVE_ONLY band"}

    def test_to_dict_round_trip(self):
        c = FallbackCandidate(
            path="noop",
            selected=True,
            metadata={"x": 1},
        )
        d = c.to_dict()
        assert d["path"] == "noop"
        assert d["selected"] is True
        assert json.dumps(d)  # must be JSON-serialisable

        restored = FallbackCandidate.from_dict(d)
        assert restored.path == c.path
        assert restored.selected == c.selected
        assert restored.metadata == c.metadata

    def test_from_dict_missing_keys_safe(self):
        c = FallbackCandidate.from_dict({})
        assert c.path == "unknown"
        assert c.selected is False


# ---------------------------------------------------------------------------
# 4. FallbackDecisionTrace
# ---------------------------------------------------------------------------


class TestFallbackDecisionTrace:
    def test_default_construction(self):
        t = FallbackDecisionTrace()
        assert t.trace_id  # non-empty UUID string
        assert t.runtime_session_id is None
        assert t.intent_id is None
        assert t.action_level == "observe"
        assert t.primary_path is None
        assert t.primary_block_reason is None
        assert t.fallback_path is None
        assert t.decision_source == FallbackDecisionSource.UNKNOWN.value
        assert t.candidate_paths == []
        assert t.outcome == FallbackOutcome.BLOCKED.value
        assert t.notes is None
        assert isinstance(t.timestamp, float) and t.timestamp > 0

    def test_full_construction(self):
        t = FallbackDecisionTrace(
            trace_id="trace-001",
            runtime_session_id="sess-xyz",
            intent_id="intent-abc",
            action_level="execute",
            primary_path="local_executor",
            primary_block_reason="policy blocked",
            fallback_path="noop",
            fallback_reason="observe_only",
            decision_source=FallbackDecisionSource.POLICY.value,
            candidate_paths=[{"path": "noop", "selected": True}],
            outcome=FallbackOutcome.NOOP.value,
            notes="test note",
        )
        assert t.trace_id == "trace-001"
        assert t.intent_id == "intent-abc"
        assert t.action_level == "execute"
        assert t.primary_path == "local_executor"
        assert t.decision_source == "policy"
        assert t.outcome == "noop"
        assert t.notes == "test note"

    def test_serialisation_is_json_serialisable(self):
        t = FallbackDecisionTrace(
            action_level="execute",
            primary_path="local_executor",
            outcome=FallbackOutcome.BLOCKED.value,
        )
        d = t.to_dict()
        serialised = json.dumps(d)
        assert serialised  # must not raise

    def test_to_json_round_trip(self):
        t = FallbackDecisionTrace(
            trace_id="round-trip-test",
            action_level="assist",
            outcome=FallbackOutcome.DEGRADED.value,
            notes="round-trip",
        )
        json_str = t.to_json()
        restored_dict = json.loads(json_str)
        assert restored_dict["trace_id"] == "round-trip-test"
        assert restored_dict["action_level"] == "assist"
        assert restored_dict["outcome"] == "degraded"
        assert restored_dict["notes"] == "round-trip"

    def test_compact_summary_keys(self):
        t = FallbackDecisionTrace(
            intent_id="intent-123",
            action_level="execute",
            primary_path="local_executor",
            outcome=FallbackOutcome.BLOCKED.value,
        )
        s = t.compact_summary()
        assert "trace_id" in s
        assert "intent_id" in s
        assert "action_level" in s
        assert "primary_path" in s
        assert "primary_block_reason" in s
        assert "fallback_path" in s
        assert "decision_source" in s
        assert "outcome" in s
        assert s["intent_id"] == "intent-123"
        assert s["action_level"] == "execute"
        assert s["outcome"] == "blocked"

    def test_timestamp_auto_populated(self):
        import time
        before = time.time()
        t = FallbackDecisionTrace()
        after = time.time()
        assert before <= t.timestamp <= after


# ---------------------------------------------------------------------------
# 5. FallbackDecisionResult
# ---------------------------------------------------------------------------


class TestFallbackDecisionResult:
    def test_default_construction(self):
        r = FallbackDecisionResult()
        assert r.trace == {}
        assert r.outcome == FallbackOutcome.BLOCKED.value
        assert r.has_fallback is False

    def test_full_construction(self):
        trace_dict = FallbackDecisionTrace(outcome="selected").to_dict()
        r = FallbackDecisionResult(
            trace=trace_dict,
            outcome=FallbackOutcome.SELECTED.value,
            has_fallback=True,
        )
        assert r.has_fallback is True
        assert r.outcome == "selected"

    def test_to_dict_json_serialisable(self):
        r = FallbackDecisionResult(
            trace={"outcome": "noop"},
            outcome="noop",
            has_fallback=False,
        )
        d = r.to_dict()
        assert json.dumps(d)

    def test_to_json_round_trip(self):
        r = FallbackDecisionResult(outcome="degraded", has_fallback=True)
        j = r.to_json()
        d = json.loads(j)
        assert d["outcome"] == "degraded"
        assert d["has_fallback"] is True


# ---------------------------------------------------------------------------
# 6. build_fallback_trace()
# ---------------------------------------------------------------------------


class TestBuildFallbackTrace:
    def test_primary_blocked_missing_target(self):
        """Readiness gate blocks with missing_target → blocked outcome."""
        profile = _make_intent_profile(action_level="execute")
        readiness = _make_readiness_result(
            ready=False,
            status="blocked",
            blocked_by="missing_target",
            reason="execution target is required but was not resolved",
        )
        exec_result = {
            "action_taken": "none",
            "success": False,
            "skipped_reason": "readiness_gate:blocked:missing_target",
        }
        trace = build_fallback_trace(
            intent_profile=profile,
            readiness_result=readiness,
            execution_result=exec_result,
        )
        assert trace.outcome == FallbackOutcome.BLOCKED.value
        assert trace.decision_source == FallbackDecisionSource.READINESS_GATE.value
        assert trace.primary_block_reason  # non-empty
        assert trace.intent_id == "test-intent-001"
        assert trace.action_level == "execute"

    def test_primary_blocked_observe_only_noop(self):
        """Readiness gate returns observe_only → noop outcome."""
        profile = _make_intent_profile(action_level="observe")
        readiness = _make_readiness_result(
            ready=False,
            status="observe_only",
            blocked_by="action_level",
            reason="observe/hint action levels are not permitted to execute",
        )
        exec_result = {
            "action_taken": "none",
            "success": False,
            "skipped_reason": "readiness_gate:observe_only:action_level",
        }
        trace = build_fallback_trace(
            intent_profile=profile,
            readiness_result=readiness,
            execution_result=exec_result,
        )
        assert trace.outcome == FallbackOutcome.NOOP.value
        assert trace.fallback_path == "noop"

    def test_executor_unavailable_degraded(self):
        """Executor is None → degraded outcome."""
        profile = _make_intent_profile(action_level="execute")
        exec_result = {
            "action_taken": "none",
            "success": False,
            "skipped_reason": "executor_unavailable",
        }
        trace = build_fallback_trace(
            intent_profile=profile,
            readiness_result=None,
            execution_result=exec_result,
        )
        assert trace.outcome == FallbackOutcome.DEGRADED.value
        assert trace.fallback_path == "local_fallback"
        assert trace.decision_source == FallbackDecisionSource.EXECUTOR.value

    def test_remote_fallback_bridge(self):
        """Bridge falls back to local when remote is unavailable → selected outcome."""
        profile = _make_intent_profile(
            action_level="execute",
            device_scope="remote",
            runtime_domain="cross_device",
        )
        exec_result = {
            "action_taken": "open_app",
            "success": True,
            "skipped_reason": None,
            "metadata": {
                "remote_fallback": True,
                "fallback_reason": "remote_device_unavailable",
            },
        }
        trace = build_fallback_trace(
            intent_profile=profile,
            readiness_result=None,
            execution_result=exec_result,
        )
        assert trace.outcome == FallbackOutcome.SELECTED.value
        assert trace.fallback_path == "local_fallback"
        assert trace.fallback_reason == "remote_device_unavailable"
        assert trace.decision_source == FallbackDecisionSource.BRIDGE.value

    def test_internal_error_failed(self):
        """Internal executor exception → failed outcome."""
        profile = _make_intent_profile(action_level="execute")
        exec_result = {
            "action_taken": "error",
            "success": False,
            "skipped_reason": "internal_error: some exception",
        }
        trace = build_fallback_trace(
            intent_profile=profile,
            readiness_result=None,
            execution_result=exec_result,
        )
        assert trace.outcome == FallbackOutcome.FAILED.value

    def test_successful_execution_selected(self):
        """Successful execution on primary path → selected outcome."""
        profile = _make_intent_profile(action_level="execute")
        exec_result = {
            "action_taken": "open_app",
            "success": True,
            "skipped_reason": None,
            "metadata": {},
        }
        trace = build_fallback_trace(
            intent_profile=profile,
            readiness_result=None,
            execution_result=exec_result,
        )
        assert trace.outcome == FallbackOutcome.SELECTED.value
        assert trace.fallback_path == "open_app"

    def test_all_none_inputs_safe(self):
        """All None inputs — returns a valid minimal trace, never raises."""
        trace = build_fallback_trace(
            intent_profile=None,
            readiness_result=None,
            execution_result=None,
        )
        assert isinstance(trace, FallbackDecisionTrace)
        assert trace.trace_id  # auto-generated
        # Serialisation must not raise
        assert json.dumps(trace.to_dict())

    def test_malformed_execution_result_safe(self):
        """Non-dict execution_result — returns valid trace, never raises."""
        trace = build_fallback_trace(
            intent_profile=None,
            readiness_result=None,
            execution_result="not-a-dict",  # type: ignore[arg-type]
        )
        assert isinstance(trace, FallbackDecisionTrace)
        assert json.dumps(trace.to_dict())

    def test_exception_in_intent_profile_safe(self):
        """Intent profile that raises on attribute access — trace still produced."""
        broken_profile = MagicMock()
        broken_profile.intent_id = MagicMock(side_effect=RuntimeError("boom"))
        trace = build_fallback_trace(
            intent_profile=broken_profile,
            readiness_result=None,
            execution_result=None,
        )
        assert isinstance(trace, FallbackDecisionTrace)

    def test_runtime_session_id_override(self):
        """Explicit runtime_session_id overrides the value from intent_profile."""
        profile = _make_intent_profile(runtime_session_id="original-session")
        trace = build_fallback_trace(
            intent_profile=profile,
            runtime_session_id="override-session",
        )
        assert trace.runtime_session_id == "override-session"

    def test_notes_propagated(self):
        trace = build_fallback_trace(notes="debug-note")
        assert trace.notes == "debug-note"


# ---------------------------------------------------------------------------
# 7. summarize_fallback_trace()
# ---------------------------------------------------------------------------


class TestSummarizeFallbackTrace:
    def test_returns_expected_keys(self):
        trace = FallbackDecisionTrace(
            intent_id="i-001",
            action_level="execute",
            outcome=FallbackOutcome.BLOCKED.value,
        )
        s = summarize_fallback_trace(trace)
        for key in ("trace_id", "intent_id", "action_level", "primary_path",
                    "primary_block_reason", "fallback_path", "decision_source", "outcome"):
            assert key in s, f"key {key!r} missing from summary"

    def test_minimal_trace_summary_safe(self):
        trace = FallbackDecisionTrace()
        s = summarize_fallback_trace(trace)
        assert s["outcome"] == FallbackOutcome.BLOCKED.value

    def test_summary_is_json_serialisable(self):
        trace = FallbackDecisionTrace(outcome="selected", action_level="assist")
        s = summarize_fallback_trace(trace)
        assert json.dumps(s)

    def test_broken_trace_returns_fallback_dict(self):
        """summarize_fallback_trace never raises even with a broken trace object."""
        broken = MagicMock()
        broken.compact_summary = MagicMock(side_effect=RuntimeError("boom"))
        result = summarize_fallback_trace(broken)
        assert result == {"outcome": FallbackOutcome.BLOCKED.value}


# ---------------------------------------------------------------------------
# 8. Integration with ExecutionIntentProfile (PR-22)
# ---------------------------------------------------------------------------


class TestIntentProfileIntegration:
    def test_intent_id_propagated(self):
        from core.execution.intent_profile import ExecutionIntentProfile

        profile = ExecutionIntentProfile(
            intent_id="real-intent-id",
            action_level="execute",
            runtime_session_id="sess-001",
        )
        trace = build_fallback_trace(intent_profile=profile)
        assert trace.intent_id == "real-intent-id"
        assert trace.action_level == "execute"
        assert trace.runtime_session_id == "sess-001"

    def test_action_level_extracted_correctly(self):
        from core.execution.intent_profile import ExecutionIntentProfile

        for level in ("observe", "hint", "assist", "execute"):
            profile = ExecutionIntentProfile(action_level=level)
            trace = build_fallback_trace(intent_profile=profile)
            assert trace.action_level == level


# ---------------------------------------------------------------------------
# 9. Integration with ReadinessResult (PR-23)
# ---------------------------------------------------------------------------


class TestReadinessResultIntegration:
    def test_missing_target_maps_to_readiness_gate(self):
        readiness = _make_readiness_result(blocked_by="missing_target")
        trace = build_fallback_trace(readiness_result=readiness)
        assert trace.decision_source == FallbackDecisionSource.READINESS_GATE.value

    def test_policy_blocked_by_maps_to_policy(self):
        readiness = _make_readiness_result(blocked_by="policy")
        trace = build_fallback_trace(readiness_result=readiness)
        assert trace.decision_source == FallbackDecisionSource.POLICY.value

    def test_hitl_blocked_by_maps_to_policy(self):
        readiness = _make_readiness_result(blocked_by="hitl")
        trace = build_fallback_trace(readiness_result=readiness)
        assert trace.decision_source == FallbackDecisionSource.POLICY.value

    def test_runtime_phase_blocked_by_maps_to_runtime(self):
        readiness = _make_readiness_result(blocked_by="runtime_phase")
        trace = build_fallback_trace(readiness_result=readiness)
        assert trace.decision_source == FallbackDecisionSource.RUNTIME.value

    def test_domain_blocked_by_maps_to_runtime(self):
        readiness = _make_readiness_result(blocked_by="domain")
        trace = build_fallback_trace(readiness_result=readiness)
        assert trace.decision_source == FallbackDecisionSource.RUNTIME.value

    def test_action_level_blocked_maps_to_readiness_gate(self):
        readiness = _make_readiness_result(blocked_by="action_level")
        trace = build_fallback_trace(readiness_result=readiness)
        assert trace.decision_source == FallbackDecisionSource.READINESS_GATE.value

    def test_real_readiness_result_object(self):
        """Test with an actual ReadinessResult from the readiness gate module."""
        from core.execution.readiness_gate import ReadinessResult, ReadinessStatus, BlockedBy

        rr = ReadinessResult(
            ready=False,
            status=ReadinessStatus.BLOCKED,
            blocked_by=BlockedBy.MISSING_TARGET,
            reason="no execution target",
            intent_id="intent-xyz",
        )
        trace = build_fallback_trace(readiness_result=rr)
        assert trace.outcome == FallbackOutcome.BLOCKED.value
        assert trace.decision_source == FallbackDecisionSource.READINESS_GATE.value


# ---------------------------------------------------------------------------
# 10. OpenClawd._build_fallback_trace() integration
# ---------------------------------------------------------------------------


class TestOpenClawdBuildFallbackTrace:
    """Tests for the _build_fallback_trace() integration in OpenClawd."""

    def _make_openclawd(self):
        """Return a minimal OpenClawd instance (config optional)."""
        try:
            from core.openclawd import OpenClawd  # noqa: PLC0415
            with patch("core.openclawd.OpenClawd._load_config", return_value={}):
                oc = OpenClawd.__new__(OpenClawd)
                oc._config = {}
                oc._session_id = "test-session"
                return oc
        except Exception:
            pytest.skip("OpenClawd not importable in this environment")

    def test_returns_compact_dict_for_valid_inputs(self):
        oc = self._make_openclawd()
        profile = _make_intent_profile()
        readiness = _make_readiness_result()
        exec_result = {
            "action_taken": "none",
            "success": False,
            "skipped_reason": "readiness_gate:blocked:missing_target",
        }
        result = oc._build_fallback_trace(profile, readiness, exec_result)
        assert result is not None
        assert isinstance(result, dict)
        assert "outcome" in result
        assert "trace_id" in result

    def test_returns_none_when_module_raises(self):
        oc = self._make_openclawd()
        with patch(
            "core.execution.fallback_trace.build_fallback_trace",
            side_effect=RuntimeError("module error"),
        ):
            result = oc._build_fallback_trace(None, None, None)
            assert result is None

    def test_run_execution_result_includes_fallback_trace_key(self):
        """_run_execution() result dict always includes a 'fallback_trace' key."""
        from core.openclawd import OpenClawd  # noqa: PLC0415

        continuum = {
            "phase": "manifest",
            "runtime_domain": "local",
            "decision": {"action_level": "execute", "decision_confidence": 0.9},
            "metadata": {"execution_target": "notepad.exe"},
        }

        mock_result = MagicMock()
        mock_result.action_taken = "open_app"
        mock_result.target = "notepad.exe"
        mock_result.success = True
        mock_result.skipped_reason = None
        mock_result.metadata = {}

        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_result

        oc = OpenClawd.__new__(OpenClawd)
        oc._config = {}
        oc._session_id = "test-session"
        oc._executor = None
        oc._continuum_orchestrator = None
        oc._decision_executor = None

        with patch.object(OpenClawd, "_get_decision_executor", return_value=mock_executor):
            result = oc._run_execution(continuum, entry_mode="local")
            assert "fallback_trace" in result
            # The fallback_trace may be a dict or None (never raises)
