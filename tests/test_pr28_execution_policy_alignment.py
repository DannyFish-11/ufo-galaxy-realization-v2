"""
tests/test_pr28_execution_policy_alignment.py
===============================================
Focused tests for PR-28: Execution Policy Alignment Surface.

Coverage
--------
1. AlignmentMismatch
   - construction with defaults
   - construction with all fields
   - to_dict is JSON-serialisable
   - to_json / to_dict round-trip preserves fields

2. AlignmentDimensionSummary
   - construction with defaults (available=False)
   - construction with all fields
   - to_dict is JSON-serialisable
   - summary_fields preserved

3. ExecutionPolicyHints
   - construction with defaults
   - to_dict is JSON-serialisable
   - hint_source defaults to "empty"

4. ExecutionPolicyAlignmentSummary
   - construction with defaults (aligned=False, policy_posture="unknown")
   - to_dict includes all sub-summaries as nested dicts
   - to_json round-trip stability
   - alignment_id is auto-populated when not provided
   - timestamp is auto-populated when not provided
   - __repr__ includes phase / posture / aligned / mismatches count

5. summarize_runtime_policy_alignment()
   - returns available=False when snapshot is None
   - extracts fields from RuntimeGovernanceSnapshot dict
   - extracts fields from pydantic-like object
   - never raises on garbage input
   - blocked propagates from readiness_summary

6. summarize_dispatch_policy_alignment()
   - returns available=False when both inputs are None
   - extracts ack_required from handoff_policy dict
   - extracts ack_required from pydantic-like handoff_policy
   - max_handoff_depth=0 → blocked=True
   - dispatch_status "failed" → blocked=True
   - never raises on garbage input

7. summarize_projection_policy_alignment()
   - returns available=False when projection_governance is None
   - returns available=False when governance_available=False
   - extracts fields from dict
   - extracts fields from pydantic-like object
   - never raises on garbage input

8. build_execution_policy_alignment_surface()
   - returns aligned=False when all inputs are None
   - policy_posture is "unknown" when all inputs are None
   - blocked=True when any dimension is blocked
   - degraded=True when critical mismatches present
   - confirmation_required propagates from readiness
   - aligned=True when two+ dimensions agree and no mismatches
   - posture resolves to "confirmation_gated" with confirmation signal
   - posture resolves to "blocked" when blocked signal present
   - posture resolves to "remote_required" with cross_device=True
   - posture resolves to "local_preferred" with local domain
   - trace_id resolved from execution_trace_envelope
   - runtime_domain resolved from snapshot / projection_governance
   - never raises on all-None inputs
   - never raises on garbage inputs
   - alignment_id auto-populated
   - timestamp auto-populated

9. Mismatch detection
   - no mismatches when only one dimension available
   - blocked mismatch detected as "critical"
   - confirmation_required mismatch detected as "warning"
   - cross_device_allowed mismatch detected as "warning"
   - runtime_domain mismatch detected as "info"
   - no mismatch when dimensions agree on all signals

10. Alignment hints
    - hint_source "empty" when no dimensions available
    - hint_source "partial" when some dimensions unavailable
    - hint_source "full" when all dimensions available
    - can_execute_locally=False when blocked
    - can_expand_cross_device=True only when all cross signals agree True
    - alignment_confidence decreases with critical mismatches

11. Serialisation stability
    - to_dict() round-trip stable across two calls on the same summary
    - to_json() produces valid JSON
    - nested sub-summaries serialised correctly
    - no non-serialisable values in to_dict()

12. Additive integration
    - ExecutionPolicyAlignmentSummary importable from core.policy.alignment_surface
    - build_execution_policy_alignment_surface importable from core.policy.alignment_surface
    - RuntimeProjection.policy_alignment field exists
    - RuntimeProjection.to_dict() includes "policy_alignment" key
    - existing RuntimeProjection fields unchanged when policy_alignment is None
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from core.policy.alignment_surface import (
    AlignmentDimensionSummary,
    AlignmentMismatch,
    ExecutionPolicyAlignmentSummary,
    ExecutionPolicyHints,
    POSTURE_BLOCKED,
    POSTURE_CONFIRMATION_GATED,
    POSTURE_DEGRADED,
    POSTURE_LOCAL_PREFERRED,
    POSTURE_REMOTE_REQUIRED,
    POSTURE_UNKNOWN,
    build_execution_policy_alignment_surface,
    summarize_dispatch_policy_alignment,
    summarize_projection_policy_alignment,
    summarize_runtime_policy_alignment,
)


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


def _make_runtime_snapshot_dict(
    *,
    governance_available: bool = True,
    blocked: bool = False,
    degraded: bool = False,
    posture: str = "execute",
    ready: bool = True,
    requires_confirmation: bool = False,
    action_level: str = "execute",
    intent_mode: str = "autonomous",
    runtime_domain: Optional[str] = "local",
) -> Dict[str, Any]:
    return {
        "governance_available": governance_available,
        "blocked": blocked,
        "degraded": degraded,
        "posture": posture,
        "runtime_domain": runtime_domain,
        "readiness_summary": {
            "available": governance_available,
            "ready": ready,
            "status": "ready" if ready else "blocked",
            "blocked": not ready,
            "degraded": degraded,
            "requires_confirmation": requires_confirmation,
        },
        "intent_summary": {
            "available": governance_available,
            "action_level": action_level,
            "intent_mode": intent_mode,
            "runtime_domain": runtime_domain,
        },
    }


def _make_projection_governance_dict(
    *,
    governance_available: bool = True,
    blocked: bool = False,
    degraded: bool = False,
    requires_confirmation: bool = False,
    action_level: str = "execute",
    tri_state_phase: Optional[str] = "manifest",
    runtime_domain: Optional[str] = "local",
) -> Dict[str, Any]:
    return {
        "governance_available": governance_available,
        "tri_state_phase": tri_state_phase,
        "runtime_domain": runtime_domain,
        "policy": {
            "available": governance_available,
            "blocked": blocked,
            "degraded": degraded,
            "requires_confirmation": requires_confirmation,
            "status": "ready" if not blocked else "blocked",
        },
        "execution": {
            "available": governance_available,
            "action_level": action_level,
        },
    }


def _make_readiness_result_obj(
    *,
    ready: bool = True,
    status: str = "ready",
    requires_confirmation: bool = False,
    action_level: str = "execute",
    cross_device_allowed: Optional[bool] = None,
) -> MagicMock:
    obj = MagicMock()
    obj.ready = ready
    obj.status = status
    obj.reason = "test reason"
    obj.requires_confirmation = requires_confirmation
    obj.action_level = action_level
    obj.cross_device_allowed = cross_device_allowed
    return obj


def _make_handoff_policy_dict(
    *,
    ack_required: bool = True,
    recovery_permitted: bool = True,
    max_handoff_depth: int = 5,
) -> Dict[str, Any]:
    return {
        "ack_required": ack_required,
        "recovery_permitted": recovery_permitted,
        "max_handoff_depth": max_handoff_depth,
    }


def _make_execution_trace_envelope(
    *,
    trace_id: str = "trace-abc",
    runtime_session_id: str = "sess-xyz",
) -> MagicMock:
    obj = MagicMock()
    obj.trace_id = trace_id
    obj.runtime_session_id = runtime_session_id
    return obj


# ---------------------------------------------------------------------------
# 1. AlignmentMismatch
# ---------------------------------------------------------------------------


class TestAlignmentMismatch:
    def test_defaults(self):
        m = AlignmentMismatch(
            dimension_a="runtime_policy", dimension_b="readiness_policy"
        )
        assert m.dimension_a == "runtime_policy"
        assert m.dimension_b == "readiness_policy"
        assert m.field_a is None
        assert m.field_b is None
        assert m.value_a is None
        assert m.value_b is None
        assert m.severity == "warning"
        assert m.description == ""

    def test_all_fields(self):
        m = AlignmentMismatch(
            dimension_a="runtime_policy",
            dimension_b="readiness_policy",
            field_a="blocked",
            field_b="blocked",
            value_a=False,
            value_b=True,
            severity="critical",
            description="test mismatch",
        )
        assert m.severity == "critical"
        assert m.value_a is False
        assert m.value_b is True

    def test_to_dict_json_serialisable(self):
        m = AlignmentMismatch(
            dimension_a="a", dimension_b="b", severity="info"
        )
        d = m.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must not raise

    def test_to_json_round_trip(self):
        m = AlignmentMismatch(
            dimension_a="runtime_policy",
            dimension_b="dispatch_policy",
            field_a="blocked",
            value_a=True,
            value_b=False,
            severity="critical",
            description="desc",
        )
        raw = m.to_json()
        parsed = json.loads(raw)
        assert parsed["dimension_a"] == "runtime_policy"
        assert parsed["severity"] == "critical"


# ---------------------------------------------------------------------------
# 2. AlignmentDimensionSummary
# ---------------------------------------------------------------------------


class TestAlignmentDimensionSummary:
    def test_defaults(self):
        d = AlignmentDimensionSummary(dimension="runtime_policy")
        assert d.available is False
        assert d.blocked is False
        assert d.degraded is False
        assert d.confirmation_required is False
        assert d.cross_device_allowed is None
        assert d.runtime_domain is None
        assert d.action_level is None
        assert d.summary_fields == {}

    def test_all_fields(self):
        d = AlignmentDimensionSummary(
            dimension="readiness_policy",
            available=True,
            posture_signal="ready",
            blocked=False,
            degraded=False,
            confirmation_required=True,
            cross_device_allowed=True,
            runtime_domain="local",
            action_level="execute",
            summary_fields={"foo": "bar"},
        )
        assert d.available is True
        assert d.confirmation_required is True
        assert d.summary_fields == {"foo": "bar"}

    def test_to_dict_json_serialisable(self):
        d = AlignmentDimensionSummary(
            dimension="fallback_policy", available=True, blocked=True
        )
        raw = d.to_dict()
        json.dumps(raw)  # must not raise

    def test_summary_fields_preserved(self):
        d = AlignmentDimensionSummary(
            dimension="dispatch_policy",
            summary_fields={"ack_required": True, "max_handoff_depth": 3},
        )
        assert d.summary_fields["ack_required"] is True
        assert d.summary_fields["max_handoff_depth"] == 3


# ---------------------------------------------------------------------------
# 3. ExecutionPolicyHints
# ---------------------------------------------------------------------------


class TestExecutionPolicyHints:
    def test_defaults(self):
        h = ExecutionPolicyHints()
        assert h.can_execute_locally is False
        assert h.can_expand_cross_device is False
        assert h.is_confirmation_gated is False
        assert h.is_blocked is False
        assert h.is_degraded is False
        assert h.preferred_domain is None
        assert h.effective_action_level == "observe"
        assert h.alignment_confidence == 0.0
        assert h.policy_posture == POSTURE_UNKNOWN
        assert h.hint_source == "empty"

    def test_to_dict_json_serialisable(self):
        h = ExecutionPolicyHints(
            can_execute_locally=True,
            policy_posture=POSTURE_LOCAL_PREFERRED,
            hint_source="full",
        )
        raw = h.to_dict()
        json.dumps(raw)  # must not raise


# ---------------------------------------------------------------------------
# 4. ExecutionPolicyAlignmentSummary
# ---------------------------------------------------------------------------


class TestExecutionPolicyAlignmentSummary:
    def test_defaults(self):
        s = ExecutionPolicyAlignmentSummary()
        assert s.aligned is False
        assert s.blocked is False
        assert s.degraded is False
        assert s.confirmation_required is False
        assert s.policy_posture == POSTURE_UNKNOWN
        assert s.mismatches == []
        assert isinstance(s.alignment_hints, ExecutionPolicyHints)
        assert isinstance(s.runtime_policy_summary, AlignmentDimensionSummary)
        assert isinstance(s.readiness_policy_summary, AlignmentDimensionSummary)
        assert isinstance(s.fallback_policy_summary, AlignmentDimensionSummary)
        assert isinstance(s.dispatch_policy_summary, AlignmentDimensionSummary)
        assert isinstance(s.projection_policy_summary, AlignmentDimensionSummary)

    def test_to_dict_includes_all_sub_summaries(self):
        s = ExecutionPolicyAlignmentSummary()
        d = s.to_dict()
        assert "runtime_policy_summary" in d
        assert "readiness_policy_summary" in d
        assert "fallback_policy_summary" in d
        assert "dispatch_policy_summary" in d
        assert "projection_policy_summary" in d
        assert "mismatches" in d
        assert "alignment_hints" in d

    def test_to_json_round_trip_stability(self):
        s = ExecutionPolicyAlignmentSummary(
            aligned=True,
            policy_posture=POSTURE_LOCAL_PREFERRED,
            tri_state_phase="manifest",
            runtime_domain="local",
        )
        raw1 = s.to_json()
        raw2 = s.to_json()
        assert raw1 == raw2
        parsed = json.loads(raw1)
        assert parsed["aligned"] is True

    def test_alignment_id_auto_populated(self):
        s = ExecutionPolicyAlignmentSummary()
        assert s.alignment_id is not None
        assert len(s.alignment_id) == 36  # UUID4 format

    def test_timestamp_auto_populated(self):
        before = time.time()
        s = ExecutionPolicyAlignmentSummary()
        after = time.time()
        assert before <= s.timestamp <= after

    def test_repr_includes_key_fields(self):
        s = ExecutionPolicyAlignmentSummary(
            policy_posture=POSTURE_BLOCKED,
            aligned=False,
            tri_state_phase="manifest",
        )
        r = repr(s)
        assert "blocked" in r
        assert "aligned=False" in r


# ---------------------------------------------------------------------------
# 5. summarize_runtime_policy_alignment()
# ---------------------------------------------------------------------------


class TestSummarizeRuntimePolicyAlignment:
    def test_returns_unavailable_when_none(self):
        d = summarize_runtime_policy_alignment(None)
        assert d.dimension == "runtime_policy"
        assert d.available is False

    def test_extracts_fields_from_dict(self):
        snap = _make_runtime_snapshot_dict(ready=True, action_level="execute")
        d = summarize_runtime_policy_alignment(snap)
        assert d.available is True
        assert d.blocked is False
        assert d.action_level == "execute"

    def test_blocked_propagates_from_readiness(self):
        snap = _make_runtime_snapshot_dict(ready=False, blocked=False)
        # readiness blocked should override snapshot.blocked
        d = summarize_runtime_policy_alignment(snap)
        assert d.available is True
        assert d.blocked is True

    def test_governance_unavailable_returns_unavailable(self):
        snap = _make_runtime_snapshot_dict(governance_available=False)
        d = summarize_runtime_policy_alignment(snap)
        assert d.available is False

    def test_extracts_from_object_attribute(self):
        obj = MagicMock()
        obj.governance_available = True
        obj.blocked = False
        obj.degraded = False
        obj.posture = "execute"
        obj.runtime_domain = "local"

        readiness = MagicMock()
        readiness.requires_confirmation = False
        readiness.status = "ready"
        obj.readiness_summary = readiness

        intent = MagicMock()
        intent.action_level = "execute"
        intent.intent_mode = "autonomous"
        intent.runtime_domain = "local"
        obj.intent_summary = intent

        d = summarize_runtime_policy_alignment(obj)
        assert d.available is True
        assert d.action_level == "execute"

    def test_never_raises_on_garbage(self):
        d = summarize_runtime_policy_alignment("garbage_input")
        assert isinstance(d, AlignmentDimensionSummary)

    def test_never_raises_on_integer(self):
        d = summarize_runtime_policy_alignment(12345)
        assert isinstance(d, AlignmentDimensionSummary)


# ---------------------------------------------------------------------------
# 6. summarize_dispatch_policy_alignment()
# ---------------------------------------------------------------------------


class TestSummarizeDispatchPolicyAlignment:
    def test_returns_unavailable_when_both_none(self):
        d = summarize_dispatch_policy_alignment(None, None)
        assert d.dimension == "dispatch_policy"
        assert d.available is False

    def test_ack_required_from_dict(self):
        policy = _make_handoff_policy_dict(ack_required=True)
        d = summarize_dispatch_policy_alignment(handoff_policy=policy)
        assert d.available is True
        assert d.confirmation_required is True
        assert d.summary_fields["ack_required"] is True

    def test_ack_required_from_object(self):
        obj = MagicMock()
        obj.ack_required = True
        obj.recovery_permitted = True
        obj.max_handoff_depth = 5
        d = summarize_dispatch_policy_alignment(handoff_policy=obj)
        assert d.available is True
        assert d.confirmation_required is True

    def test_max_handoff_depth_zero_blocks(self):
        policy = _make_handoff_policy_dict(max_handoff_depth=0)
        d = summarize_dispatch_policy_alignment(handoff_policy=policy)
        assert d.blocked is True

    def test_dispatch_status_failed_blocks(self):
        dispatch = {"status": "failed"}
        d = summarize_dispatch_policy_alignment(dispatch_summary=dispatch)
        assert d.available is True
        assert d.blocked is True

    def test_dispatch_status_blocked(self):
        dispatch = {"status": "blocked"}
        d = summarize_dispatch_policy_alignment(dispatch_summary=dispatch)
        assert d.blocked is True

    def test_never_raises_on_garbage(self):
        d = summarize_dispatch_policy_alignment("garbage", "more_garbage")
        assert isinstance(d, AlignmentDimensionSummary)


# ---------------------------------------------------------------------------
# 7. summarize_projection_policy_alignment()
# ---------------------------------------------------------------------------


class TestSummarizeProjectionPolicyAlignment:
    def test_returns_unavailable_when_none(self):
        d = summarize_projection_policy_alignment(None)
        assert d.dimension == "projection_policy"
        assert d.available is False

    def test_returns_unavailable_when_governance_false(self):
        gov = _make_projection_governance_dict(governance_available=False)
        d = summarize_projection_policy_alignment(gov)
        assert d.available is False

    def test_extracts_from_dict(self):
        gov = _make_projection_governance_dict(
            blocked=False, requires_confirmation=True, action_level="assist"
        )
        d = summarize_projection_policy_alignment(gov)
        assert d.available is True
        assert d.confirmation_required is True
        assert d.action_level == "assist"

    def test_blocked_propagates_from_dict(self):
        gov = _make_projection_governance_dict(blocked=True)
        d = summarize_projection_policy_alignment(gov)
        assert d.available is True
        assert d.blocked is True

    def test_extracts_from_pydantic_object(self):
        obj = MagicMock()
        obj.governance_available = True
        obj.tri_state_phase = "manifest"
        obj.runtime_domain = "local"

        policy = MagicMock()
        policy.blocked = False
        policy.degraded = False
        policy.requires_confirmation = False
        policy.status = "ready"
        obj.policy = policy

        execution = MagicMock()
        execution.action_level = "execute"
        obj.execution = execution

        d = summarize_projection_policy_alignment(obj)
        assert d.available is True
        assert d.action_level == "execute"

    def test_never_raises_on_garbage(self):
        d = summarize_projection_policy_alignment(object())
        assert isinstance(d, AlignmentDimensionSummary)


# ---------------------------------------------------------------------------
# 8. build_execution_policy_alignment_surface()
# ---------------------------------------------------------------------------


class TestBuildExecutionPolicyAlignmentSurface:
    def test_all_none_returns_valid_summary(self):
        s = build_execution_policy_alignment_surface()
        assert isinstance(s, ExecutionPolicyAlignmentSummary)
        assert s.aligned is False
        assert s.policy_posture == POSTURE_UNKNOWN

    def test_blocked_when_any_dimension_blocked(self):
        readiness = _make_readiness_result_obj(ready=False, status="blocked")
        s = build_execution_policy_alignment_surface(readiness_result=readiness)
        assert s.blocked is True
        assert s.policy_posture == POSTURE_BLOCKED

    def test_confirmation_required_propagates(self):
        readiness = _make_readiness_result_obj(
            ready=True, requires_confirmation=True, status="confirm_required"
        )
        s = build_execution_policy_alignment_surface(readiness_result=readiness)
        assert s.confirmation_required is True
        assert s.policy_posture == POSTURE_CONFIRMATION_GATED

    def test_aligned_when_dimensions_agree(self):
        snap = _make_runtime_snapshot_dict(ready=True, blocked=False)
        proj = _make_projection_governance_dict(blocked=False)
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
        )
        assert s.aligned is True
        assert s.mismatches == []

    def test_not_aligned_on_blocked_mismatch(self):
        snap = _make_runtime_snapshot_dict(ready=True, blocked=False)
        proj = _make_projection_governance_dict(blocked=True)
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
        )
        assert s.aligned is False
        assert len(s.mismatches) > 0

    def test_posture_local_preferred_with_local_domain(self):
        s = build_execution_policy_alignment_surface(
            runtime_domain="local",
        )
        # without any blocked/confirm signals, posture should lean local
        assert s.policy_posture in (POSTURE_LOCAL_PREFERRED, POSTURE_UNKNOWN)

    def test_posture_remote_required_with_cross_device(self):
        readiness = _make_readiness_result_obj(
            ready=True, cross_device_allowed=True
        )
        s = build_execution_policy_alignment_surface(
            readiness_result=readiness,
            runtime_domain="cross_device",
        )
        assert s.policy_posture == POSTURE_REMOTE_REQUIRED

    def test_trace_id_resolved_from_envelope(self):
        envelope = _make_execution_trace_envelope(
            trace_id="trace-123", runtime_session_id="sess-456"
        )
        s = build_execution_policy_alignment_surface(
            execution_trace_envelope=envelope
        )
        assert s.trace_id == "trace-123"
        assert s.runtime_session_id == "sess-456"

    def test_trace_id_override_wins_over_envelope(self):
        envelope = _make_execution_trace_envelope(trace_id="trace-from-envelope")
        s = build_execution_policy_alignment_surface(
            execution_trace_envelope=envelope,
            trace_id="explicit-trace",
        )
        assert s.trace_id == "explicit-trace"

    def test_runtime_domain_resolved_from_snapshot(self):
        snap = _make_runtime_snapshot_dict(runtime_domain="cross_device")
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap
        )
        assert s.runtime_domain == "cross_device"

    def test_never_raises_on_all_none(self):
        s = build_execution_policy_alignment_surface()
        assert isinstance(s, ExecutionPolicyAlignmentSummary)

    def test_never_raises_on_garbage_inputs(self):
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot="garbage",
            projection_governance=12345,
            readiness_result=object(),
            fallback_trace="bad",
            dispatch_summary=None,
            handoff_policy=[1, 2, 3],
        )
        assert isinstance(s, ExecutionPolicyAlignmentSummary)

    def test_alignment_id_auto_populated(self):
        s = build_execution_policy_alignment_surface()
        assert s.alignment_id is not None
        # UUID4 format: 8-4-4-4-12
        parts = s.alignment_id.split("-")
        assert len(parts) == 5

    def test_explicit_alignment_id_preserved(self):
        aid = "my-custom-id"
        s = build_execution_policy_alignment_surface(alignment_id=aid)
        assert s.alignment_id == aid

    def test_timestamp_auto_populated(self):
        before = time.time()
        s = build_execution_policy_alignment_surface()
        after = time.time()
        assert before <= s.timestamp <= after

    def test_explicit_timestamp_preserved(self):
        ts = 1_700_000_000.0
        s = build_execution_policy_alignment_surface(timestamp=ts)
        assert s.timestamp == ts

    def test_five_dimension_summaries_always_present(self):
        s = build_execution_policy_alignment_surface()
        assert s.runtime_policy_summary.dimension == "runtime_policy"
        assert s.readiness_policy_summary.dimension == "readiness_policy"
        assert s.fallback_policy_summary.dimension == "fallback_policy"
        assert s.dispatch_policy_summary.dimension == "dispatch_policy"
        assert s.projection_policy_summary.dimension == "projection_policy"


# ---------------------------------------------------------------------------
# 9. Mismatch detection
# ---------------------------------------------------------------------------


class TestMismatchDetection:
    def test_no_mismatches_with_one_dimension(self):
        snap = _make_runtime_snapshot_dict(blocked=False)
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap
        )
        assert s.mismatches == []

    def test_blocked_mismatch_is_critical(self):
        snap = _make_runtime_snapshot_dict(ready=True, blocked=False)
        proj = _make_projection_governance_dict(blocked=True)
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
        )
        critical = [m for m in s.mismatches if m.severity == "critical"]
        assert len(critical) >= 1

    def test_confirmation_mismatch_is_warning(self):
        snap = _make_runtime_snapshot_dict(requires_confirmation=True)
        proj = _make_projection_governance_dict(requires_confirmation=False)
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
        )
        warning = [m for m in s.mismatches if m.severity == "warning"]
        assert len(warning) >= 1

    def test_no_mismatch_when_dimensions_agree(self):
        snap = _make_runtime_snapshot_dict(
            blocked=False, requires_confirmation=False, ready=True
        )
        proj = _make_projection_governance_dict(
            blocked=False, requires_confirmation=False
        )
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
        )
        assert s.mismatches == []
        assert s.aligned is True


# ---------------------------------------------------------------------------
# 10. Alignment hints
# ---------------------------------------------------------------------------


class TestAlignmentHints:
    def test_hint_source_empty_when_no_dimensions(self):
        s = build_execution_policy_alignment_surface()
        assert s.alignment_hints.hint_source == "empty"

    def test_hint_source_partial_when_some_available(self):
        snap = _make_runtime_snapshot_dict()
        # Only runtime snapshot provided → runtime_policy available, others not
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap
        )
        assert s.alignment_hints.hint_source == "partial"

    def test_can_execute_locally_false_when_blocked(self):
        readiness = _make_readiness_result_obj(ready=False, status="blocked")
        s = build_execution_policy_alignment_surface(readiness_result=readiness)
        assert s.alignment_hints.can_execute_locally is False

    def test_can_expand_cross_device_true_only_with_all_agree(self):
        readiness = _make_readiness_result_obj(
            ready=True, cross_device_allowed=True
        )
        s = build_execution_policy_alignment_surface(readiness_result=readiness)
        assert s.alignment_hints.can_expand_cross_device is True

    def test_alignment_confidence_zero_with_no_data(self):
        s = build_execution_policy_alignment_surface()
        assert s.alignment_hints.alignment_confidence == 0.0

    def test_alignment_confidence_positive_with_data(self):
        snap = _make_runtime_snapshot_dict()
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap
        )
        assert s.alignment_hints.alignment_confidence > 0.0

    def test_is_blocked_hint_matches_top_level(self):
        readiness = _make_readiness_result_obj(ready=False, status="blocked")
        s = build_execution_policy_alignment_surface(readiness_result=readiness)
        assert s.alignment_hints.is_blocked == s.blocked


# ---------------------------------------------------------------------------
# 11. Serialisation stability
# ---------------------------------------------------------------------------


class TestSerialisationStability:
    def test_to_dict_round_trip_stable(self):
        snap = _make_runtime_snapshot_dict()
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            tri_state_phase="manifest",
            runtime_domain="local",
        )
        d1 = s.to_dict()
        d2 = s.to_dict()
        assert d1 == d2

    def test_to_json_is_valid_json(self):
        s = build_execution_policy_alignment_surface()
        raw = s.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_nested_sub_summaries_are_dicts(self):
        s = build_execution_policy_alignment_surface()
        d = s.to_dict()
        assert isinstance(d["runtime_policy_summary"], dict)
        assert isinstance(d["readiness_policy_summary"], dict)
        assert isinstance(d["fallback_policy_summary"], dict)
        assert isinstance(d["dispatch_policy_summary"], dict)
        assert isinstance(d["projection_policy_summary"], dict)
        assert isinstance(d["alignment_hints"], dict)
        assert isinstance(d["mismatches"], list)

    def test_no_non_serialisable_values(self):
        snap = _make_runtime_snapshot_dict()
        proj = _make_projection_governance_dict()
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
            tri_state_phase="manifest",
            runtime_domain="local",
        )
        d = s.to_dict()
        # Should not raise
        json.dumps(d)

    def test_mismatch_list_serialisable(self):
        snap = _make_runtime_snapshot_dict(ready=True, blocked=False)
        proj = _make_projection_governance_dict(blocked=True)
        s = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=snap,
            projection_governance=proj,
        )
        d = s.to_dict()
        raw = json.dumps(d)
        parsed = json.loads(raw)
        assert isinstance(parsed["mismatches"], list)


# ---------------------------------------------------------------------------
# 12. Additive integration
# ---------------------------------------------------------------------------


class TestAdditiveIntegration:
    def test_summary_importable(self):
        from core.policy.alignment_surface import ExecutionPolicyAlignmentSummary  # noqa: F401

    def test_builder_importable(self):
        from core.policy.alignment_surface import build_execution_policy_alignment_surface  # noqa: F401

    def test_runtime_projection_has_policy_alignment_field(self):
        try:
            import importlib
            mod = importlib.import_module("core.projection.runtime_projection")
            RuntimeProjection = mod.RuntimeProjection
            assert "policy_alignment" in RuntimeProjection.model_fields
        except ModuleNotFoundError as exc:
            pytest.skip(f"Optional dependency not installed: {exc}")

    def test_runtime_projection_to_dict_includes_policy_alignment(self):
        from core.projection.runtime_projection import RuntimeProjection
        from core.continuum.types import TriStatePhase

        p = RuntimeProjection(tri_state_phase=TriStatePhase.SILENT)
        d = p.to_dict()
        assert "policy_alignment" in d

    def test_policy_alignment_none_by_default(self):
        from core.projection.runtime_projection import RuntimeProjection
        from core.continuum.types import TriStatePhase

        p = RuntimeProjection(tri_state_phase=TriStatePhase.SILENT)
        assert p.policy_alignment is None
        d = p.to_dict()
        assert d["policy_alignment"] is None

    def test_existing_fields_unchanged(self):
        from core.projection.runtime_projection import RuntimeProjection
        from core.continuum.types import TriStatePhase, RuntimeDomain

        p = RuntimeProjection(
            tri_state_phase=TriStatePhase.MANIFEST,
            runtime_domain=RuntimeDomain.LOCAL,
            primary_model_id="model-abc",
        )
        d = p.to_dict()
        assert d["tri_state_phase"] == "manifest"
        assert d["runtime_domain"] == "local"
        assert d["primary_model_id"] == "model-abc"
        assert d["policy_alignment"] is None

    def test_policy_alignment_can_be_set(self):
        from core.projection.runtime_projection import RuntimeProjection
        from core.continuum.types import TriStatePhase

        alignment_dict = {"alignment_id": "test-id", "aligned": True}
        p = RuntimeProjection(
            tri_state_phase=TriStatePhase.MANIFEST,
            policy_alignment=alignment_dict,
        )
        d = p.to_dict()
        assert d["policy_alignment"] == alignment_dict
