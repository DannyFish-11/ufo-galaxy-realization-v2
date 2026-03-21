"""tests/test_pr35_source_runtime_dispatch_orchestrator.py
============================================================
Tests for PR-35: Source Runtime Dispatch Orchestrator.

Coverage:
  1.  SourceDispatchMode — all enum values present.
  2.  SourceDispatchDecision — serialisation stability (to_dict/to_json/from_dict).
  3.  SourceDispatchDecision — stable field names.
  4.  SourceDispatchDecision — dispatch_id is UUID4.
  5.  SourceDispatchTarget — field correctness.
  6.  SourceDispatchPlan — serialisation stability.
  7.  SourceDispatchPlan — stable field names.
  8.  SourceDispatchResult — serialisation stability (to_dict/to_json/from_dict).
  9.  SourceDispatchResult — stable field names.
  10. SourceDispatchResult — to_compact_summary helper.
  11. SourceDispatchSummary — serialisation stability.
  12. build_source_dispatch_decision — convenience factory.
  13. build_source_dispatch_plan (contract level) — factory.
  14. build_source_dispatch_result — convenience factory.
  15. build_source_dispatch_summary — from result.
  16. failure_dispatch_result — minimal failure builder.
  17. select_dispatch_mode — force_local.
  18. select_dispatch_mode — force_remote with target.
  19. select_dispatch_mode — force_remote without target → fallback local.
  20. select_dispatch_mode — policy_alignment.blocked → blocked.
  21. select_dispatch_mode — can_expand_cross_device + target → remote_handoff.
  22. select_dispatch_mode — governance_snapshot execution_not_allowed → blocked.
  23. select_dispatch_mode — mesh_session multi-device active → staged_mesh.
  24. select_dispatch_mode — explicit target_device_id → remote_handoff.
  25. select_dispatch_mode — default → local.
  26. select_dispatch_target — explicit target_device_id.
  27. select_dispatch_target — from mesh_session participant.
  28. select_dispatch_target — no target → None.
  29. build_source_dispatch_plan (orchestrator level) — local mode.
  30. build_source_dispatch_plan (orchestrator level) — remote_handoff mode.
  31. build_source_dispatch_plan (orchestrator level) — blocked mode.
  32. build_source_dispatch_plan (orchestrator level) — graceful with no inputs.
  33. orchestrate_source_runtime_dispatch — local mode, executor unavailable.
  34. orchestrate_source_runtime_dispatch — blocked mode.
  35. orchestrate_source_runtime_dispatch — staged_mesh mode.
  36. orchestrate_source_runtime_dispatch — remote_handoff with no bridge → fallback_local.
  37. orchestrate_source_runtime_dispatch — graceful with None inputs.
  38. SourceDispatchOrchestrator.dispatch — returns SourceDispatchResult.
  39. SourceDispatchOrchestrator.plan — returns SourceDispatchPlan.
  40. SourceDispatchOrchestrator — graceful error handling.
  41. contracts package root re-exports.
  42. core.unified package re-exports.
  43. core.runtime package re-exports.
  44. Projection endpoint — GET /api/v1/runtime/source-dispatch-summary (additive).
  45. Graceful handling of partial / missing data.
  46. SourceDispatchResult.from_dict round-trip.
  47. SourceDispatchDecision.to_compact_summary helper.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy_alignment(
    blocked: bool = False,
    can_execute_locally: bool = True,
    can_expand_cross_device: bool = False,
) -> dict:
    return {
        "alignment_id": str(uuid.uuid4()),
        "aligned": not blocked,
        "blocked": blocked,
        "degraded": False,
        "alignment_hints": {
            "can_execute_locally": can_execute_locally,
            "can_expand_cross_device": can_expand_cross_device,
            "is_blocked": blocked,
            "preferred_domain": None,
        },
        "timestamp": 1700000000.0,
    }


def _make_governance_snapshot(execution_allowed: bool = True) -> dict:
    return {
        "snapshot_id": str(uuid.uuid4()),
        "execution_allowed": execution_allowed,
        "timestamp": 1700000000.0,
    }


def _make_mesh_session(participant_count: int = 1) -> dict:
    participants = [
        {
            "device_id": f"device_{i}",
            "runtime_id": f"runtime_{i}",
            "status": "active",
        }
        for i in range(participant_count)
    ]
    return {
        "session_id": "mesh_session_001",
        "mesh_id": "default_mesh",
        "participants": participants,
        "status": "active",
    }


# ---------------------------------------------------------------------------
# 1. SourceDispatchMode — enum values
# ---------------------------------------------------------------------------


class TestSourceDispatchModeEnum:
    def test_all_values_present(self):
        from contracts.source_dispatch import SourceDispatchMode

        expected = {"local", "remote_handoff", "staged_mesh", "blocked", "fallback_local", "unknown"}
        actual = {m.value for m in SourceDispatchMode}
        assert expected == actual

    def test_enum_values_are_strings(self):
        from contracts.source_dispatch import SourceDispatchMode

        for mode in SourceDispatchMode:
            assert isinstance(mode.value, str)


# ---------------------------------------------------------------------------
# 2. SourceDispatchDecision — serialisation stability
# ---------------------------------------------------------------------------


class TestSourceDispatchDecisionSerialisation:
    def test_to_dict_returns_dict(self):
        from contracts.source_dispatch import SourceDispatchDecision, SourceDispatchMode

        d = SourceDispatchDecision(trace_id="t1", mode=SourceDispatchMode.local)
        result = d.to_dict()
        assert isinstance(result, dict)

    def test_to_json_is_valid_json(self):
        from contracts.source_dispatch import SourceDispatchDecision, SourceDispatchMode

        d = SourceDispatchDecision(trace_id="t2", mode=SourceDispatchMode.remote_handoff)
        j = d.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_from_dict_round_trip(self):
        from contracts.source_dispatch import SourceDispatchDecision, SourceDispatchMode

        original = SourceDispatchDecision(
            trace_id="t3",
            task_id="task_rt",
            session_id="sess_rt",
            mode=SourceDispatchMode.local,
            decision_reason="force_local",
        )
        d = original.to_dict()
        restored = SourceDispatchDecision.from_dict(d)
        assert restored.trace_id == "t3"
        assert restored.task_id == "task_rt"
        assert restored.mode == SourceDispatchMode.local
        assert restored.decision_reason == "force_local"

    def test_to_json_indent(self):
        from contracts.source_dispatch import SourceDispatchDecision

        d = SourceDispatchDecision(trace_id="t4")
        j = d.to_json(indent=2)
        assert "\n" in j


# ---------------------------------------------------------------------------
# 3. SourceDispatchDecision — stable field names
# ---------------------------------------------------------------------------


class TestSourceDispatchDecisionFieldNames:
    REQUIRED_FIELDS = [
        "dispatch_id", "trace_id", "task_id", "session_id",
        "source_device_id", "source_runtime_id",
        "mode", "selected_target", "decision_reason",
        "policy_alignment", "governance_snapshot",
        "mesh_session", "handoff_envelope",
        "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.source_dispatch import SourceDispatchDecision

        d = SourceDispatchDecision(trace_id="t5").to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"

    def test_mode_serialised_as_string(self):
        from contracts.source_dispatch import SourceDispatchDecision, SourceDispatchMode

        d = SourceDispatchDecision(mode=SourceDispatchMode.remote_handoff).to_dict()
        assert d["mode"] == "remote_handoff"


# ---------------------------------------------------------------------------
# 4. SourceDispatchDecision — dispatch_id is UUID4
# ---------------------------------------------------------------------------


class TestSourceDispatchDecisionId:
    def test_dispatch_id_is_uuid4(self):
        from contracts.source_dispatch import SourceDispatchDecision

        d = SourceDispatchDecision()
        uuid.UUID(d.dispatch_id)  # should not raise

    def test_timestamp_is_float(self):
        from contracts.source_dispatch import SourceDispatchDecision

        d = SourceDispatchDecision()
        assert isinstance(d.timestamp, float)
        assert d.timestamp > 0


# ---------------------------------------------------------------------------
# 5. SourceDispatchTarget — field correctness
# ---------------------------------------------------------------------------


class TestSourceDispatchTarget:
    def test_to_dict(self):
        from contracts.source_dispatch import SourceDispatchTarget

        t = SourceDispatchTarget(
            target_device_id="device_001",
            target_runtime_id="runtime_001",
            selection_reason="explicit",
        )
        d = t.to_dict()
        assert d["target_device_id"] == "device_001"
        assert d["target_runtime_id"] == "runtime_001"
        assert d["selection_reason"] == "explicit"

    def test_none_fields_are_none(self):
        from contracts.source_dispatch import SourceDispatchTarget

        t = SourceDispatchTarget()
        d = t.to_dict()
        assert d["target_device_id"] is None
        assert d["handoff_envelope_id"] is None
        assert d["mesh_session_id"] is None


# ---------------------------------------------------------------------------
# 6. SourceDispatchPlan — serialisation stability
# ---------------------------------------------------------------------------


class TestSourceDispatchPlanSerialisation:
    def test_to_dict(self):
        from contracts.source_dispatch import SourceDispatchPlan, SourceDispatchMode

        p = SourceDispatchPlan(mode=SourceDispatchMode.local, ready=True)
        d = p.to_dict()
        assert isinstance(d, dict)
        assert d["mode"] == "local"
        assert d["ready"] is True

    def test_to_json_valid(self):
        from contracts.source_dispatch import SourceDispatchPlan

        p = SourceDispatchPlan()
        j = p.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict_round_trip(self):
        from contracts.source_dispatch import SourceDispatchPlan, SourceDispatchMode

        original = SourceDispatchPlan(
            trace_id="trace_plan",
            mode=SourceDispatchMode.remote_handoff,
            ready=False,
        )
        restored = SourceDispatchPlan.from_dict(original.to_dict())
        assert restored.trace_id == "trace_plan"
        assert restored.mode == SourceDispatchMode.remote_handoff
        assert restored.ready is False


# ---------------------------------------------------------------------------
# 7. SourceDispatchPlan — stable field names
# ---------------------------------------------------------------------------


class TestSourceDispatchPlanFieldNames:
    REQUIRED_FIELDS = [
        "plan_id", "dispatch_id", "trace_id", "task_id", "session_id",
        "mode", "selected_target", "handoff_envelope", "mesh_session",
        "policy_alignment", "governance_snapshot",
        "ready", "readiness_notes", "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.source_dispatch import SourceDispatchPlan

        d = SourceDispatchPlan().to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 8. SourceDispatchResult — serialisation stability
# ---------------------------------------------------------------------------


class TestSourceDispatchResultSerialisation:
    def test_to_dict_returns_dict(self):
        from contracts.source_dispatch import SourceDispatchResult, SourceDispatchMode

        r = SourceDispatchResult(trace_id="t1", mode=SourceDispatchMode.local, success=True)
        assert isinstance(r.to_dict(), dict)

    def test_to_json_valid(self):
        from contracts.source_dispatch import SourceDispatchResult

        r = SourceDispatchResult(trace_id="t2")
        j = r.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict_round_trip(self):
        from contracts.source_dispatch import SourceDispatchResult, SourceDispatchMode

        original = SourceDispatchResult(
            trace_id="t3",
            task_id="task_rt",
            mode=SourceDispatchMode.fallback_local,
            success=True,
        )
        restored = SourceDispatchResult.from_dict(original.to_dict())
        assert restored.trace_id == "t3"
        assert restored.mode == SourceDispatchMode.fallback_local
        assert restored.success is True


# ---------------------------------------------------------------------------
# 9. SourceDispatchResult — stable field names
# ---------------------------------------------------------------------------


class TestSourceDispatchResultFieldNames:
    REQUIRED_FIELDS = [
        "result_id", "dispatch_id", "trace_id", "task_id", "session_id",
        "source_device_id", "source_runtime_id",
        "mode", "selected_target", "success", "result",
        "execution_trace", "takeover_result",
        "governance_snapshot", "policy_alignment", "mesh_session",
        "errors", "decision_reason", "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.source_dispatch import SourceDispatchResult

        d = SourceDispatchResult(trace_id="t5").to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"

    def test_result_id_is_uuid4(self):
        from contracts.source_dispatch import SourceDispatchResult

        r = SourceDispatchResult()
        uuid.UUID(r.result_id)  # should not raise

    def test_timestamp_is_float(self):
        from contracts.source_dispatch import SourceDispatchResult

        r = SourceDispatchResult()
        assert isinstance(r.timestamp, float)
        assert r.timestamp > 0


# ---------------------------------------------------------------------------
# 10. SourceDispatchResult — to_compact_summary
# ---------------------------------------------------------------------------


class TestSourceDispatchResultCompactSummary:
    def test_compact_summary_keys(self):
        from contracts.source_dispatch import SourceDispatchResult, SourceDispatchMode

        r = SourceDispatchResult(
            trace_id="trace_cs",
            task_id="task_cs",
            mode=SourceDispatchMode.local,
            success=True,
        )
        s = r.to_compact_summary()
        assert s["trace_id"] == "trace_cs"
        assert s["task_id"] == "task_cs"
        assert s["mode"] == "local"
        assert s["success"] is True
        assert "result_id" in s
        assert "error_count" in s
        assert "has_execution_trace" in s
        assert "has_takeover_result" in s

    def test_compact_summary_mode_string(self):
        from contracts.source_dispatch import SourceDispatchResult, SourceDispatchMode

        r = SourceDispatchResult(mode=SourceDispatchMode.remote_handoff)
        s = r.to_compact_summary()
        assert s["mode"] == "remote_handoff"


# ---------------------------------------------------------------------------
# 11. SourceDispatchSummary — serialisation stability
# ---------------------------------------------------------------------------


class TestSourceDispatchSummary:
    def test_to_dict(self):
        from contracts.source_dispatch import SourceDispatchSummary, SourceDispatchMode

        s = SourceDispatchSummary(mode=SourceDispatchMode.local, success=True)
        d = s.to_dict()
        assert isinstance(d, dict)
        assert d["mode"] == "local"

    def test_to_json_valid(self):
        from contracts.source_dispatch import SourceDispatchSummary

        s = SourceDispatchSummary()
        j = s.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict(self):
        from contracts.source_dispatch import SourceDispatchSummary, SourceDispatchMode

        original = SourceDispatchSummary(
            trace_id="trace_s",
            mode=SourceDispatchMode.staged_mesh,
        )
        restored = SourceDispatchSummary.from_dict(original.to_dict())
        assert restored.trace_id == "trace_s"
        assert restored.mode == SourceDispatchMode.staged_mesh


# ---------------------------------------------------------------------------
# 12. build_source_dispatch_decision
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchDecision:
    def test_basic_build(self):
        from contracts.source_dispatch import (
            SourceDispatchMode,
            build_source_dispatch_decision,
        )

        d = build_source_dispatch_decision(
            trace_id="trace_build",
            mode=SourceDispatchMode.local,
            decision_reason="force_local",
        )
        assert d.trace_id == "trace_build"
        assert d.mode == SourceDispatchMode.local
        assert d.decision_reason == "force_local"

    def test_minimal_build(self):
        from contracts.source_dispatch import build_source_dispatch_decision

        d = build_source_dispatch_decision()
        assert d.dispatch_id is not None
        uuid.UUID(d.dispatch_id)

    def test_all_optional_fields_none(self):
        from contracts.source_dispatch import build_source_dispatch_decision

        d = build_source_dispatch_decision()
        assert d.trace_id is None
        assert d.task_id is None
        assert d.session_id is None
        assert d.selected_target is None


# ---------------------------------------------------------------------------
# 13. build_source_dispatch_plan (contract level)
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchPlanContract:
    def test_from_decision(self):
        from contracts.source_dispatch import (
            SourceDispatchMode,
            build_source_dispatch_decision,
            build_source_dispatch_plan,
        )

        decision = build_source_dispatch_decision(
            trace_id="trace_plan",
            mode=SourceDispatchMode.local,
        )
        plan = build_source_dispatch_plan(decision=decision)
        assert plan.trace_id == "trace_plan"
        assert plan.mode == SourceDispatchMode.local
        assert plan.dispatch_id == decision.dispatch_id

    def test_minimal_build(self):
        from contracts.source_dispatch import build_source_dispatch_plan

        plan = build_source_dispatch_plan()
        assert plan.plan_id is not None

    def test_ready_flag(self):
        from contracts.source_dispatch import build_source_dispatch_plan

        plan = build_source_dispatch_plan(ready=True)
        assert plan.ready is True


# ---------------------------------------------------------------------------
# 14. build_source_dispatch_result
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchResult:
    def test_basic_build(self):
        from contracts.source_dispatch import (
            SourceDispatchMode,
            build_source_dispatch_result,
        )

        r = build_source_dispatch_result(
            trace_id="trace_r",
            mode=SourceDispatchMode.local,
            success=True,
        )
        assert r.trace_id == "trace_r"
        assert r.success is True
        assert r.mode == SourceDispatchMode.local

    def test_minimal_build(self):
        from contracts.source_dispatch import build_source_dispatch_result

        r = build_source_dispatch_result()
        assert r.result_id is not None

    def test_errors_list(self):
        from contracts.source_dispatch import build_source_dispatch_result

        r = build_source_dispatch_result(errors=["err1", "err2"])
        assert len(r.errors) == 2


# ---------------------------------------------------------------------------
# 15. build_source_dispatch_summary
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchSummary:
    def test_from_result(self):
        from contracts.source_dispatch import (
            SourceDispatchMode,
            SourceDispatchResult,
            build_source_dispatch_summary,
        )

        result = SourceDispatchResult(
            trace_id="trace_sum",
            mode=SourceDispatchMode.local,
            success=True,
            errors=[],
        )
        summary = build_source_dispatch_summary(result=result)
        assert summary.trace_id == "trace_sum"
        assert summary.mode == SourceDispatchMode.local
        assert summary.success is True
        assert summary.error_count == 0

    def test_minimal_build(self):
        from contracts.source_dispatch import build_source_dispatch_summary

        s = build_source_dispatch_summary()
        assert s.summary_id is not None

    def test_overrides_result_fields(self):
        from contracts.source_dispatch import (
            SourceDispatchMode,
            SourceDispatchResult,
            build_source_dispatch_summary,
        )

        result = SourceDispatchResult(
            trace_id="orig_trace",
            mode=SourceDispatchMode.local,
        )
        # Override trace_id
        summary = build_source_dispatch_summary(
            result=result,
            trace_id="override_trace",
        )
        assert summary.trace_id == "override_trace"


# ---------------------------------------------------------------------------
# 16. failure_dispatch_result
# ---------------------------------------------------------------------------


class TestFailureDispatchResult:
    def test_basic_failure(self):
        from contracts.source_dispatch import SourceDispatchMode, failure_dispatch_result

        r = failure_dispatch_result(
            trace_id="trace_fail",
            reason="test_failure",
        )
        assert r.success is False
        assert r.trace_id == "trace_fail"
        assert "test_failure" in r.errors

    def test_minimal_failure(self):
        from contracts.source_dispatch import failure_dispatch_result

        r = failure_dispatch_result()
        assert r.success is False
        assert len(r.errors) > 0


# ---------------------------------------------------------------------------
# 17–25. select_dispatch_mode
# ---------------------------------------------------------------------------


class TestSelectDispatchMode:
    def test_force_local(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(force_local=True)
        assert mode == SourceDispatchMode.local
        assert "force_local" in reason

    def test_force_remote_with_target(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(force_remote=True, target_device_id="dev_001")
        assert mode == SourceDispatchMode.remote_handoff
        assert "force_remote" in reason

    def test_force_remote_without_target(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(force_remote=True)
        assert mode == SourceDispatchMode.local

    def test_policy_alignment_blocked(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        pa = _make_policy_alignment(blocked=True)
        mode, reason = select_dispatch_mode(policy_alignment=pa)
        assert mode == SourceDispatchMode.blocked
        assert "blocked" in reason

    def test_policy_alignment_can_expand_cross_device_with_target(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        pa = _make_policy_alignment(can_expand_cross_device=True)
        mode, reason = select_dispatch_mode(
            policy_alignment=pa,
            target_device_id="dev_001",
        )
        assert mode == SourceDispatchMode.remote_handoff

    def test_governance_snapshot_execution_not_allowed(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        gs = _make_governance_snapshot(execution_allowed=False)
        mode, reason = select_dispatch_mode(governance_snapshot=gs)
        assert mode == SourceDispatchMode.blocked
        assert "execution_not_allowed" in reason

    def test_mesh_session_multi_device_staged_mesh(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        ms = _make_mesh_session(participant_count=3)
        mode, reason = select_dispatch_mode(mesh_session=ms)
        assert mode == SourceDispatchMode.staged_mesh

    def test_explicit_target_device_remote_handoff(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(target_device_id="dev_002")
        assert mode == SourceDispatchMode.remote_handoff
        assert "target_device_specified" in reason

    def test_default_local(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode()
        assert mode == SourceDispatchMode.local
        assert "local" in reason


# ---------------------------------------------------------------------------
# 26–28. select_dispatch_target
# ---------------------------------------------------------------------------


class TestSelectDispatchTarget:
    def test_explicit_target_device(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_target

        target = select_dispatch_target(
            target_device_id="dev_001",
            target_runtime_id="rt_001",
        )
        assert target is not None
        assert target.target_device_id == "dev_001"
        assert target.target_runtime_id == "rt_001"
        assert "explicit" in (target.selection_reason or "")

    def test_from_mesh_session_participant(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_target

        ms = _make_mesh_session(participant_count=2)
        target = select_dispatch_target(mesh_session=ms)
        assert target is not None
        assert target.target_device_id == "device_0"
        assert "mesh_session" in (target.selection_reason or "")

    def test_no_target_returns_none(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_target

        target = select_dispatch_target()
        assert target is None

    def test_mesh_session_single_non_active_returns_none(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_target

        ms = {
            "session_id": "s1",
            "participants": [{"device_id": "dev", "status": "pending"}],
        }
        target = select_dispatch_target(mesh_session=ms)
        assert target is None


# ---------------------------------------------------------------------------
# 29–32. build_source_dispatch_plan (orchestrator level)
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchPlanOrchestrator:
    def test_local_mode(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        plan = build_source_dispatch_plan(
            trace_id="trace_plan_local",
            force_local=True,
            # Provide stubs to avoid auto-fetch
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert plan.mode == SourceDispatchMode.local

    def test_remote_handoff_mode(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        plan = build_source_dispatch_plan(
            trace_id="trace_plan_remote",
            task={"tool_name": "click", "args": {}},
            target_device_id="dev_remote",
            force_remote=True,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert plan.mode == SourceDispatchMode.remote_handoff

    def test_blocked_mode(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        pa = _make_policy_alignment(blocked=True)
        plan = build_source_dispatch_plan(
            trace_id="trace_plan_blocked",
            policy_alignment=pa,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert plan.mode == SourceDispatchMode.blocked
        assert plan.ready is False

    def test_graceful_with_no_inputs(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan

        # Should not raise even with no context
        plan = build_source_dispatch_plan(
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert plan is not None
        assert plan.plan_id is not None


# ---------------------------------------------------------------------------
# 33–37. orchestrate_source_runtime_dispatch
# ---------------------------------------------------------------------------


class TestOrchestrateSourceRuntimeDispatch:
    def test_local_mode_executor_unavailable(self):
        """Local mode returns a result even when OpenClawd is unavailable."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        from contracts.source_dispatch import SourceDispatchMode

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_local",
            task={"tool_name": "click", "args": {}},
            force_local=True,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert result is not None
        # Local mode should always produce a result
        assert result.mode in (SourceDispatchMode.local, SourceDispatchMode.fallback_local)
        assert isinstance(result.to_dict(), dict)

    def test_blocked_mode(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        from contracts.source_dispatch import SourceDispatchMode

        pa = _make_policy_alignment(blocked=True)
        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_blocked",
            policy_alignment=pa,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert result.mode == SourceDispatchMode.blocked
        assert result.success is False

    def test_staged_mesh_mode(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        from contracts.source_dispatch import SourceDispatchMode

        ms = _make_mesh_session(participant_count=3)
        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_mesh",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        assert result.mode == SourceDispatchMode.staged_mesh
        assert result.success is True
        assert result.result is not None
        assert result.result.get("action_taken") == "staged_mesh_plan_prepared"

    def test_remote_handoff_no_bridge_fallback_local(self):
        """Remote handoff without a real bridge falls back to local."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        from contracts.source_dispatch import SourceDispatchMode

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_remote",
            task={"tool_name": "screenshot", "args": {}},
            target_device_id="dev_remote",
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        # Either remote handoff succeeded (unlikely in test) or fell back
        assert result.mode in (
            SourceDispatchMode.remote_handoff,
            SourceDispatchMode.fallback_local,
            SourceDispatchMode.local,
        )
        assert isinstance(result.to_dict(), dict)

    def test_graceful_with_none_inputs(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        result = orchestrate_source_runtime_dispatch(
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert result is not None
        assert result.result_id is not None
        assert isinstance(result.to_dict(), dict)


# ---------------------------------------------------------------------------
# 38–40. SourceDispatchOrchestrator
# ---------------------------------------------------------------------------


class TestSourceDispatchOrchestrator:
    def test_dispatch_returns_result(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orchestrator = SourceDispatchOrchestrator()
        result = orchestrator.dispatch(
            trace_id="trace_handler",
            task={"tool_name": "click", "args": {}},
            force_local=True,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert result is not None
        assert result.result_id is not None

    def test_plan_returns_plan(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator
        from contracts.source_dispatch import SourceDispatchMode

        orchestrator = SourceDispatchOrchestrator()
        plan = orchestrator.plan(
            trace_id="trace_plan_h",
            force_local=True,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_session=None,
            mesh_memberships=None,
        )
        assert plan is not None
        assert plan.mode == SourceDispatchMode.local

    def test_graceful_error_handling(self):
        """Orchestrator should never raise even on unexpected error."""
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orchestrator = SourceDispatchOrchestrator()
        # Pass malformed context — should not raise
        result = orchestrator.dispatch(
            policy_alignment={"garbage": True},
            governance_snapshot={"garbage": True},
            mesh_session={"garbage": True},
            mesh_memberships=None,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# 41. contracts package root re-exports
# ---------------------------------------------------------------------------


class TestContractsPackageReExports:
    def test_source_dispatch_mode_exported(self):
        from contracts import SourceDispatchMode
        assert SourceDispatchMode is not None

    def test_source_dispatch_decision_exported(self):
        from contracts import SourceDispatchDecision
        assert SourceDispatchDecision is not None

    def test_source_dispatch_target_exported(self):
        from contracts import SourceDispatchTarget
        assert SourceDispatchTarget is not None

    def test_source_dispatch_plan_exported(self):
        from contracts import SourceDispatchPlan
        assert SourceDispatchPlan is not None

    def test_source_dispatch_result_exported(self):
        from contracts import SourceDispatchResult
        assert SourceDispatchResult is not None

    def test_source_dispatch_summary_exported(self):
        from contracts import SourceDispatchSummary
        assert SourceDispatchSummary is not None

    def test_build_source_dispatch_decision_exported(self):
        from contracts import build_source_dispatch_decision
        assert callable(build_source_dispatch_decision)

    def test_build_source_dispatch_result_exported(self):
        from contracts import build_source_dispatch_result
        assert callable(build_source_dispatch_result)

    def test_build_source_dispatch_summary_exported(self):
        from contracts import build_source_dispatch_summary
        assert callable(build_source_dispatch_summary)

    def test_failure_dispatch_result_exported(self):
        from contracts import failure_dispatch_result
        assert callable(failure_dispatch_result)


# ---------------------------------------------------------------------------
# 42. core.unified package re-exports
# ---------------------------------------------------------------------------


class TestCoreUnifiedReExports:
    def test_source_dispatch_mode_exported(self):
        from core.unified import SourceDispatchMode
        assert SourceDispatchMode is not None

    def test_source_dispatch_result_exported(self):
        from core.unified import SourceDispatchResult
        assert SourceDispatchResult is not None

    def test_source_dispatch_summary_exported(self):
        from core.unified import SourceDispatchSummary
        assert SourceDispatchSummary is not None

    def test_failure_dispatch_result_exported(self):
        from core.unified import failure_dispatch_result
        assert callable(failure_dispatch_result)


# ---------------------------------------------------------------------------
# 43. core.runtime package re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimeReExports:
    def test_orchestrator_exported(self):
        from core.runtime import SourceDispatchOrchestrator
        assert SourceDispatchOrchestrator is not None

    def test_select_dispatch_mode_exported(self):
        from core.runtime import select_dispatch_mode
        assert callable(select_dispatch_mode)

    def test_select_dispatch_target_exported(self):
        from core.runtime import select_dispatch_target
        assert callable(select_dispatch_target)

    def test_build_source_dispatch_plan_exported(self):
        from core.runtime import build_source_dispatch_plan
        assert callable(build_source_dispatch_plan)

    def test_orchestrate_source_runtime_dispatch_exported(self):
        from core.runtime import orchestrate_source_runtime_dispatch
        assert callable(orchestrate_source_runtime_dispatch)

    def test_pr34_exports_still_present(self):
        """Ensure PR-34 exports are not broken by PR-35 changes."""
        from core.runtime import (
            TargetTakeoverHandler,
            execute_local_takeover,
            normalize_handoff_envelope,
        )
        assert TargetTakeoverHandler is not None
        assert callable(execute_local_takeover)
        assert callable(normalize_handoff_envelope)


# ---------------------------------------------------------------------------
# 44. Projection endpoint — GET /api/v1/runtime/source-dispatch-summary
# ---------------------------------------------------------------------------


class TestSourceDispatchSummaryEndpoint:
    def test_endpoint_exists_and_returns_200(self):
        """GET /api/v1/runtime/source-dispatch-summary should return 200."""
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        from core.routes.projection import create_router

        app = FastAPI()
        router = create_router()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/api/v1/runtime/source-dispatch-summary")
        assert response.status_code == 200

    def test_endpoint_returns_json_with_mode(self):
        """GET /api/v1/runtime/source-dispatch-summary returns JSON with mode field."""
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        from core.routes.projection import create_router

        app = FastAPI()
        router = create_router()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/api/v1/runtime/source-dispatch-summary")
        body = response.json()
        assert "mode" in body
        assert "success" in body or "summary_id" in body


# ---------------------------------------------------------------------------
# 45. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------


class TestGracefulPartialInputs:
    def test_decision_with_all_none(self):
        from contracts.source_dispatch import build_source_dispatch_decision

        d = build_source_dispatch_decision()
        assert d is not None
        assert d.dispatch_id is not None

    def test_result_with_all_none(self):
        from contracts.source_dispatch import build_source_dispatch_result

        r = build_source_dispatch_result()
        assert r is not None
        assert r.result_id is not None

    def test_summary_with_all_none(self):
        from contracts.source_dispatch import build_source_dispatch_summary

        s = build_source_dispatch_summary()
        assert s is not None
        assert s.summary_id is not None

    def test_failure_with_minimal_args(self):
        from contracts.source_dispatch import failure_dispatch_result

        r = failure_dispatch_result()
        assert r.success is False

    def test_orchestration_with_empty_dict_context(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        result = orchestrate_source_runtime_dispatch(
            policy_alignment={},
            governance_snapshot={},
            mesh_session={},
            mesh_memberships=[],
        )
        assert result is not None


# ---------------------------------------------------------------------------
# 46. SourceDispatchResult.from_dict round-trip
# ---------------------------------------------------------------------------


class TestSourceDispatchResultFromDict:
    def test_round_trip_all_fields(self):
        from contracts.source_dispatch import SourceDispatchResult, SourceDispatchMode

        original = SourceDispatchResult(
            trace_id="trace_rt",
            task_id="task_rt",
            session_id="sess_rt",
            source_device_id="src_device",
            source_runtime_id="src_runtime",
            mode=SourceDispatchMode.remote_handoff,
            success=True,
            result={"action": "click"},
            errors=["minor_warning"],
            decision_reason="remote_handoff:success",
            metadata={"custom": "value"},
        )
        d = original.to_dict()
        restored = SourceDispatchResult.from_dict(d)

        assert restored.trace_id == original.trace_id
        assert restored.task_id == original.task_id
        assert restored.session_id == original.session_id
        assert restored.source_device_id == original.source_device_id
        assert restored.mode == SourceDispatchMode.remote_handoff
        assert restored.success is True
        assert restored.errors == ["minor_warning"]
        assert restored.decision_reason == "remote_handoff:success"

    def test_round_trip_extra_fields_tolerated(self):
        from contracts.source_dispatch import SourceDispatchResult

        data = {
            "result_id": str(uuid.uuid4()),
            "trace_id": "trace_extra",
            "mode": "local",
            "success": False,
            "errors": [],
            "unknown_future_field": "value_that_should_be_tolerated",
        }
        r = SourceDispatchResult.from_dict(data)
        assert r.trace_id == "trace_extra"


# ---------------------------------------------------------------------------
# 47. SourceDispatchDecision.to_compact_summary
# ---------------------------------------------------------------------------


class TestSourceDispatchDecisionCompactSummary:
    def test_compact_summary_keys(self):
        from contracts.source_dispatch import SourceDispatchDecision, SourceDispatchMode

        d = SourceDispatchDecision(
            trace_id="trace_cs",
            task_id="task_cs",
            mode=SourceDispatchMode.remote_handoff,
            decision_reason="explicit_target",
        )
        s = d.to_compact_summary()
        assert s["trace_id"] == "trace_cs"
        assert s["task_id"] == "task_cs"
        assert s["mode"] == "remote_handoff"
        assert s["decision_reason"] == "explicit_target"
        assert "dispatch_id" in s
        assert "has_target" in s
        assert "has_policy_alignment" in s
        assert "timestamp" in s

    def test_compact_summary_mode_string(self):
        from contracts.source_dispatch import SourceDispatchDecision, SourceDispatchMode

        d = SourceDispatchDecision(mode=SourceDispatchMode.staged_mesh)
        s = d.to_compact_summary()
        assert s["mode"] == "staged_mesh"
