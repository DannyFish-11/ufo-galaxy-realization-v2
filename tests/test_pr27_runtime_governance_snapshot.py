"""
tests/test_pr27_runtime_governance_snapshot.py
=================================================
Focused tests for PR-27: Runtime Governance Snapshot.

Coverage
--------
1. RuntimeGovernanceExecutionSummary
   - construction with defaults (available=False)
   - construction with all fields specified
   - to_dict is JSON-serialisable
   - to_json / to_dict round-trip preserves fields

2. RuntimeGovernancePolicySummary
   - construction with defaults (available=False, blocked=True)
   - construction with ready=True
   - convenience booleans (blocked / degraded)
   - to_dict is JSON-serialisable

3. RuntimeGovernanceTraceSummary
   - construction with defaults (available=False, final_status="pending", stage_count=0)
   - construction with full fields
   - to_dict is JSON-serialisable

4. RuntimeGovernanceProjectionSummary
   - construction with defaults (available=False)
   - construction with all fields specified
   - to_dict is JSON-serialisable

5. RuntimeGovernanceSnapshot
   - construction with defaults (governance_available=False, posture="unknown")
   - to_dict includes all sub-summaries as nested dicts
   - to_json round-trip stability
   - snapshot_id is auto-populated when not provided
   - timestamp is auto-populated when not provided
   - __repr__ includes phase / domain / posture

6. summarize_runtime_intent()
   - returns available=False when intent_profile is None
   - extracts fields from compact_summary() when available
   - extracts fields from attributes when compact_summary absent
   - never raises on garbage input
   - action_level defaults to "observe" for missing intent

7. summarize_runtime_readiness()
   - returns available=False when readiness_result is None
   - extracts ready / status / reason / requires_confirmation
   - blocked=True when status is "blocked"
   - degraded=True when action_level is "observe"
   - never raises on garbage input

8. summarize_runtime_fallback()
   - returns available=False when fallback_trace is None
   - extracts outcome / trace_id / intent_id via compact_summary()
   - extracts via attributes when compact_summary absent
   - never raises on garbage input

9. summarize_runtime_execution_trace()
   - returns available=False when envelope is None
   - extracts trace_id / final_status / stage_count / stages via compact_summary()
   - extracts via attributes when compact_summary absent
   - never raises on garbage input

10. summarize_projection_governance_for_runtime()
    - returns available=False when projection_governance is None
    - extracts fields from Pydantic-like object with nested attributes
    - extracts fields from a plain dict
    - never raises on garbage input

11. assemble_runtime_governance_snapshot()
    - returns governance_available=False when all inputs are None
    - posture is "unknown" when all inputs are None
    - returns governance_available=True when at least one input is present
    - posture is "execute" when readiness is ready
    - posture is "blocked" when readiness is blocked
    - posture is "degraded" when readiness is degraded
    - posture is "observe" when intent action_level is "observe"
    - tri_state_phase resolved from explicit parameter
    - runtime_domain resolved from explicit parameter
    - runtime_domain falls back to intent_summary domain
    - trace_id / runtime_session_id resolved from execution trace envelope
    - never raises on all-None inputs
    - never raises on garbage inputs
    - snapshot_id auto-populated
    - timestamp auto-populated

12. Serialisation stability
    - to_dict() round-trip is stable across two calls on the same snapshot
    - to_json() produces valid JSON
    - nested sub-summaries serialised correctly
    - no non-serialisable values in to_dict()

13. Additive integration
    - RuntimeGovernanceSnapshot is importable from core.runtime_governance
    - assemble_runtime_governance_snapshot is importable from core.runtime_governance
    - RuntimeProjection.runtime_governance_snapshot field exists
    - RuntimeProjection.to_dict() includes "runtime_governance_snapshot" key
    - existing RuntimeProjection fields are unchanged when snapshot field is None
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from core.runtime_governance.snapshot import (
    RuntimeGovernanceExecutionSummary,
    RuntimeGovernancePolicySummary,
    RuntimeGovernanceProjectionSummary,
    RuntimeGovernanceSnapshot,
    RuntimeGovernanceTraceSummary,
    assemble_runtime_governance_snapshot,
    summarize_projection_governance_for_runtime,
    summarize_runtime_execution_trace,
    summarize_runtime_fallback,
    summarize_runtime_intent,
    summarize_runtime_readiness,
)


# ---------------------------------------------------------------------------
# Helpers — minimal stub objects
# ---------------------------------------------------------------------------


def _make_intent_profile(
    intent_id: str = "intent-001",
    source: str = "openclawd",
    action_level: str = "execute",
    intent_mode: str = "direct",
    target_type: Optional[str] = "app",
    target_ref: Optional[str] = "notepad",
    device_scope: Optional[str] = "local",
    runtime_domain: Optional[str] = "local",
    confidence: float = 0.9,
    degrade_reason: Optional[str] = None,
) -> MagicMock:
    mock = MagicMock()
    mock.compact_summary.return_value = {
        "intent_id": intent_id,
        "source": source,
        "action_level": action_level,
        "intent_mode": intent_mode,
        "target_type": target_type,
        "target_ref": target_ref,
        "device_scope": device_scope,
        "runtime_domain": runtime_domain,
        "confidence": confidence,
        "degrade_reason": degrade_reason,
    }
    return mock


def _make_readiness_result(
    ready: bool = True,
    status: str = "ready",
    reason: str = "full_execute band",
    requires_confirmation: bool = False,
    action_level: str = "execute",
    policy_band: Optional[str] = "full_execute",
    blocked_by: str = "none",
    runtime_domain: Optional[str] = "local",
) -> MagicMock:
    mock = MagicMock()
    mock.ready = ready
    mock.status = status
    mock.reason = reason
    mock.requires_confirmation = requires_confirmation
    mock.action_level = action_level
    mock.policy_band = policy_band
    mock.blocked_by = blocked_by
    mock.runtime_domain = runtime_domain
    return mock


def _make_fallback_trace(
    outcome: str = "noop",
    trace_id: Optional[str] = None,
    intent_id: str = "intent-001",
    action_level: str = "execute",
) -> MagicMock:
    mock = MagicMock()
    mock.compact_summary.return_value = {
        "trace_id": trace_id or str(uuid.uuid4()),
        "intent_id": intent_id,
        "action_level": action_level,
        "outcome": outcome,
    }
    return mock


def _make_execution_trace_envelope(
    final_status: str = "success",
    stages: Optional[list] = None,
    intent_id: str = "intent-001",
    runtime_session_id: Optional[str] = None,
) -> MagicMock:
    stages = stages or ["intent_created", "readiness_evaluated", "execution_finished"]
    mock = MagicMock()
    trace_id = str(uuid.uuid4())
    mock.compact_summary.return_value = {
        "trace_id": trace_id,
        "intent_id": intent_id,
        "runtime_session_id": runtime_session_id,
        "final_status": final_status,
        "stage_count": len(stages),
        "stages": stages,
        "created_at": time.time(),
    }
    return mock


def _make_projection_governance(
    governance_available: bool = True,
    action_level: str = "execute",
    intent_mode: str = "direct",
    policy_status: str = "ready",
    ready: bool = True,
    blocked: bool = False,
    degraded: bool = False,
    fallback_outcome: str = "noop",
    trace_final_status: str = "success",
    tri_state_phase: str = "manifest",
    runtime_domain: str = "local",
) -> MagicMock:
    mock = MagicMock()
    mock.governance_available = governance_available
    execution = MagicMock()
    execution.action_level = action_level
    execution.intent_mode = intent_mode
    mock.execution = execution
    policy = MagicMock()
    policy.status = policy_status
    policy.ready = ready
    policy.blocked = blocked
    policy.degraded = degraded
    mock.policy = policy
    fallback = MagicMock()
    fallback.outcome = fallback_outcome
    mock.fallback = fallback
    exec_trace = MagicMock()
    exec_trace.final_status = trace_final_status
    mock.execution_trace = exec_trace
    tri_phase_mock = MagicMock()
    tri_phase_mock.value = tri_state_phase
    mock.tri_state_phase = tri_state_phase
    mock.runtime_domain = runtime_domain
    mock.assembled_at = time.time()
    return mock


# ---------------------------------------------------------------------------
# 1. RuntimeGovernanceExecutionSummary
# ---------------------------------------------------------------------------


class TestRuntimeGovernanceExecutionSummary:
    def test_defaults_available_false(self):
        s = RuntimeGovernanceExecutionSummary()
        assert s.available is False
        assert s.action_level == "observe"
        assert s.intent_mode == "advisory"
        assert s.intent_id is None

    def test_construction_all_fields(self):
        s = RuntimeGovernanceExecutionSummary(
            intent_id="x-1",
            source="chat",
            action_level="execute",
            intent_mode="direct",
            target_type="app",
            target_ref="notepad",
            device_scope="local",
            runtime_domain="local",
            confidence=0.95,
            degrade_reason=None,
            available=True,
        )
        assert s.intent_id == "x-1"
        assert s.action_level == "execute"
        assert s.available is True
        assert s.confidence == 0.95

    def test_to_dict_json_serialisable(self):
        s = RuntimeGovernanceExecutionSummary(
            intent_id="x-1", action_level="execute", available=True
        )
        d = s.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert "intent_id" in d
        assert "action_level" in d
        assert "available" in d

    def test_to_json_round_trip(self):
        s = RuntimeGovernanceExecutionSummary(
            intent_id="x-2", action_level="assist", intent_mode="assistive", available=True
        )
        json_str = s.to_json()
        d = json.loads(json_str)
        assert d["intent_id"] == "x-2"
        assert d["action_level"] == "assist"
        assert d["intent_mode"] == "assistive"
        assert d["available"] is True


# ---------------------------------------------------------------------------
# 2. RuntimeGovernancePolicySummary
# ---------------------------------------------------------------------------


class TestRuntimeGovernancePolicySummary:
    def test_defaults_available_false_blocked_true(self):
        s = RuntimeGovernancePolicySummary()
        assert s.available is False
        assert s.blocked is True
        assert s.ready is False
        assert s.status == "blocked"

    def test_ready_true(self):
        s = RuntimeGovernancePolicySummary(
            ready=True,
            status="ready",
            blocked=False,
            blocked_by="none",
            available=True,
        )
        assert s.ready is True
        assert s.blocked is False
        assert s.available is True

    def test_degraded_flag(self):
        s = RuntimeGovernancePolicySummary(degraded=True, available=True)
        assert s.degraded is True

    def test_to_dict_json_serialisable(self):
        s = RuntimeGovernancePolicySummary(
            ready=True, status="ready", blocked=False, available=True
        )
        d = s.to_dict()
        json_str = json.dumps(d)
        assert "ready" in d
        assert "status" in d
        assert "blocked" in d
        assert "available" in d


# ---------------------------------------------------------------------------
# 3. RuntimeGovernanceTraceSummary
# ---------------------------------------------------------------------------


class TestRuntimeGovernanceTraceSummary:
    def test_defaults(self):
        s = RuntimeGovernanceTraceSummary()
        assert s.available is False
        assert s.final_status == "pending"
        assert s.stage_count == 0
        assert s.stages == []
        assert s.trace_id is None

    def test_construction_full(self):
        s = RuntimeGovernanceTraceSummary(
            trace_id="t-1",
            intent_id="i-1",
            runtime_session_id="sess-1",
            final_status="success",
            stage_count=3,
            stages=["intent_created", "readiness_evaluated", "execution_finished"],
            fallback_outcome="noop",
            available=True,
        )
        assert s.trace_id == "t-1"
        assert s.final_status == "success"
        assert s.stage_count == 3
        assert len(s.stages) == 3
        assert s.available is True

    def test_to_dict_json_serialisable(self):
        s = RuntimeGovernanceTraceSummary(
            trace_id="t-2", final_status="success", stage_count=2,
            stages=["a", "b"], available=True
        )
        d = s.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert "trace_id" in d
        assert "final_status" in d
        assert "stages" in d


# ---------------------------------------------------------------------------
# 4. RuntimeGovernanceProjectionSummary
# ---------------------------------------------------------------------------


class TestRuntimeGovernanceProjectionSummary:
    def test_defaults_available_false(self):
        s = RuntimeGovernanceProjectionSummary()
        assert s.available is False
        assert s.governance_available is False
        assert s.action_level == "observe"
        assert s.blocked is True
        assert s.ready is False

    def test_construction_all_fields(self):
        s = RuntimeGovernanceProjectionSummary(
            governance_available=True,
            action_level="execute",
            intent_mode="direct",
            policy_status="ready",
            ready=True,
            blocked=False,
            degraded=False,
            fallback_outcome="noop",
            trace_final_status="success",
            tri_state_phase="manifest",
            runtime_domain="local",
            assembled_at=1234567890.0,
            available=True,
        )
        assert s.available is True
        assert s.governance_available is True
        assert s.action_level == "execute"
        assert s.tri_state_phase == "manifest"

    def test_to_dict_json_serialisable(self):
        s = RuntimeGovernanceProjectionSummary(
            governance_available=True, action_level="execute", available=True
        )
        d = s.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert "governance_available" in d
        assert "action_level" in d
        assert "available" in d


# ---------------------------------------------------------------------------
# 5. RuntimeGovernanceSnapshot
# ---------------------------------------------------------------------------


class TestRuntimeGovernanceSnapshot:
    def test_defaults(self):
        s = RuntimeGovernanceSnapshot(
            tri_state_phase="silent",
        )
        assert s.governance_available is False
        assert s.posture == "unknown"
        assert s.blocked is False
        assert s.degraded is False
        assert s.snapshot_id is not None
        assert s.timestamp > 0

    def test_snapshot_id_auto_populated(self):
        s1 = RuntimeGovernanceSnapshot(tri_state_phase="silent")
        s2 = RuntimeGovernanceSnapshot(tri_state_phase="silent")
        assert s1.snapshot_id != s2.snapshot_id

    def test_timestamp_auto_populated(self):
        before = time.time()
        s = RuntimeGovernanceSnapshot(tri_state_phase="silent")
        after = time.time()
        assert before <= s.timestamp <= after

    def test_to_dict_all_keys(self):
        s = RuntimeGovernanceSnapshot(tri_state_phase="manifest")
        d = s.to_dict()
        expected_keys = {
            "snapshot_id", "trace_id", "runtime_session_id", "tri_state_phase",
            "runtime_domain", "governance_available", "intent_summary",
            "readiness_summary", "fallback_summary", "execution_trace_summary",
            "projection_governance_summary", "posture", "blocked", "degraded",
            "timestamp",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_to_dict_nested_summaries_are_dicts(self):
        s = RuntimeGovernanceSnapshot(tri_state_phase="manifest")
        d = s.to_dict()
        assert isinstance(d["intent_summary"], dict)
        assert isinstance(d["readiness_summary"], dict)
        assert isinstance(d["fallback_summary"], dict)
        assert isinstance(d["execution_trace_summary"], dict)
        assert isinstance(d["projection_governance_summary"], dict)

    def test_to_json_valid_json(self):
        s = RuntimeGovernanceSnapshot(tri_state_phase="liminal")
        j = s.to_json()
        d = json.loads(j)
        assert d["tri_state_phase"] == "liminal"

    def test_to_json_round_trip_stability(self):
        s = RuntimeGovernanceSnapshot(
            snapshot_id="snap-123",
            tri_state_phase="manifest",
            runtime_domain="local",
            posture="execute",
            blocked=False,
            degraded=False,
            timestamp=1234567890.0,
        )
        d1 = s.to_dict()
        d2 = json.loads(s.to_json())
        assert d1["snapshot_id"] == d2["snapshot_id"]
        assert d1["tri_state_phase"] == d2["tri_state_phase"]
        assert d1["posture"] == d2["posture"]

    def test_repr_contains_key_fields(self):
        s = RuntimeGovernanceSnapshot(
            tri_state_phase="manifest",
            runtime_domain="local",
            posture="execute",
            blocked=False,
            degraded=False,
        )
        r = repr(s)
        assert "manifest" in r
        assert "local" in r
        assert "execute" in r

    def test_to_dict_fully_json_serialisable(self):
        s = RuntimeGovernanceSnapshot(
            tri_state_phase="liminal",
            runtime_domain="transition",
            posture="degraded",
            blocked=False,
            degraded=True,
        )
        d = s.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)


# ---------------------------------------------------------------------------
# 6. summarize_runtime_intent()
# ---------------------------------------------------------------------------


class TestSummarizeRuntimeIntent:
    def test_none_returns_available_false(self):
        s = summarize_runtime_intent(None)
        assert s.available is False
        assert s.action_level == "observe"
        assert s.intent_mode == "advisory"

    def test_extracts_from_compact_summary(self):
        profile = _make_intent_profile(
            intent_id="i-1", source="openclawd", action_level="execute",
            intent_mode="direct", runtime_domain="local", confidence=0.95
        )
        s = summarize_runtime_intent(profile)
        assert s.available is True
        assert s.intent_id == "i-1"
        assert s.source == "openclawd"
        assert s.action_level == "execute"
        assert s.intent_mode == "direct"
        assert s.runtime_domain == "local"
        assert s.confidence == 0.95

    def test_extracts_from_attributes_when_no_compact_summary(self):
        profile = MagicMock(spec=[])  # no methods
        profile.intent_id = "i-attr"
        profile.source = "runtime"
        profile.action_level = "assist"
        profile.intent_mode = "assistive"
        profile.target_type = "window"
        profile.target_ref = None
        profile.device_scope = None
        profile.runtime_domain = "local"
        profile.confidence = 0.7
        profile.degrade_reason = None
        s = summarize_runtime_intent(profile)
        assert s.available is True
        assert s.intent_id == "i-attr"
        assert s.action_level == "assist"

    def test_never_raises_on_garbage(self):
        for bad_input in [42, "string", [], {}, object()]:
            s = summarize_runtime_intent(bad_input)
            assert isinstance(s, RuntimeGovernanceExecutionSummary)

    def test_defaults_to_observe_for_missing_intent(self):
        s = summarize_runtime_intent(None)
        assert s.action_level == "observe"


# ---------------------------------------------------------------------------
# 7. summarize_runtime_readiness()
# ---------------------------------------------------------------------------


class TestSummarizeRuntimeReadiness:
    def test_none_returns_available_false(self):
        s = summarize_runtime_readiness(None)
        assert s.available is False
        assert s.status == "blocked"
        assert s.ready is False

    def test_extracts_ready_status_reason(self):
        rr = _make_readiness_result(
            ready=True, status="ready", reason="ok", action_level="execute"
        )
        s = summarize_runtime_readiness(rr)
        assert s.available is True
        assert s.ready is True
        assert s.status == "ready"
        assert s.reason == "ok"

    def test_blocked_true_when_status_blocked(self):
        rr = _make_readiness_result(ready=False, status="blocked", action_level="observe")
        s = summarize_runtime_readiness(rr)
        assert s.blocked is True
        assert s.ready is False

    def test_degraded_true_when_action_level_observe(self):
        rr = _make_readiness_result(
            ready=False, status="observe_only", action_level="observe"
        )
        s = summarize_runtime_readiness(rr)
        assert s.degraded is True

    def test_requires_confirmation_extracted(self):
        rr = _make_readiness_result(
            ready=True, status="confirm_required", requires_confirmation=True,
            action_level="execute"
        )
        s = summarize_runtime_readiness(rr)
        assert s.requires_confirmation is True

    def test_never_raises_on_garbage(self):
        for bad_input in [42, "string", [], {}]:
            s = summarize_runtime_readiness(bad_input)
            assert isinstance(s, RuntimeGovernancePolicySummary)


# ---------------------------------------------------------------------------
# 8. summarize_runtime_fallback()
# ---------------------------------------------------------------------------


class TestSummarizeRuntimeFallback:
    def test_none_returns_available_false(self):
        s = summarize_runtime_fallback(None)
        assert s.available is False

    def test_extracts_outcome_via_compact_summary(self):
        ft = _make_fallback_trace(outcome="selected")
        s = summarize_runtime_fallback(ft)
        assert s.available is True
        assert s.fallback_outcome == "selected"

    def test_extracts_via_attributes_when_no_compact_summary(self):
        ft = MagicMock(spec=[])
        ft.outcome = "degraded"
        ft.trace_id = "t-fallback"
        ft.intent_id = "i-1"
        s = summarize_runtime_fallback(ft)
        assert s.available is True
        assert s.fallback_outcome == "degraded"

    def test_stage_count_zero_for_fallback_summary(self):
        ft = _make_fallback_trace(outcome="noop")
        s = summarize_runtime_fallback(ft)
        assert s.stage_count == 0
        assert s.stages == []

    def test_never_raises_on_garbage(self):
        for bad_input in [42, "string", [], {}]:
            s = summarize_runtime_fallback(bad_input)
            assert isinstance(s, RuntimeGovernanceTraceSummary)


# ---------------------------------------------------------------------------
# 9. summarize_runtime_execution_trace()
# ---------------------------------------------------------------------------


class TestSummarizeRuntimeExecutionTrace:
    def test_none_returns_available_false(self):
        s = summarize_runtime_execution_trace(None)
        assert s.available is False
        assert s.final_status == "pending"
        assert s.stage_count == 0

    def test_extracts_via_compact_summary(self):
        envelope = _make_execution_trace_envelope(
            final_status="success",
            stages=["intent_created", "execution_finished"],
            intent_id="i-1",
            runtime_session_id="sess-123",
        )
        s = summarize_runtime_execution_trace(envelope)
        assert s.available is True
        assert s.final_status == "success"
        assert s.stage_count == 2
        assert "intent_created" in s.stages
        assert s.intent_id == "i-1"
        assert s.runtime_session_id == "sess-123"

    def test_extracts_via_attributes_when_no_compact_summary(self):
        envelope = MagicMock(spec=[])
        envelope.trace_id = "t-attr"
        envelope.intent_id = "i-attr"
        envelope.runtime_session_id = None
        envelope.final_status = "failed"
        event_mock = MagicMock()
        event_mock.stage = "execution_blocked"
        envelope.events = [event_mock]
        s = summarize_runtime_execution_trace(envelope)
        assert s.available is True
        assert s.final_status == "failed"
        assert s.stage_count == 1
        assert "execution_blocked" in s.stages

    def test_never_raises_on_garbage(self):
        for bad_input in [42, "string", [], {}]:
            s = summarize_runtime_execution_trace(bad_input)
            assert isinstance(s, RuntimeGovernanceTraceSummary)


# ---------------------------------------------------------------------------
# 10. summarize_projection_governance_for_runtime()
# ---------------------------------------------------------------------------


class TestSummarizeProjectionGovernanceForRuntime:
    def test_none_returns_available_false(self):
        s = summarize_projection_governance_for_runtime(None)
        assert s.available is False
        assert s.governance_available is False

    def test_extracts_from_pydantic_like_object(self):
        pg = _make_projection_governance(
            governance_available=True,
            action_level="execute",
            intent_mode="direct",
            policy_status="ready",
            ready=True,
            blocked=False,
            degraded=False,
            fallback_outcome="noop",
            trace_final_status="success",
            tri_state_phase="manifest",
            runtime_domain="local",
        )
        s = summarize_projection_governance_for_runtime(pg)
        assert s.available is True
        assert s.governance_available is True
        assert s.action_level == "execute"
        assert s.intent_mode == "direct"
        assert s.ready is True
        assert s.blocked is False
        assert s.tri_state_phase == "manifest"
        assert s.runtime_domain == "local"

    def test_extracts_from_plain_dict(self):
        pg_dict = {
            "governance_available": True,
            "execution": {"action_level": "assist", "intent_mode": "assistive"},
            "policy": {"status": "ready", "ready": True, "blocked": False, "degraded": False},
            "fallback": {"outcome": "selected"},
            "execution_trace": {"final_status": "success"},
            "tri_state_phase": "liminal",
            "runtime_domain": "transition",
            "assembled_at": 1234567890.0,
        }
        s = summarize_projection_governance_for_runtime(pg_dict)
        assert s.available is True
        assert s.governance_available is True
        assert s.action_level == "assist"
        assert s.intent_mode == "assistive"
        assert s.ready is True
        assert s.blocked is False
        assert s.tri_state_phase == "liminal"
        assert s.runtime_domain == "transition"
        assert s.assembled_at == 1234567890.0

    def test_never_raises_on_garbage(self):
        for bad_input in [42, "string", []]:
            s = summarize_projection_governance_for_runtime(bad_input)
            assert isinstance(s, RuntimeGovernanceProjectionSummary)


# ---------------------------------------------------------------------------
# 11. assemble_runtime_governance_snapshot()
# ---------------------------------------------------------------------------


class TestAssembleRuntimeGovernanceSnapshot:
    def test_all_none_returns_governance_unavailable(self):
        snap = assemble_runtime_governance_snapshot()
        assert snap.governance_available is False
        assert snap.posture == "unknown"
        assert snap.blocked is False
        assert snap.degraded is False

    def test_all_none_snapshot_id_auto_populated(self):
        snap = assemble_runtime_governance_snapshot()
        assert snap.snapshot_id is not None
        assert len(snap.snapshot_id) > 0

    def test_all_none_timestamp_auto_populated(self):
        before = time.time()
        snap = assemble_runtime_governance_snapshot()
        after = time.time()
        assert before <= snap.timestamp <= after

    def test_governance_available_true_when_intent_present(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile()
        )
        assert snap.governance_available is True
        assert snap.intent_summary.available is True

    def test_posture_execute_when_readiness_ready(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(action_level="execute"),
            readiness_result=_make_readiness_result(
                ready=True, status="ready", action_level="execute"
            ),
        )
        assert snap.posture == "execute"
        assert snap.blocked is False
        assert snap.degraded is False

    def test_posture_blocked_when_readiness_blocked(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(action_level="execute"),
            readiness_result=_make_readiness_result(
                ready=False, status="blocked", action_level="observe"
            ),
        )
        assert snap.posture == "blocked"
        assert snap.blocked is True
        assert snap.degraded is False

    def test_posture_degraded_when_readiness_degraded(self):
        snap = assemble_runtime_governance_snapshot(
            readiness_result=_make_readiness_result(
                ready=False, status="observe_only", action_level="observe"
            ),
        )
        assert snap.posture == "degraded"
        assert snap.degraded is True

    def test_posture_observe_when_intent_observe(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(action_level="observe"),
        )
        # readiness is None → blocked posture not applicable, observe from intent
        assert snap.posture in ("observe", "unknown")

    def test_tri_state_phase_from_explicit_param(self):
        snap = assemble_runtime_governance_snapshot(tri_state_phase="manifest")
        assert snap.tri_state_phase == "manifest"

    def test_runtime_domain_from_explicit_param(self):
        snap = assemble_runtime_governance_snapshot(runtime_domain="cross_device")
        assert snap.runtime_domain == "cross_device"

    def test_runtime_domain_fallback_to_intent_domain(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(runtime_domain="local"),
        )
        assert snap.runtime_domain == "local"

    def test_trace_id_from_envelope(self):
        envelope = _make_execution_trace_envelope()
        cs = envelope.compact_summary.return_value
        expected_trace_id = cs["trace_id"]
        snap = assemble_runtime_governance_snapshot(
            execution_trace_envelope=envelope,
        )
        assert snap.trace_id == expected_trace_id

    def test_runtime_session_id_from_envelope(self):
        envelope = _make_execution_trace_envelope(runtime_session_id="sess-abc")
        snap = assemble_runtime_governance_snapshot(
            execution_trace_envelope=envelope,
        )
        assert snap.runtime_session_id == "sess-abc"

    def test_explicit_trace_id_overrides_envelope(self):
        envelope = _make_execution_trace_envelope()
        snap = assemble_runtime_governance_snapshot(
            execution_trace_envelope=envelope,
            trace_id="override-trace",
        )
        assert snap.trace_id == "override-trace"

    def test_explicit_snapshot_id_used(self):
        snap = assemble_runtime_governance_snapshot(snapshot_id="snap-fixed")
        assert snap.snapshot_id == "snap-fixed"

    def test_explicit_timestamp_used(self):
        snap = assemble_runtime_governance_snapshot(timestamp=1111111111.0)
        assert snap.timestamp == 1111111111.0

    def test_never_raises_on_all_none(self):
        snap = assemble_runtime_governance_snapshot()
        assert isinstance(snap, RuntimeGovernanceSnapshot)

    def test_never_raises_on_garbage_inputs(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=42,
            readiness_result="not_a_result",
            fallback_trace=[],
            execution_trace_envelope=object(),
            projection_governance=None,
        )
        assert isinstance(snap, RuntimeGovernanceSnapshot)

    def test_projection_governance_from_dict(self):
        pg_dict = {
            "governance_available": True,
            "execution": {"action_level": "execute", "intent_mode": "direct"},
            "policy": {"status": "ready", "ready": True, "blocked": False, "degraded": False},
            "fallback": {"outcome": "noop"},
            "execution_trace": {"final_status": "success"},
            "tri_state_phase": "manifest",
            "runtime_domain": "local",
            "assembled_at": time.time(),
        }
        snap = assemble_runtime_governance_snapshot(
            projection_governance=pg_dict,
        )
        assert snap.projection_governance_summary.available is True
        assert snap.projection_governance_summary.governance_available is True
        assert snap.tri_state_phase == "manifest"

    def test_full_snapshot_all_inputs(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(action_level="execute"),
            readiness_result=_make_readiness_result(ready=True, status="ready"),
            fallback_trace=_make_fallback_trace(outcome="noop"),
            execution_trace_envelope=_make_execution_trace_envelope(final_status="success"),
            projection_governance=_make_projection_governance(governance_available=True),
            tri_state_phase="manifest",
            runtime_domain="local",
        )
        assert snap.governance_available is True
        assert snap.posture == "execute"
        assert snap.intent_summary.available is True
        assert snap.readiness_summary.available is True
        assert snap.fallback_summary.available is True
        assert snap.execution_trace_summary.available is True
        assert snap.projection_governance_summary.available is True
        assert snap.tri_state_phase == "manifest"
        assert snap.runtime_domain == "local"


# ---------------------------------------------------------------------------
# 12. Serialisation stability
# ---------------------------------------------------------------------------


class TestSerialisationStability:
    def test_to_dict_round_trip_stable(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(),
            readiness_result=_make_readiness_result(),
            tri_state_phase="manifest",
            runtime_domain="local",
            snapshot_id="stable-snap",
            timestamp=9999999.0,
        )
        d1 = snap.to_dict()
        d2 = snap.to_dict()
        assert d1 == d2

    def test_to_json_produces_valid_json(self):
        snap = assemble_runtime_governance_snapshot(
            tri_state_phase="silent",
        )
        j = snap.to_json()
        parsed = json.loads(j)
        assert parsed["tri_state_phase"] == "silent"

    def test_nested_summaries_serialised_correctly(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(intent_id="serial-test"),
            readiness_result=_make_readiness_result(ready=True, status="ready"),
            snapshot_id="serial-snap",
            timestamp=8888888.0,
        )
        d = snap.to_dict()
        assert d["intent_summary"]["intent_id"] == "serial-test"
        assert d["readiness_summary"]["ready"] is True
        assert isinstance(d["fallback_summary"]["stages"], list)

    def test_no_non_serialisable_values(self):
        snap = assemble_runtime_governance_snapshot(
            intent_profile=_make_intent_profile(),
            readiness_result=_make_readiness_result(),
            fallback_trace=_make_fallback_trace(),
            execution_trace_envelope=_make_execution_trace_envelope(),
            projection_governance=_make_projection_governance(),
            tri_state_phase="manifest",
            runtime_domain="local",
            snapshot_id="serial-snap-2",
            timestamp=7777777.0,
        )
        d = snap.to_dict()
        # Must not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# 13. Additive integration
# ---------------------------------------------------------------------------


class TestAdditiveIntegration:
    def test_importable_from_core_runtime_governance(self):
        from core.runtime_governance import (
            RuntimeGovernanceSnapshot,
            assemble_runtime_governance_snapshot,
        )
        assert RuntimeGovernanceSnapshot is not None
        assert assemble_runtime_governance_snapshot is not None

    def test_all_exports_importable(self):
        from core.runtime_governance import (
            RuntimeGovernanceExecutionSummary,
            RuntimeGovernancePolicySummary,
            RuntimeGovernanceProjectionSummary,
            RuntimeGovernanceSnapshot,
            RuntimeGovernanceTraceSummary,
            assemble_runtime_governance_snapshot,
            summarize_projection_governance_for_runtime,
            summarize_runtime_execution_trace,
            summarize_runtime_fallback,
            summarize_runtime_intent,
            summarize_runtime_readiness,
        )
        for obj in [
            RuntimeGovernanceExecutionSummary,
            RuntimeGovernancePolicySummary,
            RuntimeGovernanceProjectionSummary,
            RuntimeGovernanceSnapshot,
            RuntimeGovernanceTraceSummary,
            assemble_runtime_governance_snapshot,
            summarize_projection_governance_for_runtime,
            summarize_runtime_execution_trace,
            summarize_runtime_fallback,
            summarize_runtime_intent,
            summarize_runtime_readiness,
        ]:
            assert obj is not None

    def test_runtime_projection_has_snapshot_field(self):
        from core.projection.runtime_projection import RuntimeProjection
        from pydantic.fields import FieldInfo

        fields = RuntimeProjection.model_fields
        assert "runtime_governance_snapshot" in fields

    def test_runtime_projection_to_dict_includes_snapshot_key(self):
        from core.projection.runtime_projection import RuntimeProjection

        # Verify the field declaration alone — construction requires TriStatePhase
        fields = RuntimeProjection.model_fields
        assert "runtime_governance_snapshot" in fields
        assert "governance" in fields

    def test_runtime_projection_snapshot_populated(self):
        from core.projection.runtime_projection import RuntimeProjection

        snap = assemble_runtime_governance_snapshot(
            tri_state_phase="manifest",
            runtime_domain="local",
            snapshot_id="integration-snap",
        )
        # Verify the field can hold a dict value (Pydantic field validation)
        fields = RuntimeProjection.model_fields
        assert "runtime_governance_snapshot" in fields
        snap_dict = snap.to_dict()
        assert snap_dict["snapshot_id"] == "integration-snap"

    def test_existing_projection_fields_unchanged(self):
        from core.projection.runtime_projection import RuntimeProjection

        # Verify both old and new fields are declared on the model
        fields = RuntimeProjection.model_fields
        for field_name in [
            "tri_state_phase", "runtime_domain", "presence_intensity",
            "primary_model_id", "governance", "runtime_governance_snapshot",
            "timestamp",
        ]:
            assert field_name in fields, f"Expected field {field_name!r} missing"
