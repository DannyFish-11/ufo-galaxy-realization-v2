"""
PR-8: Execution Envelope Consolidation — unit tests
=====================================================

Covers:
* EnvelopeRole enum values and helpers (role_for_class, layer_for_role)
* extract_trace_fields from all four envelope types and plain dicts
* propagate_trace non-overwrite semantics
* task_to_command_summary field extraction and defaults
* result_to_observation PR-7 compatibility
* interaction_trace_fields extraction
* EnvelopeSummary serialisation round-trip (to_dict / from_dict)
* summarise_envelope role inference for all four envelope types
* envelope_role_catalog structure
* Edge cases: missing trace_id, None values, partial envelopes
* summarise_result_for_projection
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# EnvelopeRole tests
# ---------------------------------------------------------------------------

class TestEnvelopeRole:
    def test_role_values(self):
        from core.envelope_consolidation import EnvelopeRole

        assert EnvelopeRole.INTERACTION.value == "interaction"
        assert EnvelopeRole.TASK.value == "task"
        assert EnvelopeRole.COMMAND.value == "command"
        assert EnvelopeRole.RESULT.value == "result"

    def test_role_for_class_short_name(self):
        from core.envelope_consolidation import role_for_class, EnvelopeRole

        assert role_for_class("InteractionEnvelope") == EnvelopeRole.INTERACTION
        assert role_for_class("TaskEnvelope") == EnvelopeRole.TASK
        assert role_for_class("CommandEnvelope") == EnvelopeRole.COMMAND
        assert role_for_class("ResultEnvelope") == EnvelopeRole.RESULT

    def test_role_for_class_fqn(self):
        from core.envelope_consolidation import role_for_class, EnvelopeRole

        assert role_for_class("core.schemas.task_envelope.TaskEnvelope") == EnvelopeRole.TASK
        assert role_for_class(
            "core.unified.command_envelope.CommandEnvelope"
        ) == EnvelopeRole.COMMAND

    def test_role_for_class_unknown_raises(self):
        from core.envelope_consolidation import role_for_class

        with pytest.raises(KeyError):
            role_for_class("BogusEnvelope")

    def test_layer_for_role(self):
        from core.envelope_consolidation import layer_for_role, EnvelopeRole

        assert "interaction" in layer_for_role(EnvelopeRole.INTERACTION)
        assert "orchestration" in layer_for_role(EnvelopeRole.TASK)
        assert "executor" in layer_for_role(EnvelopeRole.COMMAND)
        assert "result" in layer_for_role(EnvelopeRole.RESULT)

    def test_role_descriptions_completeness(self):
        from core.envelope_consolidation import ROLE_DESCRIPTIONS, EnvelopeRole

        for role in EnvelopeRole:
            assert role in ROLE_DESCRIPTIONS
            meta = ROLE_DESCRIPTIONS[role]
            assert "label" in meta
            assert "canonical_class" in meta
            assert "layer" in meta
            assert "key_fields" in meta
            assert "summary" in meta
            assert "trace_field" in meta


# ---------------------------------------------------------------------------
# extract_trace_fields tests
# ---------------------------------------------------------------------------

class TestExtractTraceFields:
    def test_from_plain_dict(self):
        from core.envelope_consolidation import extract_trace_fields

        d = {
            "trace_id": "trace_abc",
            "task_id": "task_xyz",
            "runtime_session_id": "sess_1",
            "session_id": "sess_2",
            "interaction_id": "ix_001",
        }
        result = extract_trace_fields(d)
        assert result["trace_id"] == "trace_abc"
        assert result["task_id"] == "task_xyz"
        assert result["runtime_session_id"] == "sess_1"
        assert result["session_id"] == "sess_2"
        assert result["interaction_id"] == "ix_001"

    def test_from_task_envelope(self):
        from core.envelope_consolidation import extract_trace_fields
        from core.schemas.task_envelope import TaskEnvelope

        te = TaskEnvelope(
            trace_id="trace_te_001",
            task_id="task_te_001",
            session_id="sess_te",
        )
        result = extract_trace_fields(te)
        assert result["trace_id"] == "trace_te_001"
        assert result["task_id"] == "task_te_001"
        assert result["session_id"] == "sess_te"

    def test_from_command_envelope(self):
        from core.envelope_consolidation import extract_trace_fields
        from core.unified.command_envelope import CommandEnvelope

        cmd = CommandEnvelope(
            trace_id="trace_cmd_001",
            task_id="task_cmd_001",
            runtime_session_id="sess_cmd",
            device_id="win_pc_01",
        )
        result = extract_trace_fields(cmd)
        assert result["trace_id"] == "trace_cmd_001"
        assert result["task_id"] == "task_cmd_001"
        assert result["runtime_session_id"] == "sess_cmd"

    def test_from_result_envelope(self):
        from core.envelope_consolidation import extract_trace_fields
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(
            task_id="task_res_001",
            trace_id="trace_res_001",
            success=True,
        )
        result = extract_trace_fields(re)
        assert result["trace_id"] == "trace_res_001"
        assert result["task_id"] == "task_res_001"

    def test_from_interaction_envelope(self):
        from core.envelope_consolidation import extract_trace_fields
        from core.schemas.interaction_envelope import InteractionEnvelope

        ie = InteractionEnvelope(
            trace_id="trace_ix_001",
            session_id="sess_ix",
        )
        result = extract_trace_fields(ie)
        assert result["trace_id"] == "trace_ix_001"
        assert result["session_id"] == "sess_ix"
        assert result["interaction_id"] is not None  # auto-generated

    def test_missing_trace_id_generates_new(self):
        from core.envelope_consolidation import extract_trace_fields

        result = extract_trace_fields({})
        assert result["trace_id"] is not None
        assert result["trace_id"].startswith("trace_")

    def test_none_trace_id_generates_new(self):
        from core.envelope_consolidation import extract_trace_fields

        result = extract_trace_fields({"trace_id": None})
        assert result["trace_id"] is not None
        assert result["trace_id"].startswith("trace_")

    def test_missing_optional_fields_return_none(self):
        from core.envelope_consolidation import extract_trace_fields

        result = extract_trace_fields({"trace_id": "trace_only"})
        assert result["task_id"] is None
        assert result["runtime_session_id"] is None
        assert result["session_id"] is None
        assert result["interaction_id"] is None


# ---------------------------------------------------------------------------
# propagate_trace tests
# ---------------------------------------------------------------------------

class TestPropagateTrace:
    def test_copies_trace_fields(self):
        from core.envelope_consolidation import propagate_trace

        source = {"trace_id": "trace_src", "task_id": "task_src", "session_id": "sess_src"}
        target: Dict[str, Any] = {}
        result = propagate_trace(source, target)
        assert result["trace_id"] == "trace_src"
        assert result["task_id"] == "task_src"
        assert result["session_id"] == "sess_src"

    def test_does_not_overwrite_existing(self):
        from core.envelope_consolidation import propagate_trace

        source = {"trace_id": "trace_new", "task_id": "task_new"}
        target: Dict[str, Any] = {"trace_id": "trace_existing"}
        propagate_trace(source, target)
        # existing trace_id must not be overwritten
        assert target["trace_id"] == "trace_existing"
        # task_id from source is written since it was absent
        assert target["task_id"] == "task_new"

    def test_returns_target(self):
        from core.envelope_consolidation import propagate_trace

        target: Dict[str, Any] = {}
        result = propagate_trace({"trace_id": "t"}, target)
        assert result is target

    def test_none_fields_not_copied(self):
        from core.envelope_consolidation import propagate_trace

        source = {"trace_id": "trace_src", "task_id": None}
        target: Dict[str, Any] = {}
        propagate_trace(source, target)
        # None task_id should not be written
        assert "task_id" not in target


# ---------------------------------------------------------------------------
# task_to_command_summary tests
# ---------------------------------------------------------------------------

class TestTaskToCommandSummary:
    def test_from_task_envelope(self):
        from core.envelope_consolidation import task_to_command_summary
        from core.schemas.task_envelope import TaskEnvelope

        te = TaskEnvelope(
            trace_id="trace_te",
            task_id="task_te",
            session_id="sess_te",
            targets=["device_01"],
            tool_name="click",
            args={"x": 100, "y": 200},
            priority=3,
            timeout=15.0,
            source="api",
        )
        summary = task_to_command_summary(te)
        assert summary["trace_id"] == "trace_te"
        assert summary["task_id"] == "task_te"
        assert summary["device_id"] == "device_01"
        assert summary["tool_name"] == "click"
        assert summary["args"] == {"x": 100, "y": 200}
        assert summary["priority"] == 3
        assert summary["timeout"] == 15.0
        assert summary["lifecycle_status"] == "created"
        assert summary["source"] == "api"
        assert summary["envelope_role"] == "task"

    def test_from_plain_dict(self):
        from core.envelope_consolidation import task_to_command_summary

        d = {
            "trace_id": "trace_d",
            "task_id": "task_d",
            "targets": ["device_02"],
            "tool_name": "type_text",
            "args": {"text": "hello"},
            "priority": 5,
            "timeout": 30.0,
            "lifecycle_status": "running",
            "source": "ws",
        }
        summary = task_to_command_summary(d)
        assert summary["device_id"] == "device_02"
        assert summary["tool_name"] == "type_text"
        assert summary["lifecycle_status"] == "running"

    def test_empty_targets_returns_empty_device_id(self):
        from core.envelope_consolidation import task_to_command_summary

        summary = task_to_command_summary({"trace_id": "t", "targets": []})
        assert summary["device_id"] == ""

    def test_defaults_applied(self):
        from core.envelope_consolidation import task_to_command_summary

        summary = task_to_command_summary({})
        assert summary["priority"] == 5
        assert summary["timeout"] == 30.0
        assert summary["lifecycle_status"] == "created"
        assert summary["envelope_role"] == "task"
        assert summary["trace_id"].startswith("trace_")


# ---------------------------------------------------------------------------
# result_to_observation tests
# ---------------------------------------------------------------------------

class TestResultToObservation:
    def test_success_result(self):
        from core.envelope_consolidation import result_to_observation
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(
            task_id="task_r",
            trace_id="trace_r",
            success=True,
            elapsed_ms=42.5,
            device_id="win_pc",
        )
        obs = result_to_observation(re)
        assert obs["trace"]["trace_id"] == "trace_r"
        assert obs["trace"]["task_id"] == "task_r"
        assert obs["metadata"]["success"] is True
        assert obs["metadata"]["elapsed_ms"] == 42.5
        assert obs["metadata"]["device_id"] == "win_pc"
        assert obs["message"] == "success"
        assert obs["executor_level"] == "unknown"

    def test_failure_result(self):
        from core.envelope_consolidation import result_to_observation
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(
            task_id="task_fail",
            trace_id="trace_fail",
            success=False,
            error="something went wrong",
            error_code="EX_001",
        )
        obs = result_to_observation(re)
        assert obs["metadata"]["success"] is False
        assert obs["message"] == "something went wrong"
        assert obs["metadata"]["error_code"] == "EX_001"

    def test_compatible_with_execution_event(self):
        """Verify result_to_observation output is compatible with ExecutionEvent.from_dict."""
        from core.envelope_consolidation import result_to_observation
        from core.execution_observability import ExecutionEvent
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(
            task_id="task_obs",
            trace_id="trace_obs",
            success=True,
            elapsed_ms=10.0,
        )
        obs = result_to_observation(re)
        # Should not raise
        event = ExecutionEvent.from_dict(obs)
        assert event.trace.trace_id == "trace_obs"
        assert event.trace.task_id == "task_obs"


# ---------------------------------------------------------------------------
# interaction_trace_fields tests
# ---------------------------------------------------------------------------

class TestInteractionTraceFields:
    def test_from_interaction_envelope(self):
        from core.envelope_consolidation import interaction_trace_fields
        from core.schemas.interaction_envelope import InteractionEnvelope

        ie = InteractionEnvelope(
            trace_id="trace_ix",
            session_id="sess_ix",
        )
        fields = interaction_trace_fields(ie)
        assert fields["trace_id"] == "trace_ix"
        assert fields["session_id"] == "sess_ix"
        assert fields["interaction_id"] == ie.interaction_id

    def test_missing_trace_generates_new(self):
        from core.envelope_consolidation import interaction_trace_fields
        from core.schemas.interaction_envelope import InteractionEnvelope

        ie = InteractionEnvelope(session_id="sess_x")
        # trace_id defaults to None on InteractionEnvelope
        ie.trace_id = None  # type: ignore[assignment]
        fields = interaction_trace_fields(ie)
        assert fields["trace_id"] is not None
        assert fields["trace_id"].startswith("trace_")

    def test_from_plain_dict(self):
        from core.envelope_consolidation import interaction_trace_fields

        d = {"trace_id": "t_1", "session_id": "s_1", "interaction_id": "ix_1"}
        fields = interaction_trace_fields(d)
        assert fields["trace_id"] == "t_1"
        assert fields["session_id"] == "s_1"
        assert fields["interaction_id"] == "ix_1"


# ---------------------------------------------------------------------------
# EnvelopeSummary serialisation tests
# ---------------------------------------------------------------------------

class TestEnvelopeSummary:
    def test_to_dict_keys(self):
        from core.envelope_consolidation import EnvelopeSummary, EnvelopeRole

        summary = EnvelopeSummary(
            role=EnvelopeRole.TASK,
            trace_id="trace_s",
            task_id="task_s",
            runtime_session_id="sess_s",
            label="Task Envelope",
            metadata={"tool_name": "click"},
        )
        d = summary.to_dict()
        assert d["role"] == "task"
        assert d["trace_id"] == "trace_s"
        assert d["task_id"] == "task_s"
        assert d["runtime_session_id"] == "sess_s"
        assert d["metadata"]["tool_name"] == "click"
        assert "captured_at" in d

    def test_from_dict_round_trip(self):
        from core.envelope_consolidation import EnvelopeSummary, EnvelopeRole

        summary = EnvelopeSummary(
            role=EnvelopeRole.COMMAND,
            trace_id="trace_c",
            task_id="task_c",
            runtime_session_id=None,
            label="Command Envelope",
            metadata={"verb": "execute"},
        )
        d = summary.to_dict()
        restored = EnvelopeSummary.from_dict(d)
        assert restored.role == EnvelopeRole.COMMAND
        assert restored.trace_id == "trace_c"
        assert restored.task_id == "task_c"
        assert restored.metadata["verb"] == "execute"

    def test_projection_summary_compact(self):
        from core.envelope_consolidation import EnvelopeSummary, EnvelopeRole

        summary = EnvelopeSummary(
            role=EnvelopeRole.RESULT,
            trace_id="trace_r",
            task_id=None,
            runtime_session_id=None,
            label="Result Envelope",
            metadata={"success": True, "elapsed_ms": 5.0},
        )
        proj = summary.projection_summary()
        assert proj["role"] == "result"
        assert proj["trace_id"] == "trace_r"
        assert proj["success"] is True
        assert proj["elapsed_ms"] == 5.0
        # task_id and runtime_session_id are absent (None)
        assert "task_id" not in proj
        assert "runtime_session_id" not in proj

    def test_from_dict_invalid_role_falls_back_to_task(self):
        from core.envelope_consolidation import EnvelopeSummary, EnvelopeRole

        restored = EnvelopeSummary.from_dict({"role": "bogus_role", "trace_id": "t"})
        assert restored.role == EnvelopeRole.TASK

    def test_from_dict_missing_trace_generates_new(self):
        from core.envelope_consolidation import EnvelopeSummary

        restored = EnvelopeSummary.from_dict({"role": "task"})
        assert restored.trace_id is not None
        assert len(restored.trace_id) > 0


# ---------------------------------------------------------------------------
# summarise_envelope role-inference tests
# ---------------------------------------------------------------------------

class TestSummariseEnvelope:
    def test_interaction_envelope_inferred(self):
        from core.envelope_consolidation import summarise_envelope, EnvelopeRole
        from core.schemas.interaction_envelope import InteractionEnvelope

        ie = InteractionEnvelope(trace_id="trace_ix2", session_id="sess_ix2", mode="chat")
        summary = summarise_envelope(ie)
        assert summary.role == EnvelopeRole.INTERACTION
        assert summary.trace_id == "trace_ix2"
        assert summary.metadata.get("mode") == "chat"

    def test_task_envelope_inferred(self):
        from core.envelope_consolidation import summarise_envelope, EnvelopeRole
        from core.schemas.task_envelope import TaskEnvelope

        te = TaskEnvelope(
            trace_id="trace_te2",
            task_id="task_te2",
            targets=["dev_01"],
            tool_name="run_script",
        )
        summary = summarise_envelope(te)
        assert summary.role == EnvelopeRole.TASK
        assert summary.task_id == "task_te2"
        assert summary.metadata.get("tool_name") == "run_script"

    def test_command_envelope_inferred(self):
        from core.envelope_consolidation import summarise_envelope, EnvelopeRole
        from core.unified.command_envelope import CommandEnvelope

        cmd = CommandEnvelope(
            trace_id="trace_cmd2",
            task_id="task_cmd2",
            runtime_session_id="sess_cmd2",
            device_id="device_cmd",
        )
        summary = summarise_envelope(cmd)
        assert summary.role == EnvelopeRole.COMMAND
        assert summary.trace_id == "trace_cmd2"

    def test_result_envelope_inferred(self):
        from core.envelope_consolidation import summarise_envelope, EnvelopeRole
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(
            task_id="task_res2",
            trace_id="trace_res2",
            success=False,
            error="oops",
            elapsed_ms=7.5,
        )
        summary = summarise_envelope(re)
        assert summary.role == EnvelopeRole.RESULT
        assert summary.metadata.get("success") is False
        assert summary.metadata.get("elapsed_ms") == 7.5

    def test_explicit_role_override(self):
        from core.envelope_consolidation import summarise_envelope, EnvelopeRole

        # Pass a plain dict that would infer as TASK but force COMMAND
        d = {
            "trace_id": "t",
            "task_id": "task_x",
            "lifecycle_status": "running",
            "targets": ["dev"],
        }
        summary = summarise_envelope(d, role=EnvelopeRole.COMMAND)
        assert summary.role == EnvelopeRole.COMMAND

    def test_partial_envelope_dict(self):
        from core.envelope_consolidation import summarise_envelope

        # Should not raise even with minimal / missing fields
        summary = summarise_envelope({"trace_id": "t_partial"})
        assert summary.trace_id == "t_partial"


# ---------------------------------------------------------------------------
# envelope_role_catalog tests
# ---------------------------------------------------------------------------

class TestEnvelopeRoleCatalog:
    def test_catalog_has_four_entries(self):
        from core.envelope_consolidation import envelope_role_catalog

        catalog = envelope_role_catalog()
        assert len(catalog) == 4

    def test_catalog_entry_keys(self):
        from core.envelope_consolidation import envelope_role_catalog

        catalog = envelope_role_catalog()
        required_keys = {"role", "label", "canonical_class", "layer", "key_fields", "summary", "trace_field"}
        for entry in catalog:
            assert required_keys.issubset(entry.keys()), (
                f"Missing keys in catalog entry for role {entry.get('role')}: "
                f"{required_keys - entry.keys()}"
            )

    def test_catalog_roles_match_enum(self):
        from core.envelope_consolidation import envelope_role_catalog, EnvelopeRole

        catalog = envelope_role_catalog()
        role_values = {e.value for e in EnvelopeRole}
        catalog_roles = {entry["role"] for entry in catalog}
        assert catalog_roles == role_values

    def test_catalog_serialisable(self):
        import json
        from core.envelope_consolidation import envelope_role_catalog

        catalog = envelope_role_catalog()
        # Should not raise
        json.dumps(catalog)


# ---------------------------------------------------------------------------
# summarise_result_for_projection tests
# ---------------------------------------------------------------------------

class TestSummariseResultForProjection:
    def test_returns_flat_dict(self):
        from core.envelope_consolidation import summarise_result_for_projection
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(
            task_id="task_proj",
            trace_id="trace_proj",
            success=True,
            elapsed_ms=3.0,
        )
        proj = summarise_result_for_projection(re)
        assert isinstance(proj, dict)
        assert proj["role"] == "result"
        assert proj["trace_id"] == "trace_proj"
        assert proj["task_id"] == "task_proj"

    def test_projection_omits_none_values(self):
        from core.envelope_consolidation import summarise_result_for_projection
        from core.unified.command_envelope import ResultEnvelope

        re = ResultEnvelope(task_id="t", trace_id="tr", success=True)
        proj = summarise_result_for_projection(re)
        # Fields with None values should not appear
        for v in proj.values():
            assert v is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_summarise_empty_dict(self):
        from core.envelope_consolidation import summarise_envelope

        # Empty dict: should not raise, should produce a summary with generated trace_id
        summary = summarise_envelope({})
        assert summary.trace_id is not None

    def test_summarise_object_without_attributes(self):
        from core.envelope_consolidation import summarise_envelope

        # An object that has no envelope attributes
        class Empty:
            pass

        summary = summarise_envelope(Empty())
        assert summary.trace_id is not None

    def test_extract_trace_fields_object_attributes(self):
        from core.envelope_consolidation import extract_trace_fields

        class MockEnvelope:
            trace_id = "trace_mock"
            task_id = "task_mock"
            session_id = "sess_mock"

        result = extract_trace_fields(MockEnvelope())
        assert result["trace_id"] == "trace_mock"
        assert result["task_id"] == "task_mock"
        assert result["session_id"] == "sess_mock"

    def test_task_to_command_summary_empty_object(self):
        from core.envelope_consolidation import task_to_command_summary

        class Empty:
            pass

        summary = task_to_command_summary(Empty())
        assert summary["envelope_role"] == "task"
        assert summary["trace_id"].startswith("trace_")
        assert summary["priority"] == 5
        assert summary["timeout"] == 30.0

    def test_result_to_observation_plain_dict(self):
        from core.envelope_consolidation import result_to_observation

        d = {
            "task_id": "task_d",
            "trace_id": "trace_d",
            "success": False,
            "error": "network timeout",
            "error_code": "TR_001",
            "elapsed_ms": 5000.0,
            "device_id": "remote_dev",
        }
        obs = result_to_observation(d)
        assert obs["trace"]["trace_id"] == "trace_d"
        assert obs["message"] == "network timeout"
        assert obs["metadata"]["error_code"] == "TR_001"

    def test_envelope_summary_no_metadata(self):
        from core.envelope_consolidation import EnvelopeSummary, EnvelopeRole

        summary = EnvelopeSummary(
            role=EnvelopeRole.INTERACTION,
            trace_id="t",
            task_id=None,
            runtime_session_id=None,
            label="Test",
        )
        d = summary.to_dict()
        assert "metadata" not in d  # empty metadata dict omitted
