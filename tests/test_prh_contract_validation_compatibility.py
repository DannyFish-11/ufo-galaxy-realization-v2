"""tests/test_prh_contract_validation_compatibility.py
=======================================================
PR-H: Contract Validation and Compatibility Coverage for Multi-Device
Runtime Dispatch Evolution.

Coverage:
  A.  Sentinel constants are importable from contracts.contract_compatibility.
  B.  EvolutionCompatibilityReport round-trips through to_dict / from_dict.
  C.  validate_task_envelope_contract — valid minimal envelope passes.
  D.  validate_task_envelope_contract — missing task_id fails.
  E.  validate_task_envelope_contract — missing trace_id fails.
  F.  validate_task_envelope_contract — invalid executor_target_type value fails.
  G.  validate_task_envelope_contract — valid executor_target_type values pass.
  H.  validate_task_envelope_contract — None executor_target_type passes
      (backward compat: pre-PR-E envelope).
  I.  validate_task_envelope_contract — continuity_context as dict passes
      (PR-F).
  J.  validate_task_envelope_contract — continuity_context=None passes
      (backward compat: pre-PR-F envelope).
  K.  validate_task_envelope_contract — non-dict input returns invalid.
  L.  validate_source_dispatch_plan_contract — valid minimal plan passes.
  M.  validate_source_dispatch_plan_contract — missing plan_id fails.
  N.  validate_source_dispatch_plan_contract — unknown mode value fails.
  O.  validate_source_dispatch_plan_contract — continuity_context=dict passes.
  P.  validate_source_dispatch_plan_contract — continuity_context=None passes.
  Q.  validate_source_dispatch_result_contract — valid minimal result passes.
  R.  validate_source_dispatch_result_contract — missing result_id fails.
  S.  validate_source_dispatch_result_contract — success not bool fails.
  T.  validate_source_dispatch_result_contract — unknown mode fails.
  U.  check_envelope_backward_compatibility — fully-evolved envelope is
      compatible and has_executor_target_type, has_continuity_context True.
  V.  check_envelope_backward_compatibility — pre-PR-E/F envelope is still
      compatible; has_executor_target_type=False, has_continuity_context=False.
  W.  check_envelope_backward_compatibility — invalid payload returns
      is_compatible=False.
  X.  check_dispatch_plan_backward_compatibility — evolved plan is compatible;
      reports has_continuity_context=True.
  Y.  check_dispatch_plan_backward_compatibility — pre-PR-F plan is compatible;
      has_continuity_context=False.
  Z.  check_dispatch_result_backward_compatibility — evolved result is
      compatible; reports has_continuity_context=True.
  AA. check_dispatch_result_backward_compatibility — pre-PR-F result is
      compatible; has_continuity_context=False.
  AB. EvolutionCompatibilityReport.missing_evolved_fields is populated when
      evolved fields are absent.
  AC. EvolutionCompatibilityReport.present_evolved_fields is populated when
      evolved fields are present.
  AD. Strict mode records notes for missing evolved fields.
  AE. check_envelope_backward_compatibility with observability_metadata in
      metadata dict reports has_observability_metadata=True.
  AF. TaskEnvelope produced by model_dump() passes check_envelope_backward_compatibility.
  AG. SourceDispatchPlan produced by to_dict() passes check_dispatch_plan_backward_compatibility.
  AH. SourceDispatchResult produced by to_dict() passes check_dispatch_result_backward_compatibility.
  AI. Backward compatibility: old envelope dict with unknown extra fields is tolerated.
  AJ. Backward compatibility: new envelope dict parsed by old consumers (pydantic
      extra=allow) does not raise.
  AK. Backward compatibility: SourceDispatchDecision with executor_target_type=None
      round-trips correctly.
  AL. EvolutionCompatibilityReport.to_json() / from_dict() round-trip preserves
      all list fields.
  AM. validate_task_envelope_contract warnings for unknown lifecycle_status.
  AN. validate_source_dispatch_plan_contract warns on non-canonical posture value.
  AO. Backward compat: continuity_context with nested prior_dispatch_id survives
      envelope round-trip through SourceDispatchPlan.from_dict().
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

import pytest

from contracts.contract_compatibility import (
    CONTRACT_COMPATIBILITY_PR_H_SENTINEL,
    CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY,
    CONTRACT_VALIDATION_IS_AUTHORITY,
    EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY,
    STAGED_MIGRATION_IS_SAFE_POLICY,
    EvolutionCompatibilityReport,
    check_dispatch_plan_backward_compatibility,
    check_dispatch_result_backward_compatibility,
    check_envelope_backward_compatibility,
    validate_source_dispatch_plan_contract,
    validate_source_dispatch_result_contract,
    validate_task_envelope_contract,
)


# ===========================================================================
# A. Sentinel constants importable
# ===========================================================================


class TestSentinelConstants:
    """All sentinel constants are importable and non-empty."""

    def test_contract_validation_is_authority(self):
        assert CONTRACT_VALIDATION_IS_AUTHORITY
        assert "PR-H" in CONTRACT_VALIDATION_IS_AUTHORITY
        assert "canonical" in CONTRACT_VALIDATION_IS_AUTHORITY.lower()
        assert "validation" in CONTRACT_VALIDATION_IS_AUTHORITY.lower()

    def test_evolved_fields_policy(self):
        assert EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY
        assert "PR-H" in EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY
        assert "optional" in EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY.lower()

    def test_contract_evolution_explicit_policy(self):
        assert CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY
        assert "PR-H" in CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY
        assert "explicit" in CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY.lower()

    def test_staged_migration_policy(self):
        assert STAGED_MIGRATION_IS_SAFE_POLICY
        assert "PR-H" in STAGED_MIGRATION_IS_SAFE_POLICY
        assert "migration" in STAGED_MIGRATION_IS_SAFE_POLICY.lower()

    def test_pr_h_sentinel(self):
        assert CONTRACT_COMPATIBILITY_PR_H_SENTINEL
        assert "PR-H" in CONTRACT_COMPATIBILITY_PR_H_SENTINEL


# ===========================================================================
# B. EvolutionCompatibilityReport round-trip
# ===========================================================================


class TestEvolutionCompatibilityReportRoundTrip:
    """EvolutionCompatibilityReport round-trips through to_dict / from_dict."""

    def test_basic_round_trip(self):
        report = EvolutionCompatibilityReport(
            contract_kind="task_envelope",
            is_compatible=True,
            has_executor_target_type=True,
            has_continuity_context=False,
            missing_evolved_fields=["continuity_context"],
            present_evolved_fields=["executor_target_type"],
            validation_errors=[],
            notes=["test note"],
        )
        d = report.to_dict()
        restored = EvolutionCompatibilityReport.from_dict(d)
        assert restored.contract_kind == "task_envelope"
        assert restored.is_compatible is True
        assert restored.has_executor_target_type is True
        assert restored.has_continuity_context is False
        assert "continuity_context" in restored.missing_evolved_fields
        assert "executor_target_type" in restored.present_evolved_fields
        assert restored.notes == ["test note"]

    def test_to_dict_is_json_serialisable(self):
        report = EvolutionCompatibilityReport(contract_kind="source_dispatch_plan")
        payload = json.dumps(report.to_dict())
        assert "source_dispatch_plan" in payload

    def test_from_dict_tolerates_unknown_fields(self):
        d = {
            "contract_kind": "test",
            "is_compatible": True,
            "unknown_extra_field": "should_be_ignored",
        }
        report = EvolutionCompatibilityReport.from_dict(d)
        assert report.contract_kind == "test"
        assert report.is_compatible is True

    def test_report_id_is_populated(self):
        report = EvolutionCompatibilityReport()
        assert report.report_id
        assert len(report.report_id) > 0

    def test_timestamp_is_positive(self):
        report = EvolutionCompatibilityReport()
        assert report.timestamp > 0


# ===========================================================================
# C. validate_task_envelope_contract — valid minimal envelope
# ===========================================================================


class TestValidateTaskEnvelopeContractValid:
    """validate_task_envelope_contract accepts a valid minimal envelope."""

    def test_minimal_valid(self):
        payload = {"task_id": "task_abc", "trace_id": "trace_xyz"}
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_full_evolved_envelope(self):
        payload = {
            "task_id": "task_001",
            "trace_id": "trace_001",
            "executor_target_type": "android_device",
            "continuity_context": {"continuity_id": "c_001"},
            "lifecycle_status": "created",
            "metadata": {},
        }
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True
        assert result["errors"] == []


# ===========================================================================
# D. validate_task_envelope_contract — missing task_id fails
# ===========================================================================


class TestValidateTaskEnvelopeMissingTaskId:
    """validate_task_envelope_contract fails when task_id is missing."""

    def test_missing_task_id(self):
        payload = {"trace_id": "trace_xyz"}
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is False
        assert any("task_id" in e for e in result["errors"])


# ===========================================================================
# E. validate_task_envelope_contract — missing trace_id fails
# ===========================================================================


class TestValidateTaskEnvelopeMissingTraceId:
    """validate_task_envelope_contract fails when trace_id is missing."""

    def test_missing_trace_id(self):
        payload = {"task_id": "task_abc"}
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is False
        assert any("trace_id" in e for e in result["errors"])


# ===========================================================================
# F. validate_task_envelope_contract — invalid executor_target_type fails
# ===========================================================================


class TestValidateTaskEnvelopeInvalidExecutorTargetType:
    """validate_task_envelope_contract fails for unknown executor_target_type."""

    def test_unknown_executor_type(self):
        payload = {
            "task_id": "task_abc",
            "trace_id": "trace_xyz",
            "executor_target_type": "unknown_type",
        }
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is False
        assert any("executor_target_type" in e for e in result["errors"])


# ===========================================================================
# G. validate_task_envelope_contract — valid executor_target_type values
# ===========================================================================


class TestValidateTaskEnvelopeValidExecutorTargetTypes:
    """validate_task_envelope_contract passes for all known executor types."""

    @pytest.mark.parametrize(
        "executor_type",
        ["android_device", "node_service", "go_worker", "local"],
    )
    def test_valid_executor_type(self, executor_type: str):
        payload = {"task_id": "task_abc", "trace_id": "trace_xyz", "executor_target_type": executor_type}
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True, result["errors"]


# ===========================================================================
# H. validate_task_envelope_contract — None executor_target_type (pre-PR-E)
# ===========================================================================


class TestValidateTaskEnvelopeNoneExecutorTargetType:
    """executor_target_type=None is valid (backward compat: pre-PR-E envelope)."""

    def test_none_executor_type(self):
        payload = {
            "task_id": "task_abc",
            "trace_id": "trace_xyz",
            "executor_target_type": None,
        }
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True

    def test_absent_executor_type(self):
        payload = {"task_id": "task_abc", "trace_id": "trace_xyz"}
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True


# ===========================================================================
# I. validate_task_envelope_contract — continuity_context as dict (PR-F)
# ===========================================================================


class TestValidateTaskEnvelopeContinuityContextDict:
    """continuity_context as dict passes validation (PR-F)."""

    def test_continuity_context_dict(self):
        payload = {
            "task_id": "task_abc",
            "trace_id": "trace_xyz",
            "continuity_context": {"continuity_id": "c_001", "prior_dispatch_id": "d_001"},
        }
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True


# ===========================================================================
# J. validate_task_envelope_contract — continuity_context=None (pre-PR-F)
# ===========================================================================


class TestValidateTaskEnvelopeNoneContinuityContext:
    """continuity_context=None is valid (backward compat: pre-PR-F envelope)."""

    def test_none_continuity_context(self):
        payload = {
            "task_id": "task_abc",
            "trace_id": "trace_xyz",
            "continuity_context": None,
        }
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True

    def test_absent_continuity_context(self):
        payload = {"task_id": "task_abc", "trace_id": "trace_xyz"}
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True


# ===========================================================================
# K. validate_task_envelope_contract — non-dict input returns invalid
# ===========================================================================


class TestValidateTaskEnvelopeNonDict:
    """Non-dict input to validate_task_envelope_contract returns invalid."""

    def test_none_input(self):
        result = validate_task_envelope_contract(None)
        assert result["valid"] is False

    def test_list_input(self):
        result = validate_task_envelope_contract([])
        assert result["valid"] is False

    def test_string_input(self):
        result = validate_task_envelope_contract("not_a_dict")
        assert result["valid"] is False


# ===========================================================================
# L. validate_source_dispatch_plan_contract — valid minimal plan
# ===========================================================================


class TestValidateSourceDispatchPlanContractValid:
    """validate_source_dispatch_plan_contract accepts a valid minimal plan."""

    def test_minimal_valid(self):
        payload = {"plan_id": "plan_001", "mode": "local"}
        result = validate_source_dispatch_plan_contract(payload)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_all_modes_valid(self):
        for mode in ("local", "remote_handoff", "staged_mesh", "blocked", "fallback_local", "unknown"):
            payload = {"plan_id": "plan_001", "mode": mode}
            result = validate_source_dispatch_plan_contract(payload)
            assert result["valid"] is True, f"mode={mode} errors: {result['errors']}"


# ===========================================================================
# M. validate_source_dispatch_plan_contract — missing plan_id fails
# ===========================================================================


class TestValidateSourceDispatchPlanMissingPlanId:
    """validate_source_dispatch_plan_contract fails when plan_id is missing."""

    def test_missing_plan_id(self):
        payload = {"mode": "local"}
        result = validate_source_dispatch_plan_contract(payload)
        assert result["valid"] is False
        assert any("plan_id" in e for e in result["errors"])


# ===========================================================================
# N. validate_source_dispatch_plan_contract — unknown mode value fails
# ===========================================================================


class TestValidateSourceDispatchPlanUnknownMode:
    """validate_source_dispatch_plan_contract fails for unknown mode."""

    def test_unknown_mode(self):
        payload = {"plan_id": "plan_001", "mode": "invalid_mode_xyz"}
        result = validate_source_dispatch_plan_contract(payload)
        assert result["valid"] is False
        assert any("mode" in e for e in result["errors"])


# ===========================================================================
# O. validate_source_dispatch_plan_contract — continuity_context=dict
# ===========================================================================


class TestValidateSourceDispatchPlanContinuityContextDict:
    """validate_source_dispatch_plan_contract accepts continuity_context dict."""

    def test_continuity_context_dict(self):
        payload = {
            "plan_id": "plan_001",
            "mode": "local",
            "continuity_context": {"continuity_id": "c_001"},
        }
        result = validate_source_dispatch_plan_contract(payload)
        assert result["valid"] is True


# ===========================================================================
# P. validate_source_dispatch_plan_contract — continuity_context=None
# ===========================================================================


class TestValidateSourceDispatchPlanNoneContinuityContext:
    """validate_source_dispatch_plan_contract accepts continuity_context=None."""

    def test_none_continuity_context(self):
        payload = {"plan_id": "plan_001", "mode": "remote_handoff", "continuity_context": None}
        result = validate_source_dispatch_plan_contract(payload)
        assert result["valid"] is True


# ===========================================================================
# Q. validate_source_dispatch_result_contract — valid minimal result
# ===========================================================================


class TestValidateSourceDispatchResultContractValid:
    """validate_source_dispatch_result_contract accepts a valid minimal result."""

    def test_minimal_valid(self):
        payload = {"result_id": "res_001", "mode": "local", "success": True}
        result = validate_source_dispatch_result_contract(payload)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_failed_result_valid(self):
        payload = {"result_id": "res_002", "mode": "remote_handoff", "success": False}
        result = validate_source_dispatch_result_contract(payload)
        assert result["valid"] is True


# ===========================================================================
# R. validate_source_dispatch_result_contract — missing result_id fails
# ===========================================================================


class TestValidateSourceDispatchResultMissingResultId:
    """validate_source_dispatch_result_contract fails when result_id is missing."""

    def test_missing_result_id(self):
        payload = {"mode": "local", "success": True}
        result = validate_source_dispatch_result_contract(payload)
        assert result["valid"] is False
        assert any("result_id" in e for e in result["errors"])


# ===========================================================================
# S. validate_source_dispatch_result_contract — success not bool fails
# ===========================================================================


class TestValidateSourceDispatchResultSuccessNotBool:
    """validate_source_dispatch_result_contract fails when success is not bool."""

    def test_success_as_string(self):
        payload = {"result_id": "res_001", "mode": "local", "success": "yes"}
        result = validate_source_dispatch_result_contract(payload)
        assert result["valid"] is False
        assert any("success" in e for e in result["errors"])

    def test_success_as_int(self):
        payload = {"result_id": "res_001", "mode": "local", "success": 1}
        result = validate_source_dispatch_result_contract(payload)
        assert result["valid"] is False


# ===========================================================================
# T. validate_source_dispatch_result_contract — unknown mode fails
# ===========================================================================


class TestValidateSourceDispatchResultUnknownMode:
    """validate_source_dispatch_result_contract fails for unknown mode."""

    def test_unknown_mode(self):
        payload = {"result_id": "res_001", "mode": "mystery_mode", "success": True}
        result = validate_source_dispatch_result_contract(payload)
        assert result["valid"] is False


# ===========================================================================
# U. check_envelope_backward_compatibility — fully evolved envelope
# ===========================================================================


class TestCheckEnvelopeBackwardCompatibilityEvolved:
    """Fully evolved envelope is compatible with all PR fields present."""

    def test_evolved_envelope(self):
        payload = {
            "task_id": "task_abc",
            "trace_id": "trace_xyz",
            "executor_target_type": "android_device",
            "continuity_context": {
                "continuity_id": "c_001",
                "prior_dispatch_id": "d_001",
                "prior_session_id": "s_001",
            },
            "metadata": {},
        }
        report = check_envelope_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_executor_target_type is True
        assert report.has_continuity_context is True
        assert report.contract_kind == "task_envelope"

    def test_present_evolved_fields_populated(self):
        payload = {
            "task_id": "t1",
            "trace_id": "tr1",
            "executor_target_type": "local",
            "continuity_context": {"continuity_id": "c1"},
        }
        report = check_envelope_backward_compatibility(payload)
        assert "executor_target_type" in report.present_evolved_fields
        assert "continuity_context" in report.present_evolved_fields


# ===========================================================================
# V. check_envelope_backward_compatibility — pre-PR-E/F envelope
# ===========================================================================


class TestCheckEnvelopeBackwardCompatibilityPreEvolution:
    """Pre-evolution envelope (no PR-E/F fields) is still compatible."""

    def test_pre_evolution_envelope(self):
        payload = {"task_id": "task_abc", "trace_id": "trace_xyz"}
        report = check_envelope_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_executor_target_type is False
        assert report.has_continuity_context is False

    def test_missing_evolved_fields_recorded(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload)
        assert "executor_target_type" in report.missing_evolved_fields
        assert "continuity_context" in report.missing_evolved_fields

    def test_validation_errors_empty(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload)
        assert report.validation_errors == []


# ===========================================================================
# W. check_envelope_backward_compatibility — invalid payload
# ===========================================================================


class TestCheckEnvelopeBackwardCompatibilityInvalid:
    """Invalid payload returns is_compatible=False."""

    def test_non_dict_payload(self):
        report = check_envelope_backward_compatibility(None)
        assert report.is_compatible is False
        assert len(report.validation_errors) > 0

    def test_missing_required_fields(self):
        payload = {"executor_target_type": "local"}
        report = check_envelope_backward_compatibility(payload)
        assert report.is_compatible is False


# ===========================================================================
# X. check_dispatch_plan_backward_compatibility — evolved plan
# ===========================================================================


class TestCheckDispatchPlanBackwardCompatibilityEvolved:
    """Evolved dispatch plan is compatible; reports has_continuity_context=True."""

    def test_evolved_plan(self):
        payload = {
            "plan_id": "plan_001",
            "mode": "remote_handoff",
            "continuity_context": {"continuity_id": "c_001", "prior_dispatch_id": "d_001"},
            "source_runtime_posture": "control_only",
        }
        report = check_dispatch_plan_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_continuity_context is True
        assert report.has_source_runtime_posture is True


# ===========================================================================
# Y. check_dispatch_plan_backward_compatibility — pre-PR-F plan
# ===========================================================================


class TestCheckDispatchPlanBackwardCompatibilityPrePRF:
    """Pre-PR-F dispatch plan (no continuity_context) is still compatible."""

    def test_pre_prf_plan(self):
        payload = {"plan_id": "plan_001", "mode": "local"}
        report = check_dispatch_plan_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_continuity_context is False

    def test_missing_continuity_context_recorded(self):
        payload = {"plan_id": "plan_001", "mode": "fallback_local"}
        report = check_dispatch_plan_backward_compatibility(payload)
        assert "continuity_context" in report.missing_evolved_fields


# ===========================================================================
# Z. check_dispatch_result_backward_compatibility — evolved result
# ===========================================================================


class TestCheckDispatchResultBackwardCompatibilityEvolved:
    """Evolved dispatch result is compatible; reports has_continuity_context=True."""

    def test_evolved_result(self):
        payload = {
            "result_id": "res_001",
            "mode": "local",
            "success": True,
            "continuity_context": {"continuity_id": "c_001"},
        }
        report = check_dispatch_result_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_continuity_context is True


# ===========================================================================
# AA. check_dispatch_result_backward_compatibility — pre-PR-F result
# ===========================================================================


class TestCheckDispatchResultBackwardCompatibilityPrePRF:
    """Pre-PR-F dispatch result (no continuity_context) is still compatible."""

    def test_pre_prf_result(self):
        payload = {"result_id": "res_001", "mode": "local", "success": False}
        report = check_dispatch_result_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_continuity_context is False


# ===========================================================================
# AB. missing_evolved_fields populated when evolved fields absent
# ===========================================================================


class TestMissingEvolvedFieldsPopulated:
    """missing_evolved_fields is populated when evolved fields are absent."""

    def test_executor_target_type_missing(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload)
        assert "executor_target_type" in report.missing_evolved_fields

    def test_continuity_context_missing(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload)
        assert "continuity_context" in report.missing_evolved_fields

    def test_both_missing_when_absent(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload)
        assert "executor_target_type" in report.missing_evolved_fields
        assert "continuity_context" in report.missing_evolved_fields


# ===========================================================================
# AC. present_evolved_fields populated when evolved fields are present
# ===========================================================================


class TestPresentEvolvedFieldsPopulated:
    """present_evolved_fields is populated when evolved fields are present."""

    def test_executor_target_type_present(self):
        payload = {
            "task_id": "t1",
            "trace_id": "tr1",
            "executor_target_type": "go_worker",
        }
        report = check_envelope_backward_compatibility(payload)
        assert "executor_target_type" in report.present_evolved_fields

    def test_continuity_context_present(self):
        payload = {
            "task_id": "t1",
            "trace_id": "tr1",
            "continuity_context": {"continuity_id": "c1"},
        }
        report = check_envelope_backward_compatibility(payload)
        assert "continuity_context" in report.present_evolved_fields

    def test_both_present(self):
        payload = {
            "task_id": "t1",
            "trace_id": "tr1",
            "executor_target_type": "node_service",
            "continuity_context": {"continuity_id": "c1"},
        }
        report = check_envelope_backward_compatibility(payload)
        assert "executor_target_type" in report.present_evolved_fields
        assert "continuity_context" in report.present_evolved_fields


# ===========================================================================
# AD. Strict mode records notes for missing evolved fields
# ===========================================================================


class TestStrictModeNotes:
    """Strict mode records notes for missing evolved fields."""

    def test_strict_mode_adds_note(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload, strict=True)
        assert len(report.notes) > 0
        assert any("missing" in n.lower() or "evolved" in n.lower() for n in report.notes)

    def test_non_strict_mode_no_notes_for_missing(self):
        payload = {"task_id": "t1", "trace_id": "tr1"}
        report = check_envelope_backward_compatibility(payload, strict=False)
        assert report.notes == []

    def test_strict_mode_dispatch_plan(self):
        payload = {"plan_id": "p1", "mode": "local"}
        report = check_dispatch_plan_backward_compatibility(payload, strict=True)
        assert len(report.notes) > 0


# ===========================================================================
# AE. observability_metadata in metadata dict → has_observability_metadata=True
# ===========================================================================


class TestObservabilityMetadataInMetadataDict:
    """has_observability_metadata=True when metadata contains observability_metadata."""

    def test_observability_metadata_present(self):
        payload = {
            "task_id": "t1",
            "trace_id": "tr1",
            "metadata": {
                "observability_metadata": {
                    "trace_id": "trace_001",
                    "span_id": "span_001",
                }
            },
        }
        report = check_envelope_backward_compatibility(payload)
        assert report.has_observability_metadata is True

    def test_observability_metadata_absent(self):
        payload = {"task_id": "t1", "trace_id": "tr1", "metadata": {}}
        report = check_envelope_backward_compatibility(payload)
        assert report.has_observability_metadata is False


# ===========================================================================
# AF. TaskEnvelope.model_dump() passes check
# ===========================================================================


class TestTaskEnvelopeModelDumpPasses:
    """TaskEnvelope produced by model_dump() passes backward compatibility check."""

    def test_default_envelope_passes(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope()
        payload = env.model_dump()
        report = check_envelope_backward_compatibility(payload)
        assert report.is_compatible is True

    def test_evolved_envelope_passes(self):
        from core.schemas.task_envelope import TaskEnvelope
        from core.schemas.remote_execution import ExecutorTargetType
        env = TaskEnvelope(
            executor_target_type=ExecutorTargetType.android_device,
            continuity_context={"continuity_id": "c_001", "prior_dispatch_id": "d_001"},
        )
        payload = env.model_dump()
        report = check_envelope_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_executor_target_type is True
        assert report.has_continuity_context is True


# ===========================================================================
# AG. SourceDispatchPlan.to_dict() passes check
# ===========================================================================


class TestSourceDispatchPlanToDictPasses:
    """SourceDispatchPlan produced by to_dict() passes backward compatibility check."""

    def test_default_plan_passes(self):
        from contracts.source_dispatch import SourceDispatchPlan
        plan = SourceDispatchPlan()
        payload = plan.to_dict()
        report = check_dispatch_plan_backward_compatibility(payload)
        assert report.is_compatible is True

    def test_plan_with_continuity_context_passes(self):
        from contracts.source_dispatch import build_source_dispatch_plan
        plan = build_source_dispatch_plan(
            mode=None,
            continuity_context={"continuity_id": "c_001", "prior_session_id": "s_001"},
        )
        payload = plan.to_dict()
        report = check_dispatch_plan_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_continuity_context is True


# ===========================================================================
# AH. SourceDispatchResult.to_dict() passes check
# ===========================================================================


class TestSourceDispatchResultToDictPasses:
    """SourceDispatchResult produced by to_dict() passes backward compatibility check."""

    def test_default_result_passes(self):
        from contracts.source_dispatch import SourceDispatchResult
        result = SourceDispatchResult()
        payload = result.to_dict()
        report = check_dispatch_result_backward_compatibility(payload)
        assert report.is_compatible is True

    def test_result_with_continuity_context_passes(self):
        from contracts.source_dispatch import build_source_dispatch_result
        result = build_source_dispatch_result(
            success=True,
            continuity_context={"continuity_id": "c_001"},
        )
        payload = result.to_dict()
        report = check_dispatch_result_backward_compatibility(payload)
        assert report.is_compatible is True
        assert report.has_continuity_context is True


# ===========================================================================
# AI. Backward compatibility: old envelope with unknown extra fields tolerated
# ===========================================================================


class TestOldEnvelopeWithUnknownExtraFieldsTolerated:
    """Old envelope dict with unknown extra fields is tolerated by validators."""

    def test_extra_fields_tolerated(self):
        payload = {
            "task_id": "t_old",
            "trace_id": "tr_old",
            "legacy_field_from_v1": "value",
            "another_old_field": {"nested": True},
        }
        result = validate_task_envelope_contract(payload)
        assert result["valid"] is True

    def test_extra_fields_do_not_affect_compat_report(self):
        payload = {
            "task_id": "t_old",
            "trace_id": "tr_old",
            "old_routing_hint": "node_07",
        }
        report = check_envelope_backward_compatibility(payload)
        assert report.is_compatible is True


# ===========================================================================
# AJ. Backward compat: new envelope parsed by TaskEnvelope (extra=allow)
# ===========================================================================


class TestNewEnvelopeParsedByOldConsumer:
    """New envelope dict with evolved fields is parsed by TaskEnvelope (extra=allow)."""

    def test_new_envelope_parses_without_error(self):
        from core.schemas.task_envelope import TaskEnvelope
        # Simulate a new envelope that includes future unknown fields
        payload = {
            "task_id": "t_new",
            "trace_id": "tr_new",
            "executor_target_type": "android_device",
            "continuity_context": {"continuity_id": "c_001"},
            "future_field_from_pr_x": "some_value",
        }
        # TaskEnvelope should parse this without error due to extra="allow"
        env = TaskEnvelope.model_validate(payload)
        assert env.task_id == "t_new"
        assert env.executor_target_type is not None


# ===========================================================================
# AK. Backward compat: SourceDispatchDecision with executor_target_type=None
# ===========================================================================


class TestSourceDispatchDecisionNoneExecutorTargetType:
    """SourceDispatchDecision with executor_target_type=None round-trips correctly."""

    def test_executor_target_type_absent_round_trip(self):
        from contracts.source_dispatch import SourceDispatchDecision
        decision = SourceDispatchDecision()
        d = decision.to_dict()
        restored = SourceDispatchDecision.from_dict(d)
        assert restored.dispatch_id == decision.dispatch_id
        # mode defaults to unknown
        assert restored.mode.value == "unknown"

    def test_decision_with_unknown_extra_fields(self):
        from contracts.source_dispatch import SourceDispatchDecision
        # Simulate a newer decision payload with extra unknown fields
        payload = {
            "dispatch_id": "d_001",
            "mode": "local",
            "decision_reason": "local_preferred",
            "future_field_pr_x": "value",
        }
        decision = SourceDispatchDecision.model_validate(payload)
        assert decision.dispatch_id == "d_001"
        assert decision.mode.value == "local"


# ===========================================================================
# AL. EvolutionCompatibilityReport.to_json() / from_dict() round-trip
# ===========================================================================


class TestEvolutionCompatibilityReportJsonRoundTrip:
    """to_json() / from_dict() round-trip preserves all list fields."""

    def test_json_round_trip(self):
        report = EvolutionCompatibilityReport(
            contract_kind="source_dispatch_result",
            is_compatible=False,
            missing_evolved_fields=["executor_target_type", "continuity_context"],
            present_evolved_fields=[],
            validation_errors=["Missing result_id"],
            notes=["note_1", "note_2"],
        )
        json_str = report.to_json()
        d = json.loads(json_str)
        restored = EvolutionCompatibilityReport.from_dict(d)
        assert restored.contract_kind == "source_dispatch_result"
        assert restored.is_compatible is False
        assert "executor_target_type" in restored.missing_evolved_fields
        assert "continuity_context" in restored.missing_evolved_fields
        assert "Missing result_id" in restored.validation_errors
        assert "note_1" in restored.notes

    def test_empty_report_json_round_trip(self):
        report = EvolutionCompatibilityReport()
        restored = EvolutionCompatibilityReport.from_dict(json.loads(report.to_json()))
        assert restored.is_compatible is True
        assert restored.missing_evolved_fields == []
        assert restored.validation_errors == []


# ===========================================================================
# AM. validate_task_envelope_contract warnings for unknown lifecycle_status
# ===========================================================================


class TestValidateTaskEnvelopeLifecycleStatusWarning:
    """validate_task_envelope_contract warns on unknown lifecycle_status."""

    def test_unknown_lifecycle_status_warning(self):
        payload = {
            "task_id": "t1",
            "trace_id": "tr1",
            "lifecycle_status": "mysterious_state",
        }
        result = validate_task_envelope_contract(payload)
        # Should still be valid (only a warning)
        assert result["valid"] is True
        assert any("lifecycle_status" in w for w in result["warnings"])

    def test_known_lifecycle_status_no_warning(self):
        for status in ("created", "running", "done", "failed"):
            payload = {"task_id": "t1", "trace_id": "tr1", "lifecycle_status": status}
            result = validate_task_envelope_contract(payload)
            assert result["valid"] is True
            assert not any("lifecycle_status" in w for w in result["warnings"])


# ===========================================================================
# AN. validate_source_dispatch_plan_contract warns on non-canonical posture
# ===========================================================================


class TestValidateSourceDispatchPlanNonCanonicalPosture:
    """validate_source_dispatch_plan_contract warns on non-canonical posture."""

    def test_non_canonical_posture_warning(self):
        payload = {
            "plan_id": "p1",
            "mode": "local",
            "source_runtime_posture": "invalid_posture",
        }
        result = validate_source_dispatch_plan_contract(payload)
        # Valid (posture is optional field), but warns
        assert result["valid"] is True
        assert any("source_runtime_posture" in w for w in result["warnings"])

    def test_canonical_posture_no_warning(self):
        for posture in ("control_only", "join_runtime"):
            payload = {
                "plan_id": "p1",
                "mode": "local",
                "source_runtime_posture": posture,
            }
            result = validate_source_dispatch_plan_contract(payload)
            assert result["valid"] is True
            assert not any("source_runtime_posture" in w for w in result["warnings"])


# ===========================================================================
# AO. Backward compat: continuity_context survives SourceDispatchPlan round-trip
# ===========================================================================


class TestContinuityContextSurvivesDispatchPlanRoundTrip:
    """continuity_context with nested fields survives SourceDispatchPlan.from_dict()."""

    def test_nested_continuity_context_round_trip(self):
        from contracts.source_dispatch import SourceDispatchPlan
        ctx_dict = {
            "continuity_id": "c_001",
            "prior_dispatch_id": "d_001",
            "prior_session_id": "s_001",
            "prior_mesh_session_id": "m_001",
            "prior_task_id": "t_001",
            "prior_trace_id": "tr_001",
            "originating_device_id": "android_01",
            "resume_attempt_count": 1,
            "continuity_class": "persistent",
        }
        plan = SourceDispatchPlan(
            plan_id="plan_001",
            mode="remote_handoff",
            continuity_context=ctx_dict,
        )
        d = plan.to_dict()
        restored = SourceDispatchPlan.from_dict(d)
        assert restored.continuity_context is not None
        assert restored.continuity_context["continuity_id"] == "c_001"
        assert restored.continuity_context["prior_dispatch_id"] == "d_001"
        assert restored.continuity_context["prior_session_id"] == "s_001"
        assert restored.continuity_context["resume_attempt_count"] == 1

    def test_compat_report_for_plan_with_full_continuity(self):
        from contracts.source_dispatch import SourceDispatchPlan
        ctx_dict = {"continuity_id": "c_002", "prior_task_id": "t_002"}
        plan = SourceDispatchPlan(plan_id="plan_002", mode="staged_mesh", continuity_context=ctx_dict)
        report = check_dispatch_plan_backward_compatibility(plan.to_dict())
        assert report.is_compatible is True
        assert report.has_continuity_context is True
