"""
tests/test_pr25_execution_trace_contract.py
=============================================
Focused tests for PR-25: Execution Trace Contract.

Coverage
--------
1. ExecutionTraceStage
   - enum values are stable strings
   - from_string normalisation and unknown fallback

2. ExecutionTraceStatus
   - enum values are stable strings
   - from_string normalisation and unknown fallback

3. ExecutionTraceEvent
   - construction with defaults (safe minimal)
   - construction with all fields specified
   - serialisation stability: to_dict is JSON-serialisable
   - to_json / to_dict round-trip preserves fields
   - compact_summary() contains expected keys and values
   - trace_id / event_id / timestamp auto-populated

4. ExecutionTraceEnvelope
   - construction with defaults
   - append() updates final_status and events list
   - append() with PENDING/SKIPPED events does not overwrite non-pending final_status
   - to_dict / to_json round-trip
   - compact_summary() contains expected keys

5. from_execution_intent()
   - extracts intent_id, action_level, runtime_domain, target_ref from profile
   - stage is intent_created
   - status is success for normal profile
   - status is degraded when degrade_reason is set
   - returns safe defaults when intent_profile is None
   - never raises on garbage input

6. from_readiness_result()
   - extracts ready/status/blocked_by from ReadinessResult-like object
   - stage is readiness_evaluated
   - status is success when ready=True, requires_confirmation=False
   - status is pending when ready=True, requires_confirmation=True
   - status is blocked when ready=False
   - status is skipped when status is observe_only
   - returns safe skipped event when readiness_result is None
   - never raises on garbage input

7. from_fallback_trace()
   - extracts outcome / fallback_path / decision_source from FallbackDecisionTrace
   - stage is fallback_selected
   - outcome=selected → status success
   - outcome=blocked  → status blocked
   - outcome=noop     → status skipped
   - outcome=degraded → status degraded
   - outcome=failed   → status failed
   - returns safe skipped event when fallback_trace is None
   - never raises on garbage input

8. from_execution_result()
   - extracts action_taken / success / skipped_reason / target from result dict
   - action_taken=error            → stage execution_blocked, status failed
   - action_taken=none, success=F  → stage execution_blocked, status blocked
   - action_taken=none, success=T  → stage execution_finished, status skipped
   - action_taken=<real>, success=T → stage execution_finished, status success
   - action_taken=<real>, success=F → stage execution_finished, status failed
   - returns safe blocked event when execution_result is None
   - never raises on garbage input

9. build_trace_envelope()
   - produces envelope with one event per available stage
   - all events share the same trace_id
   - final_status reflects last substantive event
   - compact_summary() keys present
   - never raises on all-None inputs
   - never raises on partial inputs

10. Integration with PR-22 ExecutionIntentProfile
    - intent_id propagated from profile to event
    - runtime_session_id propagated

11. Integration with PR-23 ReadinessResult
    - blocked_by and reason propagated into event details and reason

12. Integration with PR-24 FallbackDecisionTrace
    - fallback_path and decision_source propagated into event details

13. OpenClawd._build_execution_trace() integration
    - returns a compact dict for a valid execution result
    - returns None gracefully when module raises
    - _run_execution() result dict includes "execution_trace" key
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from contracts.execution_trace import (
    ExecutionTraceEnvelope,
    ExecutionTraceEvent,
    ExecutionTraceStage,
    ExecutionTraceStatus,
    build_trace_envelope,
    from_execution_intent,
    from_execution_result,
    from_fallback_trace,
    from_readiness_result,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_intent_profile(
    *,
    intent_id: Optional[str] = None,
    runtime_session_id: str = "sess-abc",
    action_level: str = "execute",
    runtime_domain: str = "local",
    target_ref: Optional[str] = "notepad.exe",
    source: str = "openclawd",
    degrade_reason: Optional[str] = None,
    intent_mode: str = "direct",
    confidence: float = 0.9,
    origin_state: Optional[str] = "manifest",
) -> MagicMock:
    profile = MagicMock()
    profile.intent_id = intent_id or str(uuid.uuid4())
    profile.runtime_session_id = runtime_session_id
    profile.action_level = action_level
    profile.runtime_domain = runtime_domain
    profile.target_ref = target_ref
    profile.source = source
    profile.degrade_reason = degrade_reason
    profile.intent_mode = intent_mode
    profile.confidence = confidence
    profile.origin_state = origin_state
    return profile


def _make_readiness_result(
    *,
    ready: bool = True,
    status: str = "ready",
    reason: str = "all checks passed",
    requires_confirmation: bool = False,
    policy_band: Optional[str] = "full_execute",
    blocked_by: str = "none",
    runtime_session_id: str = "sess-abc",
    intent_id: Optional[str] = None,
    action_level: str = "execute",
    runtime_domain: str = "local",
) -> MagicMock:
    r = MagicMock()
    r.ready = ready
    r.status = status
    r.reason = reason
    r.requires_confirmation = requires_confirmation
    r.policy_band = policy_band
    r.blocked_by = blocked_by
    r.runtime_session_id = runtime_session_id
    r.intent_id = intent_id or str(uuid.uuid4())
    r.action_level = action_level
    r.runtime_domain = runtime_domain
    return r


def _make_fallback_trace(
    *,
    runtime_session_id: str = "sess-abc",
    intent_id: Optional[str] = None,
    action_level: str = "execute",
    outcome: str = "selected",
    primary_block_reason: Optional[str] = None,
    fallback_path: Optional[str] = "local_fallback",
    fallback_reason: Optional[str] = None,
    decision_source: str = "readiness_gate",
) -> MagicMock:
    ft = MagicMock()
    ft.runtime_session_id = runtime_session_id
    ft.intent_id = intent_id or str(uuid.uuid4())
    ft.action_level = action_level
    ft.outcome = outcome
    ft.primary_block_reason = primary_block_reason
    ft.fallback_path = fallback_path
    ft.fallback_reason = fallback_reason
    ft.decision_source = decision_source
    return ft


def _make_exec_result(
    *,
    action_taken: str = "click",
    success: bool = True,
    skipped_reason: str = "",
    target: Optional[str] = "notepad.exe",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "action_taken": action_taken,
        "success": success,
        "skipped_reason": skipped_reason,
        "target": target,
        "metadata": metadata or {},
    }


# ---------------------------------------------------------------------------
# 1. ExecutionTraceStage
# ---------------------------------------------------------------------------


class TestExecutionTraceStage:
    def test_stable_string_values(self):
        assert ExecutionTraceStage.INTENT_CREATED.value == "intent_created"
        assert ExecutionTraceStage.READINESS_EVALUATED.value == "readiness_evaluated"
        assert ExecutionTraceStage.FALLBACK_SELECTED.value == "fallback_selected"
        assert ExecutionTraceStage.EXECUTION_STARTED.value == "execution_started"
        assert ExecutionTraceStage.EXECUTION_FINISHED.value == "execution_finished"
        assert ExecutionTraceStage.EXECUTION_BLOCKED.value == "execution_blocked"

    def test_from_string_known_value(self):
        assert ExecutionTraceStage.from_string("intent_created") == ExecutionTraceStage.INTENT_CREATED
        assert ExecutionTraceStage.from_string("execution_finished") == ExecutionTraceStage.EXECUTION_FINISHED

    def test_from_string_unknown_falls_back(self):
        result = ExecutionTraceStage.from_string("totally_unknown")
        assert result == ExecutionTraceStage.EXECUTION_BLOCKED

    def test_from_string_empty_falls_back(self):
        result = ExecutionTraceStage.from_string("")
        assert result == ExecutionTraceStage.EXECUTION_BLOCKED

    def test_from_string_none_falls_back(self):
        # Should handle None without raising
        result = ExecutionTraceStage.from_string(None)  # type: ignore[arg-type]
        assert result == ExecutionTraceStage.EXECUTION_BLOCKED


# ---------------------------------------------------------------------------
# 2. ExecutionTraceStatus
# ---------------------------------------------------------------------------


class TestExecutionTraceStatus:
    def test_stable_string_values(self):
        assert ExecutionTraceStatus.PENDING.value == "pending"
        assert ExecutionTraceStatus.SUCCESS.value == "success"
        assert ExecutionTraceStatus.FAILED.value == "failed"
        assert ExecutionTraceStatus.BLOCKED.value == "blocked"
        assert ExecutionTraceStatus.DEGRADED.value == "degraded"
        assert ExecutionTraceStatus.SKIPPED.value == "skipped"

    def test_from_string_known_value(self):
        assert ExecutionTraceStatus.from_string("success") == ExecutionTraceStatus.SUCCESS
        assert ExecutionTraceStatus.from_string("blocked") == ExecutionTraceStatus.BLOCKED

    def test_from_string_unknown_falls_back_to_pending(self):
        result = ExecutionTraceStatus.from_string("totally_unknown")
        assert result == ExecutionTraceStatus.PENDING

    def test_from_string_empty_falls_back(self):
        assert ExecutionTraceStatus.from_string("") == ExecutionTraceStatus.PENDING


# ---------------------------------------------------------------------------
# 3. ExecutionTraceEvent
# ---------------------------------------------------------------------------


class TestExecutionTraceEvent:
    def test_default_construction(self):
        event = ExecutionTraceEvent()
        assert event.trace_id
        assert event.event_id
        assert event.stage == ExecutionTraceStage.INTENT_CREATED.value
        assert event.status == ExecutionTraceStatus.PENDING.value
        assert event.action_level == "observe"
        assert event.source == "openclawd"
        assert isinstance(event.timestamp, float)
        assert event.timestamp > 0

    def test_full_construction(self):
        tid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        event = ExecutionTraceEvent(
            trace_id=tid,
            event_id=eid,
            runtime_session_id="sess-123",
            intent_id="intent-456",
            stage=ExecutionTraceStage.EXECUTION_FINISHED.value,
            status=ExecutionTraceStatus.SUCCESS.value,
            action_level="execute",
            runtime_domain="local",
            target_ref="notepad.exe",
            reason=None,
            source="executor",
            details={"action_taken": "click"},
        )
        assert event.trace_id == tid
        assert event.event_id == eid
        assert event.intent_id == "intent-456"
        assert event.stage == "execution_finished"
        assert event.status == "success"

    def test_to_dict_is_json_serialisable(self):
        event = ExecutionTraceEvent(
            stage=ExecutionTraceStage.EXECUTION_FINISHED.value,
            status=ExecutionTraceStatus.SUCCESS.value,
            details={"key": "value"},
        )
        d = event.to_dict()
        # Must be JSON-serialisable
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_to_json_round_trip(self):
        event = ExecutionTraceEvent(
            trace_id="trace-1",
            intent_id="intent-1",
            stage=ExecutionTraceStage.READINESS_EVALUATED.value,
            status=ExecutionTraceStatus.BLOCKED.value,
            action_level="execute",
            reason="policy_blocked",
        )
        d = json.loads(event.to_json())
        assert d["trace_id"] == "trace-1"
        assert d["intent_id"] == "intent-1"
        assert d["stage"] == "readiness_evaluated"
        assert d["status"] == "blocked"
        assert d["reason"] == "policy_blocked"

    def test_compact_summary_keys(self):
        event = ExecutionTraceEvent(
            trace_id="trace-1",
            intent_id="intent-1",
            stage=ExecutionTraceStage.INTENT_CREATED.value,
            status=ExecutionTraceStatus.SUCCESS.value,
        )
        summary = event.compact_summary()
        assert "trace_id" in summary
        assert "event_id" in summary
        assert "stage" in summary
        assert "status" in summary
        assert "action_level" in summary
        assert "intent_id" in summary
        assert "timestamp" in summary

    def test_trace_id_and_event_id_are_distinct(self):
        event = ExecutionTraceEvent()
        assert event.trace_id != event.event_id

    def test_different_events_have_different_event_ids(self):
        e1 = ExecutionTraceEvent()
        e2 = ExecutionTraceEvent()
        assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------------
# 4. ExecutionTraceEnvelope
# ---------------------------------------------------------------------------


class TestExecutionTraceEnvelope:
    def test_default_construction(self):
        env = ExecutionTraceEnvelope()
        assert env.trace_id
        assert env.events == []
        assert env.final_status == ExecutionTraceStatus.PENDING.value
        assert isinstance(env.created_at, float)

    def test_append_updates_events_and_final_status(self):
        env = ExecutionTraceEnvelope()
        event = ExecutionTraceEvent(
            trace_id=env.trace_id,
            stage=ExecutionTraceStage.EXECUTION_FINISHED.value,
            status=ExecutionTraceStatus.SUCCESS.value,
        )
        env.append(event)
        assert len(env.events) == 1
        assert env.final_status == ExecutionTraceStatus.SUCCESS.value

    def test_append_pending_does_not_overwrite_existing_final_status(self):
        env = ExecutionTraceEnvelope()
        env.final_status = ExecutionTraceStatus.BLOCKED.value
        pending_event = ExecutionTraceEvent(
            trace_id=env.trace_id,
            stage=ExecutionTraceStage.READINESS_EVALUATED.value,
            status=ExecutionTraceStatus.PENDING.value,
        )
        env.append(pending_event)
        # final_status should remain blocked (pending doesn't overwrite)
        assert env.final_status == ExecutionTraceStatus.BLOCKED.value

    def test_append_skipped_does_not_overwrite_existing_final_status(self):
        env = ExecutionTraceEnvelope()
        env.final_status = ExecutionTraceStatus.SUCCESS.value
        skipped_event = ExecutionTraceEvent(
            trace_id=env.trace_id,
            stage=ExecutionTraceStage.FALLBACK_SELECTED.value,
            status=ExecutionTraceStatus.SKIPPED.value,
        )
        env.append(skipped_event)
        assert env.final_status == ExecutionTraceStatus.SUCCESS.value

    def test_to_dict_round_trip(self):
        env = ExecutionTraceEnvelope(
            trace_id="trace-1",
            runtime_session_id="sess-1",
            intent_id="intent-1",
        )
        event = ExecutionTraceEvent(
            trace_id="trace-1",
            stage=ExecutionTraceStage.INTENT_CREATED.value,
            status=ExecutionTraceStatus.SUCCESS.value,
        )
        env.append(event)
        d = env.to_dict()
        assert d["trace_id"] == "trace-1"
        assert len(d["events"]) == 1
        assert d["events"][0]["stage"] == "intent_created"

    def test_to_json_serialisable(self):
        env = ExecutionTraceEnvelope()
        json_str = env.to_json()
        parsed = json.loads(json_str)
        assert "trace_id" in parsed

    def test_compact_summary_keys(self):
        env = ExecutionTraceEnvelope(trace_id="trace-1", intent_id="intent-1")
        event = ExecutionTraceEvent(trace_id="trace-1", stage="intent_created", status="success")
        env.append(event)
        summary = env.compact_summary()
        assert "trace_id" in summary
        assert "intent_id" in summary
        assert "final_status" in summary
        assert "stage_count" in summary
        assert "stages" in summary
        assert "intent_created" in summary["stages"]


# ---------------------------------------------------------------------------
# 5. from_execution_intent()
# ---------------------------------------------------------------------------


class TestFromExecutionIntent:
    def test_basic_extraction(self):
        profile = _make_intent_profile()
        event = from_execution_intent(profile)
        assert event.stage == ExecutionTraceStage.INTENT_CREATED.value
        assert event.intent_id == profile.intent_id
        assert event.runtime_session_id == profile.runtime_session_id
        assert event.action_level == profile.action_level
        assert event.runtime_domain == profile.runtime_domain
        assert event.target_ref == profile.target_ref

    def test_status_success_for_normal_profile(self):
        profile = _make_intent_profile(degrade_reason=None)
        event = from_execution_intent(profile)
        assert event.status == ExecutionTraceStatus.SUCCESS.value

    def test_status_degraded_when_degrade_reason_set(self):
        profile = _make_intent_profile(degrade_reason="policy_blocked")
        event = from_execution_intent(profile)
        assert event.status == ExecutionTraceStatus.DEGRADED.value
        assert event.reason == "policy_blocked"

    def test_shared_trace_id(self):
        profile = _make_intent_profile()
        tid = str(uuid.uuid4())
        event = from_execution_intent(profile, trace_id=tid)
        assert event.trace_id == tid

    def test_none_profile_returns_safe_default(self):
        event = from_execution_intent(None)
        assert event.stage == ExecutionTraceStage.INTENT_CREATED.value
        assert event.status in (
            ExecutionTraceStatus.PENDING.value,
            ExecutionTraceStatus.SUCCESS.value,
        )

    def test_garbage_profile_never_raises(self):
        event = from_execution_intent("not a profile")  # type: ignore[arg-type]
        assert isinstance(event, ExecutionTraceEvent)

    def test_details_include_intent_mode_and_confidence(self):
        profile = _make_intent_profile(intent_mode="direct", confidence=0.85)
        event = from_execution_intent(profile)
        assert event.details.get("intent_mode") == "direct"
        assert abs(event.details.get("confidence", 0) - 0.85) < 0.01


# ---------------------------------------------------------------------------
# 6. from_readiness_result()
# ---------------------------------------------------------------------------


class TestFromReadinessResult:
    def test_stage_is_readiness_evaluated(self):
        r = _make_readiness_result()
        event = from_readiness_result(r)
        assert event.stage == ExecutionTraceStage.READINESS_EVALUATED.value

    def test_status_success_when_ready(self):
        r = _make_readiness_result(ready=True, requires_confirmation=False)
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.SUCCESS.value

    def test_status_pending_when_confirmation_required(self):
        r = _make_readiness_result(
            ready=True,
            status="confirm_required",
            requires_confirmation=True,
        )
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.PENDING.value

    def test_status_blocked_when_not_ready(self):
        r = _make_readiness_result(
            ready=False,
            status="blocked",
            blocked_by="policy",
            reason="policy_denied",
        )
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.BLOCKED.value
        assert "blocked" in event.reason or event.reason is not None

    def test_status_skipped_for_observe_only(self):
        r = _make_readiness_result(
            ready=False,
            status="observe_only",
            blocked_by="action_level",
        )
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.SKIPPED.value

    def test_none_result_returns_skipped(self):
        event = from_readiness_result(None)
        assert event.stage == ExecutionTraceStage.READINESS_EVALUATED.value
        assert event.status == ExecutionTraceStatus.SKIPPED.value

    def test_blocked_by_propagated_to_details(self):
        r = _make_readiness_result(
            ready=False,
            status="blocked",
            blocked_by="missing_target",
        )
        event = from_readiness_result(r)
        assert event.details.get("blocked_by") == "missing_target"

    def test_garbage_never_raises(self):
        event = from_readiness_result(42)  # type: ignore[arg-type]
        assert isinstance(event, ExecutionTraceEvent)

    def test_intent_profile_supplements_fields(self):
        profile = _make_intent_profile(action_level="execute", runtime_domain="local")
        r = _make_readiness_result()
        event = from_readiness_result(r, intent_profile=profile)
        # Should use profile's target_ref since readiness_result doesn't have it
        assert event.target_ref == profile.target_ref


# ---------------------------------------------------------------------------
# 7. from_fallback_trace()
# ---------------------------------------------------------------------------


class TestFromFallbackTrace:
    def test_stage_is_fallback_selected(self):
        ft = _make_fallback_trace()
        event = from_fallback_trace(ft)
        assert event.stage == ExecutionTraceStage.FALLBACK_SELECTED.value

    def test_outcome_selected_maps_to_success(self):
        ft = _make_fallback_trace(outcome="selected")
        event = from_fallback_trace(ft)
        assert event.status == ExecutionTraceStatus.SUCCESS.value

    def test_outcome_blocked_maps_to_blocked(self):
        ft = _make_fallback_trace(outcome="blocked", primary_block_reason="policy_denied")
        event = from_fallback_trace(ft)
        assert event.status == ExecutionTraceStatus.BLOCKED.value

    def test_outcome_noop_maps_to_skipped(self):
        ft = _make_fallback_trace(outcome="noop")
        event = from_fallback_trace(ft)
        assert event.status == ExecutionTraceStatus.SKIPPED.value

    def test_outcome_degraded_maps_to_degraded(self):
        ft = _make_fallback_trace(outcome="degraded")
        event = from_fallback_trace(ft)
        assert event.status == ExecutionTraceStatus.DEGRADED.value

    def test_outcome_failed_maps_to_failed(self):
        ft = _make_fallback_trace(outcome="failed")
        event = from_fallback_trace(ft)
        assert event.status == ExecutionTraceStatus.FAILED.value

    def test_none_trace_returns_skipped(self):
        event = from_fallback_trace(None)
        assert event.stage == ExecutionTraceStage.FALLBACK_SELECTED.value
        assert event.status == ExecutionTraceStatus.SKIPPED.value

    def test_fallback_path_in_details(self):
        ft = _make_fallback_trace(fallback_path="local_fallback", outcome="selected")
        event = from_fallback_trace(ft)
        assert event.details.get("fallback_path") == "local_fallback"

    def test_decision_source_in_details(self):
        ft = _make_fallback_trace(decision_source="readiness_gate")
        event = from_fallback_trace(ft)
        assert event.details.get("decision_source") == "readiness_gate"

    def test_garbage_never_raises(self):
        event = from_fallback_trace(object())
        assert isinstance(event, ExecutionTraceEvent)


# ---------------------------------------------------------------------------
# 8. from_execution_result()
# ---------------------------------------------------------------------------


class TestFromExecutionResult:
    def test_action_error_is_blocked_failed(self):
        result = _make_exec_result(action_taken="error", success=False, skipped_reason="internal_error: boom")
        event = from_execution_result(result)
        assert event.stage == ExecutionTraceStage.EXECUTION_BLOCKED.value
        assert event.status == ExecutionTraceStatus.FAILED.value
        assert event.reason == "internal_error: boom"

    def test_action_none_success_false_is_blocked(self):
        result = _make_exec_result(action_taken="none", success=False, skipped_reason="executor_unavailable")
        event = from_execution_result(result)
        assert event.stage == ExecutionTraceStage.EXECUTION_BLOCKED.value
        assert event.status == ExecutionTraceStatus.BLOCKED.value

    def test_action_none_success_true_is_skipped(self):
        result = _make_exec_result(action_taken="none", success=True)
        event = from_execution_result(result)
        assert event.stage == ExecutionTraceStage.EXECUTION_FINISHED.value
        assert event.status == ExecutionTraceStatus.SKIPPED.value

    def test_real_action_success_is_finished_success(self):
        result = _make_exec_result(action_taken="click", success=True)
        event = from_execution_result(result)
        assert event.stage == ExecutionTraceStage.EXECUTION_FINISHED.value
        assert event.status == ExecutionTraceStatus.SUCCESS.value

    def test_real_action_failure_is_finished_failed(self):
        result = _make_exec_result(action_taken="type", success=False, skipped_reason="typing_failed")
        event = from_execution_result(result)
        assert event.stage == ExecutionTraceStage.EXECUTION_FINISHED.value
        assert event.status == ExecutionTraceStatus.FAILED.value

    def test_target_extracted_to_target_ref(self):
        result = _make_exec_result(action_taken="click", success=True, target="notepad.exe")
        event = from_execution_result(result)
        assert event.target_ref == "notepad.exe"

    def test_none_result_returns_blocked(self):
        event = from_execution_result(None)
        assert event.stage == ExecutionTraceStage.EXECUTION_BLOCKED.value
        assert event.status == ExecutionTraceStatus.BLOCKED.value

    def test_garbage_never_raises(self):
        event = from_execution_result("not a dict")  # type: ignore[arg-type]
        assert isinstance(event, ExecutionTraceEvent)

    def test_intent_profile_supplements_fields(self):
        profile = _make_intent_profile(action_level="execute", runtime_session_id="sess-123")
        result = _make_exec_result(action_taken="click", success=True)
        event = from_execution_result(result, intent_profile=profile)
        assert event.runtime_session_id == "sess-123"
        assert event.action_level == "execute"

    def test_action_taken_in_details(self):
        result = _make_exec_result(action_taken="launch", success=True)
        event = from_execution_result(result)
        assert event.details.get("action_taken") == "launch"


# ---------------------------------------------------------------------------
# 9. build_trace_envelope()
# ---------------------------------------------------------------------------


class TestBuildTraceEnvelope:
    def test_all_stages_produce_events(self):
        profile = _make_intent_profile()
        readiness = _make_readiness_result()
        fallback = _make_fallback_trace()
        result = _make_exec_result(action_taken="click", success=True)

        envelope = build_trace_envelope(
            intent_profile=profile,
            readiness_result=readiness,
            fallback_trace=fallback,
            execution_result=result,
        )
        stages = [e.stage for e in envelope.events]
        assert ExecutionTraceStage.INTENT_CREATED.value in stages
        assert ExecutionTraceStage.READINESS_EVALUATED.value in stages
        assert ExecutionTraceStage.FALLBACK_SELECTED.value in stages
        # execution_finished or execution_blocked
        assert any(
            s in (
                ExecutionTraceStage.EXECUTION_FINISHED.value,
                ExecutionTraceStage.EXECUTION_BLOCKED.value,
            )
            for s in stages
        )

    def test_all_events_share_trace_id(self):
        profile = _make_intent_profile()
        readiness = _make_readiness_result()
        fallback = _make_fallback_trace()
        result = _make_exec_result()

        envelope = build_trace_envelope(
            intent_profile=profile,
            readiness_result=readiness,
            fallback_trace=fallback,
            execution_result=result,
        )
        trace_ids = {e.trace_id for e in envelope.events}
        assert len(trace_ids) == 1
        assert envelope.trace_id in trace_ids

    def test_final_status_reflects_last_substantive_event(self):
        profile = _make_intent_profile()
        readiness = _make_readiness_result(ready=True)
        result = _make_exec_result(action_taken="click", success=True)

        envelope = build_trace_envelope(
            intent_profile=profile,
            readiness_result=readiness,
            execution_result=result,
        )
        assert envelope.final_status == ExecutionTraceStatus.SUCCESS.value

    def test_blocked_lifecycle_final_status_blocked(self):
        profile = _make_intent_profile()
        readiness = _make_readiness_result(
            ready=False, status="blocked", blocked_by="policy"
        )
        result = _make_exec_result(action_taken="none", success=False, skipped_reason="readiness_gate:blocked:policy")

        envelope = build_trace_envelope(
            intent_profile=profile,
            readiness_result=readiness,
            execution_result=result,
        )
        assert envelope.final_status in (
            ExecutionTraceStatus.BLOCKED.value,
            ExecutionTraceStatus.SKIPPED.value,
            ExecutionTraceStatus.FAILED.value,
        )

    def test_all_none_inputs_never_raises(self):
        envelope = build_trace_envelope()
        assert isinstance(envelope, ExecutionTraceEnvelope)

    def test_partial_inputs_never_raises(self):
        profile = _make_intent_profile()
        envelope = build_trace_envelope(intent_profile=profile)
        assert isinstance(envelope, ExecutionTraceEnvelope)

    def test_compact_summary_keys_present(self):
        profile = _make_intent_profile()
        envelope = build_trace_envelope(intent_profile=profile)
        summary = envelope.compact_summary()
        assert "trace_id" in summary
        assert "final_status" in summary
        assert "stage_count" in summary
        assert "stages" in summary

    def test_explicit_trace_id_propagated(self):
        tid = str(uuid.uuid4())
        profile = _make_intent_profile()
        envelope = build_trace_envelope(intent_profile=profile, trace_id=tid)
        assert envelope.trace_id == tid
        for event in envelope.events:
            assert event.trace_id == tid

    def test_to_json_serialisable(self):
        profile = _make_intent_profile()
        readiness = _make_readiness_result()
        result = _make_exec_result()

        envelope = build_trace_envelope(
            intent_profile=profile,
            readiness_result=readiness,
            execution_result=result,
        )
        json_str = envelope.to_json()
        parsed = json.loads(json_str)
        assert "trace_id" in parsed
        assert "events" in parsed


# ---------------------------------------------------------------------------
# 10. Integration with PR-22 ExecutionIntentProfile
# ---------------------------------------------------------------------------


class TestIntegrationPR22:
    def test_intent_id_propagated(self):
        profile = _make_intent_profile()
        event = from_execution_intent(profile)
        assert event.intent_id == profile.intent_id

    def test_runtime_session_id_propagated(self):
        profile = _make_intent_profile(runtime_session_id="sess-xyz")
        event = from_execution_intent(profile)
        assert event.runtime_session_id == "sess-xyz"

    def test_action_level_propagated(self):
        profile = _make_intent_profile(action_level="assist")
        event = from_execution_intent(profile)
        assert event.action_level == "assist"


# ---------------------------------------------------------------------------
# 11. Integration with PR-23 ReadinessResult
# ---------------------------------------------------------------------------


class TestIntegrationPR23:
    def test_blocked_by_missing_target_yields_blocked_event(self):
        r = _make_readiness_result(
            ready=False,
            status="blocked",
            blocked_by="missing_target",
            reason="no execution target resolved",
        )
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.BLOCKED.value
        assert event.details.get("blocked_by") == "missing_target"

    def test_blocked_by_policy_yields_blocked_event(self):
        r = _make_readiness_result(ready=False, status="blocked", blocked_by="policy")
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.BLOCKED.value
        assert event.details.get("blocked_by") == "policy"

    def test_blocked_by_hitl_yields_blocked_event(self):
        r = _make_readiness_result(ready=False, status="blocked", blocked_by="hitl")
        event = from_readiness_result(r)
        assert event.status == ExecutionTraceStatus.BLOCKED.value

    def test_reason_propagated(self):
        r = _make_readiness_result(ready=False, status="blocked", reason="domain_mismatch")
        event = from_readiness_result(r)
        assert event.reason == "domain_mismatch"


# ---------------------------------------------------------------------------
# 12. Integration with PR-24 FallbackDecisionTrace
# ---------------------------------------------------------------------------


class TestIntegrationPR24:
    def test_fallback_path_propagated(self):
        ft = _make_fallback_trace(fallback_path="system_api_fallback", outcome="selected")
        event = from_fallback_trace(ft)
        assert event.details.get("fallback_path") == "system_api_fallback"

    def test_decision_source_propagated(self):
        ft = _make_fallback_trace(decision_source="executor", outcome="degraded")
        event = from_fallback_trace(ft)
        assert event.details.get("decision_source") == "executor"

    def test_primary_block_reason_propagated_to_reason(self):
        ft = _make_fallback_trace(
            outcome="blocked",
            primary_block_reason="uia_unavailable",
        )
        event = from_fallback_trace(ft)
        assert event.reason == "uia_unavailable"


# ---------------------------------------------------------------------------
# 13. OpenClawd._build_execution_trace() integration
# ---------------------------------------------------------------------------


class TestOpenClawdIntegration:
    def _make_openclawd(self) -> Any:
        """Return an OpenClawd-like object with the real _build_execution_trace method."""
        try:
            from core.openclawd import OpenClawd  # noqa: PLC0415
            return OpenClawd.__new__(OpenClawd)
        except Exception:
            pytest.skip("OpenClawd not importable in test context")

    def test_build_execution_trace_returns_dict(self):
        oc = self._make_openclawd()
        profile = _make_intent_profile()
        readiness = _make_readiness_result()
        result = _make_exec_result(action_taken="click", success=True)
        out = oc._build_execution_trace(profile, readiness, result)
        assert isinstance(out, dict)
        assert "trace_id" in out
        assert "final_status" in out
        assert "stage_count" in out

    def test_build_execution_trace_never_raises_on_bad_module(self):
        oc = self._make_openclawd()
        with patch("contracts.execution_trace.build_trace_envelope", side_effect=RuntimeError("boom")):
            result = oc._build_execution_trace(None, None, None)
            assert result is None

    def test_run_execution_result_contains_execution_trace_key(self):
        """Verify that _run_execution attaches 'execution_trace' to its return dict."""
        try:
            from core.openclawd import OpenClawd  # noqa: PLC0415
        except Exception:
            pytest.skip("OpenClawd not importable")

        oc = OpenClawd.__new__(OpenClawd)

        # Stub out dependencies
        oc._build_intent_profile = MagicMock(return_value=_make_intent_profile())
        oc._check_readiness = MagicMock(return_value=None)
        oc._get_decision_executor = MagicMock(return_value=None)  # executor_unavailable path
        oc._build_fallback_trace = MagicMock(return_value={"outcome": "blocked"})

        result = oc._run_execution({"tri_state": "active"})

        # Verify key presence
        assert "execution_trace" in result

        # Verify trace content (not just key existence)
        trace = result["execution_trace"]
        assert trace is not None
        assert isinstance(trace, dict)
        assert "trace_id" in trace
        assert "final_status" in trace
        assert "stage_count" in trace
        assert "stages" in trace
        assert isinstance(trace["stages"], list)
        # The executor-unavailable path should produce at least the intent stage
        assert trace["stage_count"] >= 1
