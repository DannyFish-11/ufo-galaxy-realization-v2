"""
tests/test_pr26_projection_assembly_governance.py
====================================================
Focused tests for PR-26: Projection Assembly Governance.

Coverage
--------
1. ProjectionExecutionSummary
   - construction with defaults (available=False)
   - construction with all fields specified
   - to_dict is JSON-serialisable
   - to_json / to_dict round-trip preserves fields

2. ProjectionPolicySummary
   - construction with defaults (available=False, blocked=True)
   - construction with ready=True
   - convenience booleans (blocked / degraded)
   - to_dict is JSON-serialisable

3. ProjectionTraceSummary
   - construction with defaults (available=False, outcome="noop")
   - construction with full fields
   - to_dict is JSON-serialisable

4. ProjectionExecutionTraceSummary
   - construction with defaults (available=False, final_status="pending", stage_count=0)
   - construction with full fields
   - to_dict is JSON-serialisable

5. ProjectionGovernanceSummary
   - construction with defaults (governance_available=False)
   - to_dict includes all sub-summaries as nested dicts
   - to_json round-trip stability
   - assembled_at is auto-populated when not provided

6. summarize_intent_for_projection()
   - returns available=False when intent_profile is None
   - extracts fields from compact_summary() when available
   - extracts fields from attributes when compact_summary absent
   - never raises on garbage input
   - action_level defaults to "observe" for missing intent

7. summarize_readiness_for_projection()
   - returns available=False when readiness_result is None
   - extracts ready / status / reason / requires_confirmation
   - blocked=True when status is "blocked"
   - degraded=True when action_level is "observe"
   - never raises on garbage input

8. summarize_fallback_for_projection()
   - returns available=False when fallback_trace is None
   - extracts outcome / decision_source / fallback_path / reason
   - uses compact_summary() when available
   - uses attributes when compact_summary absent
   - never raises on garbage input

9. summarize_execution_trace_for_projection()
   - returns available=False when envelope is None
   - extracts trace_id / final_status / stage_count / stages via compact_summary()
   - extracts via attributes when compact_summary absent
   - never raises on garbage input

10. assemble_projection_governance()
    - returns governance_available=False when all inputs are None
    - returns governance_available=True when at least one input is present
    - populates tri_state_phase / runtime_domain from ContinuumState-like object
    - populates tri_state_phase / runtime_domain from dict continuum
    - sub-summaries all populated (with correct available flags)
    - never raises on all-None inputs
    - never raises on garbage inputs
    - assembled_at is auto-populated

11. Integration with build_runtime_projection
    - governance field is None when no governance inputs provided
    - governance field is populated when readiness_result provided
    - governance field is populated when all governance inputs provided
    - existing RuntimeProjection fields are unchanged when governance is added
    - to_dict() includes "governance" key

12. Additive integration
    - importing core.projection does not break existing tests
    - ProjectionGovernanceSummary is exported from core.projection
    - assemble_projection_governance is exported from core.projection
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from core.projection.assembly_governance import (
    ProjectionExecutionSummary,
    ProjectionExecutionTraceSummary,
    ProjectionGovernanceSummary,
    ProjectionPolicySummary,
    ProjectionTraceSummary,
    assemble_projection_governance,
    summarize_execution_trace_for_projection,
    summarize_fallback_for_projection,
    summarize_intent_for_projection,
    summarize_readiness_for_projection,
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
    """Return a minimal mock ExecutionIntentProfile."""
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
    """Return a minimal mock ReadinessResult."""
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
    decision_source: str = "policy",
    fallback_path: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    primary_path: Optional[str] = "local_executor",
    primary_block_reason: Optional[str] = None,
    action_level: str = "execute",
) -> MagicMock:
    """Return a minimal mock FallbackDecisionTrace with compact_summary."""
    mock = MagicMock()
    mock.compact_summary.return_value = {
        "trace_id": str(uuid.uuid4()),
        "intent_id": "intent-001",
        "action_level": action_level,
        "primary_path": primary_path,
        "primary_block_reason": primary_block_reason,
        "fallback_path": fallback_path,
        "fallback_reason": fallback_reason,
        "decision_source": decision_source,
        "outcome": outcome,
    }
    return mock


def _make_execution_trace_envelope(
    final_status: str = "success",
    stages: Optional[list] = None,
    intent_id: str = "intent-001",
) -> MagicMock:
    """Return a minimal mock ExecutionTraceEnvelope with compact_summary."""
    stages = stages or ["intent_created", "readiness_evaluated", "execution_finished"]
    mock = MagicMock()
    trace_id = str(uuid.uuid4())
    mock.compact_summary.return_value = {
        "trace_id": trace_id,
        "intent_id": intent_id,
        "runtime_session_id": None,
        "final_status": final_status,
        "stage_count": len(stages),
        "stages": stages,
        "created_at": time.time(),
    }
    return mock


def _make_continuum_state(
    phase: str = "manifest",
    domain: str = "local",
) -> MagicMock:
    """Return a minimal mock ContinuumState."""
    mock = MagicMock()
    phase_mock = MagicMock()
    phase_mock.value = phase
    domain_mock = MagicMock()
    domain_mock.value = domain
    mock.tri_state_phase = phase_mock
    mock.runtime_domain = domain_mock
    return mock


# ---------------------------------------------------------------------------
# 1. ProjectionExecutionSummary
# ---------------------------------------------------------------------------


class TestProjectionExecutionSummary:
    def test_defaults_available_false(self):
        s = ProjectionExecutionSummary()
        assert s.available is False
        assert s.action_level == "observe"
        assert s.intent_mode == "advisory"
        assert s.intent_id is None

    def test_construction_all_fields(self):
        s = ProjectionExecutionSummary(
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
        s = ProjectionExecutionSummary(
            intent_id="x-1", action_level="execute", available=True
        )
        d = s.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert "intent_id" in d
        assert "action_level" in d
        assert "available" in d

    def test_to_json_round_trip(self):
        s = ProjectionExecutionSummary(
            intent_id="x-2", action_level="assist", intent_mode="assistive", available=True
        )
        json_str = s.to_json()
        d = json.loads(json_str)
        assert d["intent_id"] == "x-2"
        assert d["action_level"] == "assist"
        assert d["intent_mode"] == "assistive"
        assert d["available"] is True


# ---------------------------------------------------------------------------
# 2. ProjectionPolicySummary
# ---------------------------------------------------------------------------


class TestProjectionPolicySummary:
    def test_defaults_available_false_blocked_true(self):
        s = ProjectionPolicySummary()
        assert s.available is False
        assert s.blocked is True
        assert s.ready is False
        assert s.status == "blocked"

    def test_ready_true(self):
        s = ProjectionPolicySummary(
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
        s = ProjectionPolicySummary(degraded=True, available=True)
        assert s.degraded is True

    def test_to_dict_json_serialisable(self):
        s = ProjectionPolicySummary(ready=True, status="ready", blocked=False, available=True)
        d = s.to_dict()
        json_str = json.dumps(d)
        assert "ready" in d
        assert "status" in d
        assert "blocked" in d
        assert "available" in d


# ---------------------------------------------------------------------------
# 3. ProjectionTraceSummary
# ---------------------------------------------------------------------------


class TestProjectionTraceSummary:
    def test_defaults(self):
        s = ProjectionTraceSummary()
        assert s.available is False
        assert s.outcome == "noop"
        assert s.decision_source == "unknown"
        assert s.fallback_path is None

    def test_construction_full(self):
        s = ProjectionTraceSummary(
            outcome="selected",
            decision_source="policy",
            fallback_path="local_fallback",
            reason="policy denied primary",
            primary_path="cross_device",
            primary_block_reason="policy denied",
            action_level="execute",
            available=True,
        )
        assert s.outcome == "selected"
        assert s.fallback_path == "local_fallback"
        assert s.available is True

    def test_to_dict_json_serialisable(self):
        s = ProjectionTraceSummary(outcome="blocked", available=True)
        d = s.to_dict()
        json_str = json.dumps(d)
        assert "outcome" in d
        assert "available" in d


# ---------------------------------------------------------------------------
# 4. ProjectionExecutionTraceSummary
# ---------------------------------------------------------------------------


class TestProjectionExecutionTraceSummary:
    def test_defaults(self):
        s = ProjectionExecutionTraceSummary()
        assert s.available is False
        assert s.final_status == "pending"
        assert s.stage_count == 0
        assert s.stages == []

    def test_construction_full(self):
        s = ProjectionExecutionTraceSummary(
            trace_id="t-1",
            intent_id="i-1",
            final_status="success",
            stage_count=3,
            stages=["intent_created", "readiness_evaluated", "execution_finished"],
            available=True,
        )
        assert s.final_status == "success"
        assert s.stage_count == 3
        assert len(s.stages) == 3
        assert s.available is True

    def test_to_dict_json_serialisable(self):
        s = ProjectionExecutionTraceSummary(final_status="success", stage_count=2, available=True)
        d = s.to_dict()
        json_str = json.dumps(d)
        assert "final_status" in d
        assert "stage_count" in d
        assert "stages" in d


# ---------------------------------------------------------------------------
# 5. ProjectionGovernanceSummary
# ---------------------------------------------------------------------------


class TestProjectionGovernanceSummary:
    def test_defaults_governance_available_false(self):
        s = ProjectionGovernanceSummary()
        assert s.governance_available is False
        assert s.tri_state_phase is None
        assert s.runtime_domain is None
        assert isinstance(s.assembled_at, float)

    def test_to_dict_includes_sub_summaries(self):
        s = ProjectionGovernanceSummary()
        d = s.to_dict()
        assert "execution" in d
        assert "policy" in d
        assert "fallback" in d
        assert "execution_trace" in d
        assert "tri_state_phase" in d
        assert "runtime_domain" in d
        assert "assembled_at" in d
        assert "governance_available" in d
        # sub-summaries are dicts, not objects
        assert isinstance(d["execution"], dict)
        assert isinstance(d["policy"], dict)
        assert isinstance(d["fallback"], dict)
        assert isinstance(d["execution_trace"], dict)

    def test_to_json_round_trip(self):
        s = ProjectionGovernanceSummary(
            tri_state_phase="manifest",
            runtime_domain="local",
            governance_available=True,
        )
        json_str = s.to_json()
        d = json.loads(json_str)
        assert d["tri_state_phase"] == "manifest"
        assert d["runtime_domain"] == "local"
        assert d["governance_available"] is True

    def test_assembled_at_auto_populated(self):
        before = time.time()
        s = ProjectionGovernanceSummary()
        after = time.time()
        assert before <= s.assembled_at <= after


# ---------------------------------------------------------------------------
# 6. summarize_intent_for_projection
# ---------------------------------------------------------------------------


class TestSummarizeIntentForProjection:
    def test_none_returns_unavailable(self):
        result = summarize_intent_for_projection(None)
        assert result.available is False
        assert result.action_level == "observe"
        assert result.intent_mode == "advisory"

    def test_uses_compact_summary_when_available(self):
        profile = _make_intent_profile(
            action_level="execute", intent_mode="direct", target_ref="notepad"
        )
        result = summarize_intent_for_projection(profile)
        assert result.available is True
        assert result.action_level == "execute"
        assert result.intent_mode == "direct"
        assert result.target_ref == "notepad"

    def test_fallback_to_attributes_when_no_compact_summary(self):
        mock = MagicMock(spec=[])  # no compact_summary attr
        mock.intent_id = "x-100"
        mock.source = "e2e"
        mock.action_level = "assist"
        mock.intent_mode = "assistive"
        mock.target_type = None
        mock.target_ref = None
        mock.device_scope = None
        mock.runtime_domain = None
        mock.confidence = 0.5
        mock.degrade_reason = None
        result = summarize_intent_for_projection(mock)
        assert result.available is True
        assert result.source == "e2e"
        assert result.action_level == "assist"
        assert result.confidence == 0.5

    def test_never_raises_on_garbage(self):
        # Should not raise for any of these
        for garbage in [42, "string", [], {}, object()]:
            result = summarize_intent_for_projection(garbage)
            assert isinstance(result, ProjectionExecutionSummary)

    def test_degrade_reason_propagated(self):
        profile = _make_intent_profile(degrade_reason="policy_blocked")
        result = summarize_intent_for_projection(profile)
        assert result.degrade_reason == "policy_blocked"
        assert result.available is True


# ---------------------------------------------------------------------------
# 7. summarize_readiness_for_projection
# ---------------------------------------------------------------------------


class TestSummarizeReadinessForProjection:
    def test_none_returns_unavailable(self):
        result = summarize_readiness_for_projection(None)
        assert result.available is False
        assert result.ready is False
        assert result.blocked is True

    def test_extracts_ready_true(self):
        r = _make_readiness_result(ready=True, status="ready", blocked_by="none")
        result = summarize_readiness_for_projection(r)
        assert result.available is True
        assert result.ready is True
        assert result.status == "ready"
        assert result.blocked is False

    def test_blocked_flag_when_status_blocked(self):
        r = _make_readiness_result(ready=False, status="blocked", blocked_by="policy")
        result = summarize_readiness_for_projection(r)
        assert result.blocked is True

    def test_degraded_for_observe_action_level(self):
        r = _make_readiness_result(action_level="observe", status="observe_only")
        result = summarize_readiness_for_projection(r)
        assert result.degraded is True

    def test_requires_confirmation_propagated(self):
        r = _make_readiness_result(
            ready=True, status="confirm_required", requires_confirmation=True
        )
        result = summarize_readiness_for_projection(r)
        assert result.requires_confirmation is True

    def test_never_raises_on_garbage(self):
        for garbage in [42, "string", [], {}, object()]:
            result = summarize_readiness_for_projection(garbage)
            assert isinstance(result, ProjectionPolicySummary)

    def test_policy_band_propagated(self):
        r = _make_readiness_result(policy_band="bounded_execute")
        result = summarize_readiness_for_projection(r)
        assert result.policy_band == "bounded_execute"


# ---------------------------------------------------------------------------
# 8. summarize_fallback_for_projection
# ---------------------------------------------------------------------------


class TestSummarizeFallbackForProjection:
    def test_none_returns_unavailable(self):
        result = summarize_fallback_for_projection(None)
        assert result.available is False
        assert result.outcome == "noop"

    def test_uses_compact_summary(self):
        trace = _make_fallback_trace(
            outcome="selected",
            decision_source="readiness_gate",
            fallback_path="local_fallback",
            fallback_reason="executor unavailable",
            primary_path="cross_device",
            primary_block_reason="bridge down",
        )
        result = summarize_fallback_for_projection(trace)
        assert result.available is True
        assert result.outcome == "selected"
        assert result.decision_source == "readiness_gate"
        assert result.fallback_path == "local_fallback"
        assert result.reason == "executor unavailable"

    def test_fallback_to_attributes_when_no_compact_summary(self):
        mock = MagicMock(spec=[])  # no compact_summary
        mock.outcome = "degraded"
        mock.decision_source = "executor"
        mock.fallback_path = "degraded_assist"
        mock.fallback_reason = "partial failure"
        mock.reason = None
        mock.primary_path = "local_executor"
        mock.primary_block_reason = None
        mock.action_level = "assist"
        result = summarize_fallback_for_projection(mock)
        assert result.available is True
        assert result.outcome == "degraded"

    def test_never_raises_on_garbage(self):
        for garbage in [42, "string", [], {}, object()]:
            result = summarize_fallback_for_projection(garbage)
            assert isinstance(result, ProjectionTraceSummary)

    def test_noop_outcome_preserved(self):
        trace = _make_fallback_trace(outcome="noop")
        result = summarize_fallback_for_projection(trace)
        assert result.outcome == "noop"


# ---------------------------------------------------------------------------
# 9. summarize_execution_trace_for_projection
# ---------------------------------------------------------------------------


class TestSummarizeExecutionTraceForProjection:
    def test_none_returns_unavailable(self):
        result = summarize_execution_trace_for_projection(None)
        assert result.available is False
        assert result.final_status == "pending"
        assert result.stage_count == 0
        assert result.stages == []

    def test_uses_compact_summary(self):
        envelope = _make_execution_trace_envelope(
            final_status="success",
            stages=["intent_created", "readiness_evaluated", "execution_finished"],
            intent_id="i-5",
        )
        result = summarize_execution_trace_for_projection(envelope)
        assert result.available is True
        assert result.final_status == "success"
        assert result.stage_count == 3
        assert "intent_created" in result.stages

    def test_fallback_to_attributes(self):
        mock = MagicMock(spec=[])  # no compact_summary
        event1 = MagicMock()
        event1.stage = "intent_created"
        event2 = MagicMock()
        event2.stage = "execution_finished"
        mock.trace_id = "t-99"
        mock.intent_id = "i-99"
        mock.final_status = "failed"
        mock.events = [event1, event2]
        result = summarize_execution_trace_for_projection(mock)
        assert result.available is True
        assert result.final_status == "failed"
        assert result.stage_count == 2
        assert result.stages == ["intent_created", "execution_finished"]

    def test_never_raises_on_garbage(self):
        for garbage in [42, "string", [], {}, object()]:
            result = summarize_execution_trace_for_projection(garbage)
            assert isinstance(result, ProjectionExecutionTraceSummary)


# ---------------------------------------------------------------------------
# 10. assemble_projection_governance
# ---------------------------------------------------------------------------


class TestAssembleProjectionGovernance:
    def test_all_none_returns_minimal_safe(self):
        gov = assemble_projection_governance()
        assert gov.governance_available is False
        assert gov.execution.available is False
        assert gov.policy.available is False
        assert gov.fallback.available is False
        assert gov.execution_trace.available is False
        assert gov.tri_state_phase is None
        assert gov.runtime_domain is None
        assert isinstance(gov.assembled_at, float)

    def test_governance_available_when_intent_present(self):
        profile = _make_intent_profile()
        gov = assemble_projection_governance(intent_profile=profile)
        assert gov.governance_available is True
        assert gov.execution.available is True
        assert gov.policy.available is False
        assert gov.fallback.available is False
        assert gov.execution_trace.available is False

    def test_governance_available_when_readiness_present(self):
        readiness = _make_readiness_result()
        gov = assemble_projection_governance(readiness_result=readiness)
        assert gov.governance_available is True
        assert gov.policy.available is True

    def test_all_inputs_present(self):
        gov = assemble_projection_governance(
            intent_profile=_make_intent_profile(),
            readiness_result=_make_readiness_result(),
            fallback_trace=_make_fallback_trace(),
            execution_trace_envelope=_make_execution_trace_envelope(),
        )
        assert gov.governance_available is True
        assert gov.execution.available is True
        assert gov.policy.available is True
        assert gov.fallback.available is True
        assert gov.execution_trace.available is True

    def test_phase_domain_from_continuum_object(self):
        state = _make_continuum_state(phase="manifest", domain="local")
        gov = assemble_projection_governance(state_continuum=state)
        assert gov.tri_state_phase == "manifest"
        assert gov.runtime_domain == "local"

    def test_phase_domain_from_dict_continuum(self):
        state = {"tri_state_phase": "liminal", "runtime_domain": "cross_device"}
        gov = assemble_projection_governance(state_continuum=state)
        assert gov.tri_state_phase == "liminal"
        assert gov.runtime_domain == "cross_device"

    def test_explicit_timestamp(self):
        ts = 1710000000.0
        gov = assemble_projection_governance(timestamp=ts)
        assert gov.assembled_at == ts

    def test_never_raises_on_garbage_inputs(self):
        for garbage in [42, "string", [], {}, object()]:
            gov = assemble_projection_governance(
                intent_profile=garbage,
                readiness_result=garbage,
                fallback_trace=garbage,
                execution_trace_envelope=garbage,
                state_continuum=garbage,
            )
            assert isinstance(gov, ProjectionGovernanceSummary)

    def test_to_dict_serialisable(self):
        gov = assemble_projection_governance(
            intent_profile=_make_intent_profile(),
            readiness_result=_make_readiness_result(),
        )
        d = gov.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert d["governance_available"] is True
        assert isinstance(d["execution"], dict)
        assert isinstance(d["policy"], dict)


# ---------------------------------------------------------------------------
# 11. Integration with build_runtime_projection
# ---------------------------------------------------------------------------


class TestBuildRuntimeProjectionGovernanceIntegration:
    """Verify that build_runtime_projection correctly populates the governance field."""

    def _make_minimal_continuum(self):
        from core.continuum.types import ContinuumPhase, ContinuumState
        return ContinuumState(phase=ContinuumPhase.LIMINAL)

    def test_governance_none_when_no_governance_inputs(self):
        from core.projection import build_runtime_projection
        state = self._make_minimal_continuum()
        projection = build_runtime_projection(state)
        assert projection.governance is None

    def test_governance_populated_when_readiness_provided(self):
        from core.projection import build_runtime_projection
        state = self._make_minimal_continuum()
        readiness = _make_readiness_result()
        projection = build_runtime_projection(state, readiness_result=readiness)
        assert projection.governance is not None
        assert isinstance(projection.governance, dict)
        assert projection.governance["governance_available"] is True
        assert projection.governance["policy"]["available"] is True

    def test_governance_populated_when_all_inputs_provided(self):
        from core.projection import build_runtime_projection
        state = self._make_minimal_continuum()
        projection = build_runtime_projection(
            state,
            intent_profile=_make_intent_profile(),
            readiness_result=_make_readiness_result(),
            fallback_trace=_make_fallback_trace(),
            execution_trace_envelope=_make_execution_trace_envelope(),
        )
        assert projection.governance is not None
        assert projection.governance["governance_available"] is True

    def test_existing_fields_unchanged(self):
        from core.projection import build_runtime_projection
        from core.continuum.types import ContinuumPhase, ContinuumState, RuntimeDomain
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            coherence=0.8,
            presence_intensity=0.9,
        )
        projection = build_runtime_projection(
            state, readiness_result=_make_readiness_result()
        )
        # Base fields are unaffected
        assert projection.tri_state_phase.value == "manifest"
        assert projection.coherence == 0.8
        assert projection.presence_intensity == 0.9
        # Governance added
        assert projection.governance is not None

    def test_to_dict_includes_governance_key(self):
        from core.projection import build_runtime_projection
        state = self._make_minimal_continuum()
        projection = build_runtime_projection(
            state, readiness_result=_make_readiness_result()
        )
        d = projection.to_dict()
        assert "governance" in d
        assert d["governance"] is not None

    def test_to_dict_governance_none_when_not_provided(self):
        from core.projection import build_runtime_projection
        state = self._make_minimal_continuum()
        projection = build_runtime_projection(state)
        d = projection.to_dict()
        assert "governance" in d
        assert d["governance"] is None


# ---------------------------------------------------------------------------
# 12. Additive integration — public exports
# ---------------------------------------------------------------------------


class TestAdditiveIntegration:
    def test_exports_from_core_projection(self):
        import core.projection as proj_pkg
        # All new PR-26 symbols should be importable from core.projection
        assert hasattr(proj_pkg, "ProjectionGovernanceSummary")
        assert hasattr(proj_pkg, "ProjectionExecutionSummary")
        assert hasattr(proj_pkg, "ProjectionPolicySummary")
        assert hasattr(proj_pkg, "ProjectionTraceSummary")
        assert hasattr(proj_pkg, "ProjectionExecutionTraceSummary")
        assert hasattr(proj_pkg, "assemble_projection_governance")
        assert hasattr(proj_pkg, "summarize_intent_for_projection")
        assert hasattr(proj_pkg, "summarize_readiness_for_projection")
        assert hasattr(proj_pkg, "summarize_fallback_for_projection")
        assert hasattr(proj_pkg, "summarize_execution_trace_for_projection")

    def test_existing_exports_still_present(self):
        from core.projection import (
            ExecutionSummary,
            RuntimeProjection,
            build_runtime_projection,
        )
        assert RuntimeProjection is not None
        assert ExecutionSummary is not None
        assert build_runtime_projection is not None

    def test_governance_summary_is_serialisable_end_to_end(self):
        """Full serialisation round-trip for a governance summary."""
        gov = assemble_projection_governance(
            intent_profile=_make_intent_profile(action_level="execute"),
            readiness_result=_make_readiness_result(ready=True),
            fallback_trace=_make_fallback_trace(outcome="noop"),
            execution_trace_envelope=_make_execution_trace_envelope(final_status="success"),
            state_continuum={"tri_state_phase": "manifest", "runtime_domain": "local"},
        )
        json_str = gov.to_json()
        d = json.loads(json_str)
        # Round-trip preserves key structure
        assert d["governance_available"] is True
        assert d["execution"]["action_level"] == "execute"
        assert d["policy"]["ready"] is True
        assert d["fallback"]["outcome"] == "noop"
        assert d["execution_trace"]["final_status"] == "success"
        assert d["tri_state_phase"] == "manifest"
        assert d["runtime_domain"] == "local"
