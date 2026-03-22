#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr21_unified_execution_decision.py
==============================================

PR-21 — Unify Execution Decision, Remote Mode Policy, and Fallback Governance

Tests are grouped by category; 71 tests total covering:

ExecutionPath enum
  - All values are stable strings and round-trip via value.

FallbackKind enum
  - All 7 values are stable strings and round-trip via value.

UnifiedExecutionDecision
  - Construction defaults and structural field completeness.
  - to_dict / from_dict round-trip.
  - Local execution path represented canonically.
  - cross_device path with agent_runtime and command_only remote modes.
  - Hybrid execution path with orchestration_active flag.
  - None / no-op execution path.
  - command_only vs agent_runtime mode captured explicitly.
  - is_downgrade and preferred_path downgrade-tracking fields.
  - execution_reason rationale field stored and round-trips.

FallbackDecisionRecord
  - Construction defaults (no fallback case).
  - to_dict / from_dict round-trip.
  - has_fallback auto-derived from fallback_kinds.
  - machine_readable_codes auto-derived from fallback_kinds.
  - human_readable_summary auto-derived; explicit value not overwritten.
  - agent_runtime → command_only downgrade captured.
  - remote → local fallback captured.
  - native_multimodal → text downgrade captured.
  - Orchestration downgrade captured.
  - Blocked / no-op governance result captured.
  - Model fallback reason captured.
  - Multiple fallback kinds in one record.
  - Partial / missing data degrades gracefully in from_dict.

UnifiedControlPlan integration
  - unified_execution_decision field populated by builder.
  - fallback_decision_record populated when fallback_kinds given; None otherwise.
  - to_dict / from_dict round-trips preserve both new fields.

unified_control_plan_summary
  - Exposes execution_reason, is_execution_downgrade, remote_execution_mode.
  - Exposes has_fallback and fallback_kinds.
  - None plan returns None.

Backward compatibility
  - Minimal builder call (no PR-21 kwargs) still works.
  - Existing ChosenExecutionDecision unaffected.
  - Existing fallback_level / fallback_reason unaffected.

OpenClawd integration
  - _build_unified_control_plan accepts all PR-21 kwargs without error.
  - unified_execution_decision and fallback_decision_record present in output.

Authority and boundary invariants
  - decision_authority always "subject_decision_authority".
  - substrate_role distinct from orchestration_role.
  - orchestration_active does not change authority chain.

Serialisation safety
  - All new structures produce JSON-serialisable output.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# 1. ExecutionPath enum — values and serialisation stability
# ---------------------------------------------------------------------------

class TestExecutionPathEnum:
    def test_all_values_are_strings(self):
        from core.schemas.unified_control_plan import ExecutionPath
        for member in ExecutionPath:
            assert isinstance(member.value, str)
            assert member.value

    def test_known_values_stable(self):
        from core.schemas.unified_control_plan import ExecutionPath
        assert ExecutionPath.LOCAL.value == "local"
        assert ExecutionPath.CROSS_DEVICE.value == "cross_device"
        assert ExecutionPath.HYBRID.value == "hybrid"
        assert ExecutionPath.NONE.value == "none"

    def test_roundtrip_via_value(self):
        from core.schemas.unified_control_plan import ExecutionPath
        for member in ExecutionPath:
            assert ExecutionPath(member.value) is member


# ---------------------------------------------------------------------------
# 2. FallbackKind enum — values and serialisation stability
# ---------------------------------------------------------------------------

class TestFallbackKindEnum:
    def test_all_values_are_strings(self):
        from core.schemas.unified_control_plan import FallbackKind
        for member in FallbackKind:
            assert isinstance(member.value, str)
            assert member.value

    def test_known_values_stable(self):
        from core.schemas.unified_control_plan import FallbackKind
        assert FallbackKind.MODEL_CAPABILITY_FALLBACK.value == "model_capability_fallback"
        assert FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value == "native_multimodal_to_text"
        assert FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value == "agent_runtime_to_command_only"
        assert FallbackKind.REMOTE_TO_LOCAL.value == "remote_to_local"
        assert FallbackKind.ORCHESTRATION_DOWNGRADE.value == "orchestration_downgrade"
        assert FallbackKind.BLOCKED_NO_OP.value == "blocked_no_op"
        assert FallbackKind.OTHER.value == "other"

    def test_roundtrip_via_value(self):
        from core.schemas.unified_control_plan import FallbackKind
        for member in FallbackKind:
            assert FallbackKind(member.value) is member


# ---------------------------------------------------------------------------
# 3–4. UnifiedExecutionDecision — construction and round-trip
# ---------------------------------------------------------------------------

class TestUnifiedExecutionDecisionBasic:
    def test_default_construction(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision, ExecutionPath
        ued = UnifiedExecutionDecision()
        assert ued.execution_path == ExecutionPath.LOCAL.value
        assert ued.delegation_point is None
        assert ued.remote_execution_mode is None
        assert ued.target_device_ids == []
        assert ued.orchestration_active is False
        assert ued.execution_reason is None
        assert ued.fallback_intent is None
        assert ued.is_downgrade is False
        assert ued.preferred_path is None

    def test_to_dict_has_required_keys(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision()
        d = ued.to_dict()
        required = {
            "execution_path", "delegation_point", "remote_execution_mode",
            "target_device_ids", "orchestration_active",
            "execution_reason", "fallback_intent", "is_downgrade", "preferred_path",
        }
        assert required.issubset(d.keys())

    def test_to_dict_from_dict_roundtrip(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            target_device_ids=["device-abc"],
            orchestration_active=False,
            execution_reason="device_id present → single_remote delegation",
            fallback_intent=None,
            is_downgrade=False,
            preferred_path=None,
        )
        restored = UnifiedExecutionDecision.from_dict(ued.to_dict())
        assert restored.execution_path == ued.execution_path
        assert restored.delegation_point == ued.delegation_point
        assert restored.remote_execution_mode == ued.remote_execution_mode
        assert restored.target_device_ids == ued.target_device_ids
        assert restored.execution_reason == ued.execution_reason
        assert restored.is_downgrade == ued.is_downgrade


# ---------------------------------------------------------------------------
# 5. Local execution path represented canonically
# ---------------------------------------------------------------------------

class TestLocalExecutionPath:
    def test_local_path_fields(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision, ExecutionPath
        ued = UnifiedExecutionDecision(
            execution_path=ExecutionPath.LOCAL.value,
            delegation_point="local",
            remote_execution_mode=None,
            execution_reason="no_device_id local_manifestation",
        )
        assert ued.execution_path == "local"
        assert ued.remote_execution_mode is None
        assert ued.orchestration_active is False
        assert ued.is_downgrade is False

    def test_local_path_serialisable(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="local",
            execution_reason="local_only",
        )
        json.dumps(ued.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# 6. Cross-device execution path with remote mode
# ---------------------------------------------------------------------------

class TestCrossDeviceExecutionPath:
    def test_cross_device_path_fields(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            target_device_ids=["phone-01"],
            execution_reason="device_id=phone-01 → single_remote delegation",
        )
        assert ued.execution_path == "cross_device"
        assert ued.remote_execution_mode == "agent_runtime"
        assert "phone-01" in ued.target_device_ids

    def test_command_only_cross_device(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
            target_device_ids=["tablet-02"],
        )
        assert ued.remote_execution_mode == "command_only"


# ---------------------------------------------------------------------------
# 7. Hybrid execution path with orchestration
# ---------------------------------------------------------------------------

class TestHybridExecutionPath:
    def test_hybrid_path_fields(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="hybrid",
            delegation_point="multi_device_orchestration",
            orchestration_active=True,
            target_device_ids=["phone-01", "tablet-02"],
            execution_reason="multi_device goal → orchestration",
        )
        assert ued.execution_path == "hybrid"
        assert ued.orchestration_active is True
        assert len(ued.target_device_ids) == 2

    def test_hybrid_serialisable(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="hybrid",
            orchestration_active=True,
            target_device_ids=["d1", "d2"],
        )
        json.dumps(ued.to_dict())


# ---------------------------------------------------------------------------
# 8. None / no-op execution path
# ---------------------------------------------------------------------------

class TestNoneExecutionPath:
    def test_none_path_fields(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision, ExecutionPath
        ued = UnifiedExecutionDecision(
            execution_path=ExecutionPath.NONE.value,
            execution_reason="observe_only action_level=observe",
        )
        assert ued.execution_path == "none"
        assert ued.remote_execution_mode is None
        assert ued.orchestration_active is False


# ---------------------------------------------------------------------------
# 9. command_only vs agent_runtime mode captured explicitly
# ---------------------------------------------------------------------------

class TestRemoteModeCaptured:
    def test_agent_runtime_mode(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            remote_execution_mode="agent_runtime",
        )
        d = ued.to_dict()
        assert d["remote_execution_mode"] == "agent_runtime"

    def test_command_only_mode(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            remote_execution_mode="command_only",
        )
        d = ued.to_dict()
        assert d["remote_execution_mode"] == "command_only"

    def test_none_mode_for_local(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(execution_path="local")
        assert ued.to_dict()["remote_execution_mode"] is None


# ---------------------------------------------------------------------------
# 10. is_downgrade and preferred_path fields
# ---------------------------------------------------------------------------

class TestDowngradeTracking:
    def test_downgrade_fields_present(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            remote_execution_mode="command_only",
            is_downgrade=True,
            preferred_path="agent_runtime",
            fallback_intent="agent_runtime unavailable → command_only",
        )
        assert ued.is_downgrade is True
        assert ued.preferred_path == "agent_runtime"
        assert ued.fallback_intent is not None

    def test_no_downgrade_default(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision()
        assert ued.is_downgrade is False
        assert ued.preferred_path is None


# ---------------------------------------------------------------------------
# 11. execution_reason present
# ---------------------------------------------------------------------------

class TestExecutionReason:
    def test_reason_stored(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        reason = "device_id=tablet-01 → single_remote delegation via agent_runtime"
        ued = UnifiedExecutionDecision(execution_reason=reason)
        assert ued.execution_reason == reason
        assert ued.to_dict()["execution_reason"] == reason

    def test_reason_round_trips(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        reason = "local_only: no device_id, action_level=execute"
        ued = UnifiedExecutionDecision(execution_reason=reason)
        restored = UnifiedExecutionDecision.from_dict(ued.to_dict())
        assert restored.execution_reason == reason


# ---------------------------------------------------------------------------
# 12–13. FallbackDecisionRecord — defaults and round-trip
# ---------------------------------------------------------------------------

class TestFallbackDecisionRecordBasic:
    def test_default_construction_no_fallback(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord
        fdr = FallbackDecisionRecord()
        assert fdr.has_fallback is False
        assert fdr.fallback_kinds == []
        assert fdr.machine_readable_codes == []
        assert fdr.human_readable_summary is None

    def test_to_dict_has_required_keys(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord
        fdr = FallbackDecisionRecord()
        d = fdr.to_dict()
        required = {
            "has_fallback", "fallback_kinds",
            "model_fallback_reason", "multimodal_downgrade_reason",
            "agent_to_command_reason", "remote_to_local_reason",
            "orchestration_downgrade_reason", "blocked_reason",
            "human_readable_summary", "machine_readable_codes",
        }
        assert required.issubset(d.keys())

    def test_to_dict_from_dict_roundtrip(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.REMOTE_TO_LOCAL.value],
            remote_to_local_reason="remote device unavailable",
        )
        restored = FallbackDecisionRecord.from_dict(fdr.to_dict())
        assert restored.has_fallback == fdr.has_fallback
        assert restored.fallback_kinds == fdr.fallback_kinds
        assert restored.remote_to_local_reason == fdr.remote_to_local_reason


# ---------------------------------------------------------------------------
# 14–16. FallbackDecisionRecord auto-derivation
# ---------------------------------------------------------------------------

class TestFallbackAutoDerivation:
    def test_has_fallback_auto_derived_from_kinds(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.REMOTE_TO_LOCAL.value],
        )
        assert fdr.has_fallback is True

    def test_machine_readable_codes_auto_derived(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        kinds = [FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value]
        fdr = FallbackDecisionRecord(fallback_kinds=kinds)
        assert fdr.machine_readable_codes == kinds

    def test_human_readable_summary_auto_derived(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.REMOTE_TO_LOCAL.value],
        )
        assert fdr.human_readable_summary is not None
        assert "remote_to_local" in fdr.human_readable_summary

    def test_explicit_summary_not_overwritten(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        custom = "Custom summary text"
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.OTHER.value],
            human_readable_summary=custom,
        )
        assert fdr.human_readable_summary == custom


# ---------------------------------------------------------------------------
# 17. agent_runtime → command_only downgrade captured
# ---------------------------------------------------------------------------

class TestAgentToCommandDowngrade:
    def test_agent_to_command_fallback_kind(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value],
            agent_to_command_reason="target does not support agent_runtime",
        )
        assert fdr.has_fallback is True
        assert FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value in fdr.fallback_kinds
        assert fdr.agent_to_command_reason is not None

    def test_serialisable(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value],
            agent_to_command_reason="capability mismatch",
        )
        json.dumps(fdr.to_dict())


# ---------------------------------------------------------------------------
# 18. remote → local fallback captured
# ---------------------------------------------------------------------------

class TestRemoteToLocalFallback:
    def test_remote_to_local_kind(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.REMOTE_TO_LOCAL.value],
            remote_to_local_reason="all remote targets unavailable",
        )
        assert fdr.has_fallback is True
        assert FallbackKind.REMOTE_TO_LOCAL.value in fdr.fallback_kinds
        assert fdr.remote_to_local_reason == "all remote targets unavailable"


# ---------------------------------------------------------------------------
# 19. native_multimodal → text downgrade captured
# ---------------------------------------------------------------------------

class TestMultimodalToTextDowngrade:
    def test_multimodal_to_text_kind(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            multimodal_downgrade_reason="no native multimodal provider available",
        )
        assert fdr.has_fallback is True
        assert FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value in fdr.fallback_kinds
        assert fdr.multimodal_downgrade_reason is not None


# ---------------------------------------------------------------------------
# 20. Orchestration downgrade captured
# ---------------------------------------------------------------------------

class TestOrchestrationDowngrade:
    def test_orchestration_downgrade_kind(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.ORCHESTRATION_DOWNGRADE.value],
            orchestration_downgrade_reason="only one device reachable, orchestration simplified",
        )
        assert fdr.has_fallback is True
        assert FallbackKind.ORCHESTRATION_DOWNGRADE.value in fdr.fallback_kinds
        assert fdr.orchestration_downgrade_reason is not None


# ---------------------------------------------------------------------------
# 21. Blocked / no-op governance result captured
# ---------------------------------------------------------------------------

class TestBlockedNoOpGovernance:
    def test_blocked_no_op_kind(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.BLOCKED_NO_OP.value],
            blocked_reason="action_level=observe governance blocked execution",
        )
        assert fdr.has_fallback is True
        assert FallbackKind.BLOCKED_NO_OP.value in fdr.fallback_kinds
        assert fdr.blocked_reason is not None


# ---------------------------------------------------------------------------
# 22. Model fallback reason captured
# ---------------------------------------------------------------------------

class TestModelFallbackReason:
    def test_model_fallback_kind(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.MODEL_CAPABILITY_FALLBACK.value],
            model_fallback_reason="primary model quota exceeded, using fallback model",
        )
        assert fdr.has_fallback is True
        assert FallbackKind.MODEL_CAPABILITY_FALLBACK.value in fdr.fallback_kinds
        assert fdr.model_fallback_reason is not None


# ---------------------------------------------------------------------------
# 23. Multiple fallback kinds in one record
# ---------------------------------------------------------------------------

class TestMultipleFallbackKinds:
    def test_multiple_kinds(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        kinds = [
            FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value,
            FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value,
        ]
        fdr = FallbackDecisionRecord(
            fallback_kinds=kinds,
            multimodal_downgrade_reason="no native mm provider",
            agent_to_command_reason="target thin client",
        )
        assert fdr.has_fallback is True
        assert len(fdr.fallback_kinds) == 2
        assert all(k in fdr.machine_readable_codes for k in kinds)

    def test_multiple_kinds_serialisable(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[
                FallbackKind.REMOTE_TO_LOCAL.value,
                FallbackKind.ORCHESTRATION_DOWNGRADE.value,
            ],
        )
        json.dumps(fdr.to_dict())


# ---------------------------------------------------------------------------
# 24–25. UnifiedControlPlan — new PR-21 fields populated by builder
# ---------------------------------------------------------------------------

class TestUnifiedControlPlanWithPR21:
    def test_unified_execution_decision_field_present(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            execution_path="local",
            execution_reason="local_only request",
        )
        assert plan.unified_execution_decision is not None
        assert plan.unified_execution_decision.execution_path == "local"
        assert plan.unified_execution_decision.execution_reason == "local_only request"

    def test_fallback_decision_record_field_present_when_fallback(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackKind
        plan = build_unified_control_plan(
            execution_path="local",
            fallback_kinds=[FallbackKind.REMOTE_TO_LOCAL.value],
            remote_to_local_reason="device unavailable",
        )
        assert plan.fallback_decision_record is not None
        assert plan.fallback_decision_record.has_fallback is True

    def test_fallback_decision_record_none_when_no_fallback(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(execution_path="local")
        assert plan.fallback_decision_record is None


# ---------------------------------------------------------------------------
# 26–27. to_dict / from_dict with new fields
# ---------------------------------------------------------------------------

class TestUnifiedControlPlanRoundTrip:
    def test_to_dict_includes_unified_execution_decision(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            execution_path="cross_device",
            remote_execution_mode="agent_runtime",
            execution_reason="device_id present",
        )
        d = plan.to_dict()
        assert "unified_execution_decision" in d
        assert d["unified_execution_decision"] is not None
        assert d["unified_execution_decision"]["execution_path"] == "cross_device"

    def test_to_dict_includes_fallback_decision_record(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackKind
        plan = build_unified_control_plan(
            fallback_kinds=[FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value],
            agent_to_command_reason="thin client target",
        )
        d = plan.to_dict()
        assert "fallback_decision_record" in d
        assert d["fallback_decision_record"] is not None
        assert d["fallback_decision_record"]["has_fallback"] is True

    def test_from_dict_round_trip_preserves_ued(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, UnifiedControlPlan
        plan = build_unified_control_plan(
            execution_path="hybrid",
            orchestration_active=True,
            execution_reason="multi_device goal",
        )
        restored = UnifiedControlPlan.from_dict(plan.to_dict())
        assert restored.unified_execution_decision is not None
        assert restored.unified_execution_decision.execution_path == "hybrid"
        assert restored.unified_execution_decision.orchestration_active is True

    def test_from_dict_round_trip_preserves_fdr(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, UnifiedControlPlan, FallbackKind
        plan = build_unified_control_plan(
            fallback_kinds=[FallbackKind.REMOTE_TO_LOCAL.value],
            remote_to_local_reason="device offline",
        )
        restored = UnifiedControlPlan.from_dict(plan.to_dict())
        assert restored.fallback_decision_record is not None
        assert restored.fallback_decision_record.remote_to_local_reason == "device offline"


# ---------------------------------------------------------------------------
# 28. unified_control_plan_summary — exposes execution_reason and fallback
# ---------------------------------------------------------------------------

class TestUnifiedControlPlanSummary:
    def test_summary_has_execution_reason(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary
        plan = build_unified_control_plan(
            execution_path="cross_device",
            execution_reason="device_id=phone-01",
        )
        summary = unified_control_plan_summary(plan)
        assert summary is not None
        assert summary["execution_reason"] == "device_id=phone-01"

    def test_summary_has_fallback_fields(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary, FallbackKind
        plan = build_unified_control_plan(
            fallback_kinds=[FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value],
        )
        summary = unified_control_plan_summary(plan)
        assert summary is not None
        assert summary["has_fallback"] is True
        assert FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value in summary["fallback_kinds"]

    def test_summary_no_fallback_defaults(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary
        plan = build_unified_control_plan(execution_path="local")
        summary = unified_control_plan_summary(plan)
        assert summary is not None
        assert summary["has_fallback"] is False
        assert summary["fallback_kinds"] == []

    def test_summary_has_remote_mode(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary
        plan = build_unified_control_plan(
            execution_path="cross_device",
            remote_execution_mode="command_only",
        )
        summary = unified_control_plan_summary(plan)
        assert summary["remote_execution_mode"] == "command_only"

    def test_summary_is_execution_downgrade(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary
        plan = build_unified_control_plan(
            execution_path="cross_device",
            remote_execution_mode="command_only",
            is_execution_downgrade=True,
            preferred_execution_path="agent_runtime",
        )
        summary = unified_control_plan_summary(plan)
        assert summary["is_execution_downgrade"] is True

    def test_summary_none_plan_returns_none(self):
        from core.schemas.unified_control_plan import unified_control_plan_summary
        assert unified_control_plan_summary(None) is None


# ---------------------------------------------------------------------------
# 29. build_unified_control_plan — minimal call (no PR-21 kwargs) still works
# ---------------------------------------------------------------------------

class TestBackwardCompatibleBuilder:
    def test_minimal_call_succeeds(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan()
        assert plan is not None
        assert plan.unified_execution_decision is not None
        assert plan.fallback_decision_record is None

    def test_existing_kwargs_still_accepted(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            target_device_ids=["d1"],
            fallback_level="local_fallback",
            fallback_reason="device unavailable",
            lifecycle_target="succeeded",
        )
        assert plan.chosen_execution_decision.execution_path == "cross_device"
        assert plan.fallback_level == "local_fallback"


# ---------------------------------------------------------------------------
# 30. OpenClawd._build_unified_control_plan — accepts PR-21 kwargs
# ---------------------------------------------------------------------------

class TestOpenClawdBuildUCP:
    def test_accepts_pr21_kwargs_without_error(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
        result = oc._build_unified_control_plan(
            execution_path="cross_device",
            remote_execution_mode="command_only",
            execution_reason="device_id present",
            is_execution_downgrade=True,
            preferred_execution_path="agent_runtime",
            fallback_kinds=["agent_runtime_to_command_only"],
            agent_to_command_reason="thin client target",
        )
        # Should return a dict (not None) on success
        assert result is not None
        assert isinstance(result, dict)

    def test_pr21_fields_in_output(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
        result = oc._build_unified_control_plan(
            execution_path="local",
            execution_reason="local_manifestation",
        )
        assert result is not None
        assert "unified_execution_decision" in result
        assert result["unified_execution_decision"]["execution_path"] == "local"

    def test_fallback_record_in_output_when_kinds_given(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
        result = oc._build_unified_control_plan(
            execution_path="local",
            fallback_kinds=["remote_to_local"],
            remote_to_local_reason="device offline",
        )
        assert result is not None
        assert result["fallback_decision_record"] is not None
        assert result["fallback_decision_record"]["has_fallback"] is True


# ---------------------------------------------------------------------------
# 31. Authority invariant — decision_authority always subject_decision_authority
# ---------------------------------------------------------------------------

class TestAuthorityInvariant:
    def test_authority_role_is_subject_decision_authority(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(execution_path="local")
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE
        assert plan.authority_chain.decision_authority == "subject_decision_authority"

    def test_authority_role_in_to_dict(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan()
        d = plan.to_dict()
        assert d["authority_chain"]["decision_authority"] == "subject_decision_authority"


# ---------------------------------------------------------------------------
# 32. Orchestration/substrate boundary — roles distinct
# ---------------------------------------------------------------------------

class TestOrchestrationSubstrateBoundary:
    def test_substrate_role_distinct_from_orchestration(self):
        from core.schemas.unified_control_plan import (
            build_unified_control_plan,
            SUBSTRATE_ROLE,
            ORCHESTRATION_ROLE,
        )
        plan = build_unified_control_plan()
        chain = plan.authority_chain
        assert chain.substrate_role != chain.orchestration_role
        assert chain.substrate_role == SUBSTRATE_ROLE
        assert chain.orchestration_role == ORCHESTRATION_ROLE

    def test_orchestration_active_does_not_change_authority(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(
            execution_path="hybrid",
            orchestration_active=True,
        )
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_orchestration_active_reflected_in_ued(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            execution_path="hybrid",
            orchestration_active=True,
        )
        assert plan.unified_execution_decision is not None
        assert plan.unified_execution_decision.orchestration_active is True


# ---------------------------------------------------------------------------
# 33. Serialisation safety — all new structures JSON-serialisable
# ---------------------------------------------------------------------------

class TestSerialisationSafety:
    def test_unified_execution_decision_json_safe(self):
        from core.schemas.unified_control_plan import UnifiedExecutionDecision
        ued = UnifiedExecutionDecision(
            execution_path="cross_device",
            remote_execution_mode="agent_runtime",
            target_device_ids=["d1", "d2"],
            orchestration_active=False,
            execution_reason="test",
            is_downgrade=False,
        )
        assert json.dumps(ued.to_dict()) is not None

    def test_fallback_decision_record_json_safe(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[
                FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value,
                FallbackKind.REMOTE_TO_LOCAL.value,
            ],
            multimodal_downgrade_reason="no native provider",
            remote_to_local_reason="device down",
        )
        assert json.dumps(fdr.to_dict()) is not None

    def test_full_plan_json_safe(self):
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackKind
        plan = build_unified_control_plan(
            execution_path="cross_device",
            remote_execution_mode="command_only",
            execution_reason="thin client target",
            is_execution_downgrade=True,
            preferred_execution_path="agent_runtime",
            fallback_kinds=[FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY.value],
            agent_to_command_reason="thin client",
        )
        assert json.dumps(plan.to_dict()) is not None


# ---------------------------------------------------------------------------
# 34. Backward compatibility — ChosenExecutionDecision unaffected
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_chosen_execution_decision_still_present(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
        )
        ced = plan.chosen_execution_decision
        assert ced.execution_path == "cross_device"
        assert ced.delegation_point == "single_remote"

    def test_chosen_execution_decision_in_to_dict(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(execution_path="local")
        d = plan.to_dict()
        assert "chosen_execution_decision" in d
        assert d["chosen_execution_decision"]["execution_path"] == "local"

    def test_existing_fallback_level_unaffected(self):
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            fallback_level="local_fallback",
            fallback_reason="device unavailable",
        )
        assert plan.fallback_level == "local_fallback"
        assert plan.fallback_reason == "device unavailable"


# ---------------------------------------------------------------------------
# 35. FallbackDecisionRecord — from_dict with partial/missing data degrades
# ---------------------------------------------------------------------------

class TestFallbackDecisionRecordDegradation:
    def test_empty_dict_returns_defaults(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord
        fdr = FallbackDecisionRecord.from_dict({})
        assert fdr.has_fallback is False
        assert fdr.fallback_kinds == []

    def test_unknown_keys_ignored(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord
        fdr = FallbackDecisionRecord.from_dict({
            "has_fallback": True,
            "fallback_kinds": ["remote_to_local"],
            "unknown_future_key": "should_be_ignored",
        })
        assert fdr.has_fallback is True
        assert fdr.fallback_kinds == ["remote_to_local"]

    def test_missing_reasons_default_to_none(self):
        from core.schemas.unified_control_plan import FallbackDecisionRecord
        fdr = FallbackDecisionRecord.from_dict({"has_fallback": False})
        assert fdr.model_fallback_reason is None
        assert fdr.agent_to_command_reason is None
        assert fdr.remote_to_local_reason is None
