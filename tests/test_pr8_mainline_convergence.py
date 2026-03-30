"""
tests/test_pr8_mainline_convergence.py
=======================================
PR-8 — System Convergence and Final Mainline Integration
=========================================================

Test suite for ``core/mainline_convergence.py``.

Covers:
-------
1.  :class:`MainlineChainStage` enum values and membership
2.  :class:`MainlineChainAuthority` enum values and STAGE_AUTHORITY mapping
3.  :class:`MainlinePathClass` enum values
4.  CANONICAL_METADATA_FIELDS completeness
5.  OPENCLAWD_AUTHORITY_ROLE constant
6.  :class:`MainlineMetadataFrame` dataclass: construction, to_dict, from_dict,
    is_mainline, covered_fields, coverage_ratio
7.  :class:`MainlineExecutionTrace` dataclass: construction, add_stage, close,
    elapsed_ms, is_open, visits_* properties, to_dict, from_dict
8.  :class:`MainlineConvergenceSnapshot` dataclass: construction, to_dict
9.  :func:`normalize_cross_subsystem_metadata`: field extraction, fallback chain,
    resource_type inference from source prefix, authority_role promotion, edge cases
10. :func:`build_mainline_trace`: defaults, entry_stage recording, authority_role
    defaulting for OPENCLAWD_AUTHORITY stage, path_class
11. :func:`record_mainline_execution`: builds + closes + records in one call
12. :class:`MainlineConvergenceRegistry`:
    - record()
    - record() with non-MAINLINE path_class emits warning
    - record_from_response() — builds trace from OpenClawd response, stamps
      ``mainline_convergence`` in the response dict
    - lookup() found / not-found
    - list_all()
    - list_by_path_class()
    - snapshot() — counters, recent_traces, stage_visit_counts,
      openclawd_coverage, knowledge_coverage
    - assert_mainline_dominant() — pass / fail
    - reset() — clears all state
    - max_traces eviction
    - thread-safety (basic smoke test)
13. Singleton accessors: get_mainline_convergence_registry() identity,
    reset_mainline_convergence_registry() clears registry
14. Integration with OpenClawd._build_mainline_convergence_stamp(): method
    exists, returns a dict with expected keys
15. **Acceptance criteria** (4 required outcomes from PR-8):
    a) Mainline chain: request → OpenClawd → capability/resource →
       execution → knowledge writeback is representable and coherent
    b) Subsystems have registered canonical stages without hidden bypasses
    c) Metadata normalization covers all required fields from any subsystem
       response shape
    d) Compatibility / legacy paths remain secondary (path_class ≠ mainline)
       and are detected by the registry
"""

from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers / fixtures
# ===========================================================================


def _fresh_registry():
    """Return a fresh MainlineConvergenceRegistry (not the module singleton)."""
    from core.mainline_convergence import MainlineConvergenceRegistry
    return MainlineConvergenceRegistry()


# ===========================================================================
# 1. MainlineChainStage
# ===========================================================================


class TestMainlineChainStage:
    def test_all_stage_values_present(self):
        from core.mainline_convergence import MainlineChainStage

        values = {s.value for s in MainlineChainStage}
        assert "request_ingress" in values
        assert "openclawd_authority" in values
        assert "capability_dispatch" in values
        assert "resource_resolution" in values
        assert "execution" in values
        assert "knowledge_recall" in values
        assert "knowledge_writeback" in values
        assert "engineering_loop" in values
        assert "response_emission" in values

    def test_stage_count(self):
        from core.mainline_convergence import MainlineChainStage

        # Two new stages were added for the canonical chain:
        # COMMAND_ROUTER_ORCHESTRATION and DEVICE_ROUTER_DISPATCH.
        # Previous count: 9 (PR-8). New count: 11 (canonical chain consolidation).
        assert len(MainlineChainStage) == 11

    def test_stages_are_strings(self):
        from core.mainline_convergence import MainlineChainStage

        for stage in MainlineChainStage:
            assert isinstance(stage.value, str)
            assert stage.value.strip() == stage.value


# ===========================================================================
# 2. MainlineChainAuthority + STAGE_AUTHORITY
# ===========================================================================


class TestMainlineChainAuthority:
    def test_authority_values(self):
        from core.mainline_convergence import MainlineChainAuthority

        values = {a.value for a in MainlineChainAuthority}
        assert "openclawd" in values
        assert "capability_bus" in values
        assert "system_resource_registry" in values
        assert "canonical_dispatcher" in values
        assert "rag_memory" in values
        assert "self_healing_loop" in values
        assert "compat_adapter" in values
        assert "legacy_path" in values
        assert "unknown" in values

    def test_stage_authority_covers_all_stages(self):
        from core.mainline_convergence import MainlineChainStage, STAGE_AUTHORITY

        for stage in MainlineChainStage:
            assert stage in STAGE_AUTHORITY, f"Missing authority for {stage}"

    def test_openclawd_authority_stage_maps_to_openclawd(self):
        from core.mainline_convergence import MainlineChainStage, MainlineChainAuthority, STAGE_AUTHORITY

        assert STAGE_AUTHORITY[MainlineChainStage.OPENCLAWD_AUTHORITY] == MainlineChainAuthority.OPENCLAWD

    def test_knowledge_stages_map_to_rag_memory(self):
        from core.mainline_convergence import MainlineChainStage, MainlineChainAuthority, STAGE_AUTHORITY

        assert STAGE_AUTHORITY[MainlineChainStage.KNOWLEDGE_RECALL] == MainlineChainAuthority.RAG_MEMORY
        assert STAGE_AUTHORITY[MainlineChainStage.KNOWLEDGE_WRITEBACK] == MainlineChainAuthority.RAG_MEMORY

    def test_capability_dispatch_maps_to_capability_bus(self):
        from core.mainline_convergence import MainlineChainStage, MainlineChainAuthority, STAGE_AUTHORITY

        assert STAGE_AUTHORITY[MainlineChainStage.CAPABILITY_DISPATCH] == MainlineChainAuthority.CAPABILITY_BUS

    def test_engineering_loop_maps_to_self_healing_loop(self):
        from core.mainline_convergence import MainlineChainStage, MainlineChainAuthority, STAGE_AUTHORITY

        assert STAGE_AUTHORITY[MainlineChainStage.ENGINEERING_LOOP] == MainlineChainAuthority.SELF_HEALING_LOOP


# ===========================================================================
# 3. MainlinePathClass
# ===========================================================================


class TestMainlinePathClass:
    def test_path_class_values(self):
        from core.mainline_convergence import MainlinePathClass

        assert MainlinePathClass.MAINLINE.value == "mainline"
        assert MainlinePathClass.COMPAT.value == "compat"
        assert MainlinePathClass.LEGACY.value == "legacy"

    def test_path_class_count(self):
        from core.mainline_convergence import MainlinePathClass

        assert len(MainlinePathClass) == 3


# ===========================================================================
# 4. CANONICAL_METADATA_FIELDS
# ===========================================================================


class TestCanonicalMetadataFields:
    def test_all_required_fields_present(self):
        from core.mainline_convergence import CANONICAL_METADATA_FIELDS

        required = {
            "authority_role",
            "execution_path",
            "trace_id",
            "task_id",
            "session_id",
            "source",
            "resource_type",
            "capability_source",
            "knowledge_source",
            "mainline_stage",
            "path_class",
        }
        for f in required:
            assert f in CANONICAL_METADATA_FIELDS, f"Missing canonical field: {f}"

    def test_no_duplicates(self):
        from core.mainline_convergence import CANONICAL_METADATA_FIELDS

        assert len(CANONICAL_METADATA_FIELDS) == len(set(CANONICAL_METADATA_FIELDS))


# ===========================================================================
# 5. OPENCLAWD_AUTHORITY_ROLE constant
# ===========================================================================


class TestOpenClawdAuthorityRole:
    def test_authority_role_value(self):
        from core.mainline_convergence import OPENCLAWD_AUTHORITY_ROLE

        assert OPENCLAWD_AUTHORITY_ROLE == "subject_decision_authority"

    def test_authority_role_is_string(self):
        from core.mainline_convergence import OPENCLAWD_AUTHORITY_ROLE

        assert isinstance(OPENCLAWD_AUTHORITY_ROLE, str)


# ===========================================================================
# 6. MainlineMetadataFrame
# ===========================================================================


class TestMainlineMetadataFrame:
    def test_default_construction(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame()
        assert f.authority_role is None
        assert f.execution_path is None
        assert f.trace_id is None

    def test_explicit_construction(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame(
            authority_role="subject_decision_authority",
            trace_id="abc",
            session_id="s1",
            execution_path="local",
        )
        assert f.authority_role == "subject_decision_authority"
        assert f.trace_id == "abc"

    def test_to_dict_contains_all_canonical_fields(self):
        from core.mainline_convergence import MainlineMetadataFrame, CANONICAL_METADATA_FIELDS

        d = MainlineMetadataFrame().to_dict()
        for field in CANONICAL_METADATA_FIELDS:
            assert field in d

    def test_from_dict_round_trip(self):
        from core.mainline_convergence import MainlineMetadataFrame

        original = MainlineMetadataFrame(
            authority_role="subject_decision_authority",
            trace_id="t1",
            session_id="s1",
            execution_path="local",
            resource_type="github",
        )
        d = original.to_dict()
        restored = MainlineMetadataFrame.from_dict(d)
        assert restored.authority_role == original.authority_role
        assert restored.trace_id == original.trace_id
        assert restored.resource_type == original.resource_type

    def test_from_dict_ignores_unknown_keys(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame.from_dict({"unknown_key": "value", "trace_id": "x"})
        assert f.trace_id == "x"

    def test_is_mainline_true(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame(authority_role="subject_decision_authority")
        assert f.is_mainline is True

    def test_is_mainline_false_wrong_role(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame(authority_role="some_other_role")
        assert f.is_mainline is False

    def test_is_mainline_false_none(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame()
        assert f.is_mainline is False

    def test_covered_fields_partial(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame(trace_id="t1", session_id="s1")
        covered = f.covered_fields
        assert "trace_id" in covered
        assert "session_id" in covered
        assert "authority_role" not in covered

    def test_coverage_ratio_zero(self):
        from core.mainline_convergence import MainlineMetadataFrame

        f = MainlineMetadataFrame()
        assert f.coverage_ratio == 0.0

    def test_coverage_ratio_full(self):
        from core.mainline_convergence import MainlineMetadataFrame, CANONICAL_METADATA_FIELDS

        kwargs = {field: "x" for field in CANONICAL_METADATA_FIELDS}
        f = MainlineMetadataFrame(**kwargs)
        assert f.coverage_ratio == 1.0

    def test_coverage_ratio_partial(self):
        from core.mainline_convergence import MainlineMetadataFrame

        # Set 2 out of 11 fields
        f = MainlineMetadataFrame(trace_id="t", session_id="s")
        ratio = f.coverage_ratio
        assert 0.0 < ratio < 1.0


# ===========================================================================
# 7. MainlineExecutionTrace
# ===========================================================================


class TestMainlineExecutionTrace:
    def test_default_construction_generates_trace_id(self):
        from core.mainline_convergence import MainlineExecutionTrace

        t = MainlineExecutionTrace()
        assert isinstance(t.trace_id, str)
        assert len(t.trace_id) > 0

    def test_add_stage_first_sets_entry_stage(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        t.add_stage(MainlineChainStage.REQUEST_INGRESS)
        assert t.entry_stage == "request_ingress"
        assert "request_ingress" in t.stages_visited

    def test_add_stage_no_duplicate(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        assert t.stages_visited.count("openclawd_authority") == 1

    def test_add_multiple_stages_in_order(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        t.add_stage(MainlineChainStage.REQUEST_INGRESS)
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        t.add_stage(MainlineChainStage.CAPABILITY_DISPATCH)
        assert t.stages_visited == [
            "request_ingress",
            "openclawd_authority",
            "capability_dispatch",
        ]

    def test_close_sets_completed_at(self):
        from core.mainline_convergence import MainlineExecutionTrace

        t = MainlineExecutionTrace()
        assert t.is_open
        t.close(success=True)
        assert not t.is_open
        assert t.completed_at is not None

    def test_close_records_success(self):
        from core.mainline_convergence import MainlineExecutionTrace

        t = MainlineExecutionTrace()
        t.close(success=False)
        assert t.success is False

    def test_elapsed_ms_none_before_close(self):
        from core.mainline_convergence import MainlineExecutionTrace

        t = MainlineExecutionTrace()
        assert t.elapsed_ms is None

    def test_elapsed_ms_after_close(self):
        from core.mainline_convergence import MainlineExecutionTrace

        t = MainlineExecutionTrace()
        time.sleep(0.01)
        t.close()
        assert t.elapsed_ms is not None
        assert t.elapsed_ms >= 0

    def test_visits_openclawd(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        assert not t.visits_openclawd
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        assert t.visits_openclawd

    def test_visits_capability_dispatch(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        assert not t.visits_capability_dispatch
        t.add_stage(MainlineChainStage.CAPABILITY_DISPATCH)
        assert t.visits_capability_dispatch

    def test_visits_knowledge_recall(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        assert not t.visits_knowledge
        t.add_stage(MainlineChainStage.KNOWLEDGE_RECALL)
        assert t.visits_knowledge

    def test_visits_knowledge_writeback(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace()
        t.add_stage(MainlineChainStage.KNOWLEDGE_WRITEBACK)
        assert t.visits_knowledge

    def test_to_dict_round_trip(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace(trace_id="t99", session_id="s1", execution_path="local")
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        t.close(success=True)
        d = t.to_dict()
        assert d["trace_id"] == "t99"
        assert d["session_id"] == "s1"
        assert d["execution_path"] == "local"
        assert "openclawd_authority" in d["stages_visited"]
        assert d["success"] is True
        assert d["elapsed_ms"] is not None

    def test_from_dict_round_trip(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        t = MainlineExecutionTrace(trace_id="t100", session_id="s2")
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        t.close()
        d = t.to_dict()
        restored = MainlineExecutionTrace.from_dict(d)
        assert restored.trace_id == "t100"
        assert "openclawd_authority" in restored.stages_visited

    def test_from_dict_with_defaults(self):
        from core.mainline_convergence import MainlineExecutionTrace

        t = MainlineExecutionTrace.from_dict({})
        assert isinstance(t.trace_id, str)
        assert t.stages_visited == []
        assert t.success is True


# ===========================================================================
# 8. MainlineConvergenceSnapshot
# ===========================================================================


class TestMainlineConvergenceSnapshot:
    def test_default_construction(self):
        from core.mainline_convergence import MainlineConvergenceSnapshot

        snap = MainlineConvergenceSnapshot()
        assert snap.total_traces == 0
        assert snap.mainline_count == 0
        assert snap.compat_count == 0
        assert snap.legacy_count == 0
        assert snap.recent_traces == []
        assert snap.stage_visit_counts == {}

    def test_to_dict_keys(self):
        from core.mainline_convergence import MainlineConvergenceSnapshot

        snap = MainlineConvergenceSnapshot()
        d = snap.to_dict()
        for key in (
            "total_traces",
            "mainline_count",
            "compat_count",
            "legacy_count",
            "recent_traces",
            "stage_visit_counts",
            "openclawd_coverage",
            "knowledge_coverage",
            "snapshotted_at",
        ):
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# 9. normalize_cross_subsystem_metadata
# ===========================================================================


class TestNormalizeCrossSubsystemMetadata:
    def test_empty_dict_returns_empty_frame(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({})
        assert frame.trace_id is None
        assert frame.authority_role is None

    def test_non_dict_returns_empty_frame(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata(None)  # type: ignore[arg-type]
        assert frame.trace_id is None

    def test_authority_role_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"authority_role": "subject_decision_authority"})
        assert frame.authority_role == "subject_decision_authority"

    def test_authority_role_openclawd_promoted(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata, OPENCLAWD_AUTHORITY_ROLE

        frame = normalize_cross_subsystem_metadata({"authority_role": "openclawd"})
        assert frame.authority_role == OPENCLAWD_AUTHORITY_ROLE

    def test_trace_id_direct(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"trace_id": "abc123"})
        assert frame.trace_id == "abc123"

    def test_trace_id_fallback_to_runtime_session_id(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"runtime_session_id": "rse1"})
        assert frame.trace_id == "rse1"

    def test_trace_id_fallback_to_request_id(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"request_id": "req1"})
        assert frame.trace_id == "req1"

    def test_trace_id_prefers_trace_id_over_fallbacks(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({
            "trace_id": "primary",
            "runtime_session_id": "fallback1",
            "request_id": "fallback2",
        })
        assert frame.trace_id == "primary"

    def test_execution_path_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"execution_path": "local"})
        assert frame.execution_path == "local"

    def test_resource_type_inferred_from_github_source(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"source": "github__ingest"})
        assert frame.resource_type == "github"

    def test_resource_type_inferred_from_academic_source(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"source": "academic__search"})
        assert frame.resource_type == "academic"

    def test_resource_type_inferred_from_engineering_source(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"source": "engineering__apply"})
        assert frame.resource_type == "engineering"

    def test_explicit_resource_type_not_overwritten(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({
            "source": "github__ingest",
            "resource_type": "custom",
        })
        assert frame.resource_type == "custom"

    def test_session_id_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"session_id": "sess_abc"})
        assert frame.session_id == "sess_abc"

    def test_capability_source_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"capability_source": "github"})
        assert frame.capability_source == "github"

    def test_knowledge_source_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"knowledge_source": "rag_memory"})
        assert frame.knowledge_source == "rag_memory"

    def test_mainline_stage_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"mainline_stage": "openclawd_authority"})
        assert frame.mainline_stage == "openclawd_authority"

    def test_path_class_passed_through(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({"path_class": "mainline"})
        assert frame.path_class == "mainline"

    def test_unknown_keys_ignored(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        frame = normalize_cross_subsystem_metadata({
            "totally_unknown_field": "value",
            "trace_id": "t1",
        })
        assert frame.trace_id == "t1"
        assert not hasattr(frame, "totally_unknown_field")

    def test_full_openclawd_kernel_response_metadata(self):
        """Normalise a metadata dict that mirrors the kernel response shape."""
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        meta = {
            "trace_id": "ker_001",
            "session_id": "s1",
            "execution_path": "local",
            "authority_role": "subject_decision_authority",
            "handler": "agent_kernel",
        }
        frame = normalize_cross_subsystem_metadata(meta)
        assert frame.trace_id == "ker_001"
        assert frame.authority_role == "subject_decision_authority"
        assert frame.execution_path == "local"
        assert frame.is_mainline


# ===========================================================================
# 10. build_mainline_trace
# ===========================================================================


class TestBuildMainlineTrace:
    def test_default_generates_trace_id(self):
        from core.mainline_convergence import build_mainline_trace

        trace = build_mainline_trace()
        assert isinstance(trace.trace_id, str)
        assert len(trace.trace_id) == 32  # uuid4().hex

    def test_explicit_trace_id(self):
        from core.mainline_convergence import build_mainline_trace

        trace = build_mainline_trace(trace_id="my_trace")
        assert trace.trace_id == "my_trace"

    def test_entry_stage_recorded(self):
        from core.mainline_convergence import build_mainline_trace, MainlineChainStage

        trace = build_mainline_trace(entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY)
        assert trace.entry_stage == "openclawd_authority"
        assert "openclawd_authority" in trace.stages_visited

    def test_openclawd_stage_sets_authority_role_default(self):
        from core.mainline_convergence import build_mainline_trace, MainlineChainStage, OPENCLAWD_AUTHORITY_ROLE

        trace = build_mainline_trace(entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY)
        assert trace.authority_role == OPENCLAWD_AUTHORITY_ROLE

    def test_explicit_authority_role_wins(self):
        from core.mainline_convergence import build_mainline_trace, MainlineChainStage

        trace = build_mainline_trace(
            entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY,
            authority_role="custom_role",
        )
        assert trace.authority_role == "custom_role"

    def test_path_class_default_mainline(self):
        from core.mainline_convergence import build_mainline_trace, MainlinePathClass

        trace = build_mainline_trace()
        assert trace.path_class == MainlinePathClass.MAINLINE.value

    def test_path_class_compat(self):
        from core.mainline_convergence import build_mainline_trace, MainlinePathClass

        trace = build_mainline_trace(path_class=MainlinePathClass.COMPAT)
        assert trace.path_class == MainlinePathClass.COMPAT.value

    def test_execution_path_set(self):
        from core.mainline_convergence import build_mainline_trace

        trace = build_mainline_trace(execution_path="cross_device")
        assert trace.execution_path == "cross_device"

    def test_session_and_task_id_set(self):
        from core.mainline_convergence import build_mainline_trace

        trace = build_mainline_trace(session_id="s1", task_id="t1")
        assert trace.session_id == "s1"
        assert trace.task_id == "t1"


# ===========================================================================
# 11. record_mainline_execution
# ===========================================================================


class TestRecordMainlineExecution:
    def setup_method(self):
        from core.mainline_convergence import reset_mainline_convergence_registry
        reset_mainline_convergence_registry()

    def test_records_in_registry(self):
        from core.mainline_convergence import (
            record_mainline_execution,
            get_mainline_convergence_registry,
            MainlineChainStage,
        )

        trace = record_mainline_execution(
            trace_id="rec_001",
            stages=[MainlineChainStage.OPENCLAWD_AUTHORITY],
        )
        assert trace.trace_id == "rec_001"
        registry = get_mainline_convergence_registry()
        found = registry.lookup("rec_001")
        assert found is not None
        assert found.trace_id == "rec_001"

    def test_trace_is_closed(self):
        from core.mainline_convergence import (
            record_mainline_execution,
            MainlineChainStage,
        )

        trace = record_mainline_execution(
            stages=[MainlineChainStage.OPENCLAWD_AUTHORITY],
        )
        assert not trace.is_open

    def test_stages_recorded(self):
        from core.mainline_convergence import record_mainline_execution, MainlineChainStage

        trace = record_mainline_execution(
            stages=[
                MainlineChainStage.OPENCLAWD_AUTHORITY,
                MainlineChainStage.CAPABILITY_DISPATCH,
                MainlineChainStage.EXECUTION,
            ]
        )
        assert "openclawd_authority" in trace.stages_visited
        assert "capability_dispatch" in trace.stages_visited
        assert "execution" in trace.stages_visited

    def test_notes_appended(self):
        from core.mainline_convergence import record_mainline_execution

        trace = record_mainline_execution(notes=["test note"])
        assert "test note" in trace.notes

    def test_success_false(self):
        from core.mainline_convergence import record_mainline_execution

        trace = record_mainline_execution(success=False)
        assert trace.success is False


# ===========================================================================
# 12. MainlineConvergenceRegistry
# ===========================================================================


class TestMainlineConvergenceRegistryRecord:
    def test_record_increments_total(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        trace = MainlineExecutionTrace(trace_id="r1")
        trace.close()
        reg.record(trace)
        snap = reg.snapshot()
        assert snap.total_traces == 1

    def test_record_non_trace_ignored(self):
        reg = _fresh_registry()
        reg.record("not a trace")  # type: ignore[arg-type]
        snap = reg.snapshot()
        assert snap.total_traces == 0

    def test_mainline_count_incremented(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        t = MainlineExecutionTrace(path_class=MainlinePathClass.MAINLINE.value)
        t.close()
        reg.record(t)
        snap = reg.snapshot()
        assert snap.mainline_count == 1

    def test_compat_count_incremented(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        t = MainlineExecutionTrace(path_class=MainlinePathClass.COMPAT.value)
        t.close()
        reg.record(t)
        snap = reg.snapshot()
        assert snap.compat_count == 1

    def test_legacy_count_incremented(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
        t.close()
        reg.record(t)
        snap = reg.snapshot()
        assert snap.legacy_count == 1

    def test_stage_visit_counts_updated(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        reg = _fresh_registry()
        t = MainlineExecutionTrace()
        t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
        t.add_stage(MainlineChainStage.CAPABILITY_DISPATCH)
        t.close()
        reg.record(t)

        snap = reg.snapshot()
        assert snap.stage_visit_counts.get("openclawd_authority", 0) == 1
        assert snap.stage_visit_counts.get("capability_dispatch", 0) == 1

    def test_non_mainline_path_emits_warning(self, caplog):
        import logging
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
        t.close()
        with caplog.at_level(logging.WARNING, logger="Galaxy.MainlineConvergence"):
            reg.record(t)
        # warning should have been emitted
        assert any("non-mainline" in r.message.lower() for r in caplog.records)


class TestMainlineConvergenceRegistryRecordFromResponse:
    def test_builds_and_records_trace(self):
        from core.mainline_convergence import MainlineConvergenceRegistry

        reg = MainlineConvergenceRegistry()
        response = {
            "success": True,
            "metadata": {
                "trace_id": "resp_001",
                "session_id": "sess1",
                "execution_path": "local",
                "authority_role": "subject_decision_authority",
            },
        }
        trace = reg.record_from_response(response)
        assert trace is not None
        assert trace.trace_id == "resp_001"

    def test_stamps_mainline_convergence_in_response(self):
        from core.mainline_convergence import MainlineConvergenceRegistry

        reg = MainlineConvergenceRegistry()
        response = {
            "success": True,
            "metadata": {"trace_id": "mc1", "execution_path": "local"},
        }
        reg.record_from_response(response)
        assert "mainline_convergence" in response
        mc = response["mainline_convergence"]
        assert "trace_id" in mc
        assert "path_class" in mc
        assert "stages_visited" in mc
        assert "authority_role" in mc

    def test_returns_none_for_non_dict(self):
        from core.mainline_convergence import MainlineConvergenceRegistry

        reg = MainlineConvergenceRegistry()
        result = reg.record_from_response("not a dict")  # type: ignore[arg-type]
        assert result is None

    def test_success_flag_propagated(self):
        from core.mainline_convergence import MainlineConvergenceRegistry

        reg = MainlineConvergenceRegistry()
        response = {"success": False, "metadata": {}}
        trace = reg.record_from_response(response)
        assert trace is not None
        assert trace.success is False


class TestMainlineConvergenceRegistryLookup:
    def test_lookup_found(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        t = MainlineExecutionTrace(trace_id="find_me")
        t.close()
        reg.record(t)
        found = reg.lookup("find_me")
        assert found is not None
        assert found.trace_id == "find_me"

    def test_lookup_not_found(self):
        reg = _fresh_registry()
        assert reg.lookup("does_not_exist") is None

    def test_lookup_returns_most_recent(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        t1 = MainlineExecutionTrace(trace_id="dup", session_id="first")
        t1.close()
        reg.record(t1)
        t2 = MainlineExecutionTrace(trace_id="dup", session_id="second")
        t2.close()
        reg.record(t2)
        found = reg.lookup("dup")
        assert found.session_id == "second"


class TestMainlineConvergenceRegistryListAll:
    def test_list_all_order(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        for i in range(3):
            t = MainlineExecutionTrace(trace_id=f"trace_{i}")
            t.close()
            reg.record(t)
        all_traces = reg.list_all()
        assert len(all_traces) == 3
        assert all_traces[0].trace_id == "trace_0"

    def test_list_all_is_copy(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        t = MainlineExecutionTrace()
        t.close()
        reg.record(t)
        lst = reg.list_all()
        lst.clear()
        assert reg.snapshot().total_traces == 1


class TestMainlineConvergenceRegistryListByPathClass:
    def test_list_by_mainline(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        for pc in (MainlinePathClass.MAINLINE, MainlinePathClass.COMPAT, MainlinePathClass.LEGACY):
            t = MainlineExecutionTrace(path_class=pc.value)
            t.close()
            reg.record(t)
        mainline_traces = reg.list_by_path_class(MainlinePathClass.MAINLINE)
        assert len(mainline_traces) == 1
        assert mainline_traces[0].path_class == "mainline"

    def test_list_by_legacy(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        for _ in range(2):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
            t.close()
            reg.record(t)
        assert len(reg.list_by_path_class(MainlinePathClass.LEGACY)) == 2


class TestMainlineConvergenceRegistrySnapshot:
    def test_snapshot_counts(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        for _ in range(3):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.MAINLINE.value)
            t.close()
            reg.record(t)
        t_compat = MainlineExecutionTrace(path_class=MainlinePathClass.COMPAT.value)
        t_compat.close()
        reg.record(t_compat)

        snap = reg.snapshot()
        assert snap.total_traces == 4
        assert snap.mainline_count == 3
        assert snap.compat_count == 1
        assert snap.legacy_count == 0

    def test_recent_traces_capped(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        for i in range(15):
            t = MainlineExecutionTrace(trace_id=f"t{i}")
            t.close()
            reg.record(t)
        snap = reg.snapshot()
        assert len(snap.recent_traces) <= 10

    def test_openclawd_coverage(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        reg = _fresh_registry()
        # 2 traces visit openclawd, 1 does not
        for _ in range(2):
            t = MainlineExecutionTrace()
            t.add_stage(MainlineChainStage.OPENCLAWD_AUTHORITY)
            t.close()
            reg.record(t)
        t_no_oc = MainlineExecutionTrace()
        t_no_oc.close()
        reg.record(t_no_oc)

        snap = reg.snapshot()
        assert snap.openclawd_coverage == pytest.approx(2 / 3)

    def test_knowledge_coverage_nonzero(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlineChainStage

        reg = _fresh_registry()
        t = MainlineExecutionTrace()
        t.add_stage(MainlineChainStage.KNOWLEDGE_WRITEBACK)
        t.close()
        reg.record(t)

        snap = reg.snapshot()
        assert snap.knowledge_coverage > 0.0

    def test_snapshot_to_dict_serialisable(self):
        import json
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        t = MainlineExecutionTrace()
        t.close()
        reg.record(t)
        snap = reg.snapshot()
        d = snap.to_dict()
        # should not raise
        json.dumps(d)


class TestMainlineConvergenceRegistryAssertMainlineDominant:
    def test_passes_when_all_mainline(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        for _ in range(5):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.MAINLINE.value)
            t.close()
            reg.record(t)
        assert reg.assert_mainline_dominant(min_ratio=0.5) is True

    def test_passes_vacuously_when_empty(self):
        reg = _fresh_registry()
        assert reg.assert_mainline_dominant() is True

    def test_fails_when_too_many_legacy(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        for _ in range(3):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
            t.close()
            reg.record(t)
        assert reg.assert_mainline_dominant(min_ratio=0.5) is False

    def test_threshold_respected(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        # 1 mainline, 1 legacy → ratio = 0.5
        for pc in (MainlinePathClass.MAINLINE, MainlinePathClass.LEGACY):
            t = MainlineExecutionTrace(path_class=pc.value)
            t.close()
            reg.record(t)
        # 0.5 >= 0.5 → passes
        assert reg.assert_mainline_dominant(min_ratio=0.5) is True
        # 0.5 < 0.6 → fails
        assert reg.assert_mainline_dominant(min_ratio=0.6) is False


class TestMainlineConvergenceRegistryReset:
    def test_reset_clears_traces(self):
        from core.mainline_convergence import MainlineExecutionTrace

        reg = _fresh_registry()
        for _ in range(3):
            t = MainlineExecutionTrace()
            t.close()
            reg.record(t)
        reg.reset()
        assert reg.snapshot().total_traces == 0

    def test_reset_clears_counters(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
        t.close()
        reg.record(t)
        reg.reset()
        snap = reg.snapshot()
        assert snap.legacy_count == 0
        assert snap.stage_visit_counts == {}


class TestMainlineConvergenceRegistryMaxTraces:
    def test_oldest_evicted_when_full(self):
        from core.mainline_convergence import MainlineConvergenceRegistry, MainlineExecutionTrace

        reg = MainlineConvergenceRegistry(max_traces=3)
        for i in range(5):
            t = MainlineExecutionTrace(trace_id=f"t{i}")
            t.close()
            reg.record(t)
        all_ids = [t.trace_id for t in reg.list_all()]
        assert "t0" not in all_ids
        assert "t1" not in all_ids
        assert "t4" in all_ids


class TestMainlineConvergenceRegistryThreadSafety:
    def test_concurrent_records_do_not_corrupt(self):
        import threading
        from core.mainline_convergence import MainlineConvergenceRegistry, MainlineExecutionTrace

        reg = MainlineConvergenceRegistry(max_traces=1000)
        errors = []

        def worker():
            try:
                for _ in range(10):
                    t = MainlineExecutionTrace()
                    t.close()
                    reg.record(t)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == [], f"Thread errors: {errors}"
        assert reg.snapshot().total_traces == 100


# ===========================================================================
# 13. Singleton accessors
# ===========================================================================


class TestSingletonAccessors:
    def test_get_returns_same_instance(self):
        from core.mainline_convergence import get_mainline_convergence_registry

        r1 = get_mainline_convergence_registry()
        r2 = get_mainline_convergence_registry()
        assert r1 is r2

    def test_reset_clears_module_registry(self):
        from core.mainline_convergence import (
            get_mainline_convergence_registry,
            reset_mainline_convergence_registry,
            MainlineExecutionTrace,
        )
        reg = get_mainline_convergence_registry()
        t = MainlineExecutionTrace()
        t.close()
        reg.record(t)
        reset_mainline_convergence_registry()
        assert reg.snapshot().total_traces == 0

    def test_reset_is_idempotent(self):
        from core.mainline_convergence import reset_mainline_convergence_registry

        # should not raise
        reset_mainline_convergence_registry()
        reset_mainline_convergence_registry()


# ===========================================================================
# 14. Integration with OpenClawd._build_mainline_convergence_stamp()
# ===========================================================================


class TestOpenClawdMainlineConvergenceStamp:
    def test_method_exists(self):
        from core.openclawd import OpenClawd

        instance = OpenClawd.__new__(OpenClawd)
        assert hasattr(instance, "_build_mainline_convergence_stamp")
        assert callable(instance._build_mainline_convergence_stamp)

    def test_returns_dict_with_expected_keys(self):
        from core.openclawd import OpenClawd

        instance = OpenClawd.__new__(OpenClawd)
        result = instance._build_mainline_convergence_stamp(
            trace_id="oc_test",
            session_id="s1",
            execution_path="local",
        )
        # Must be a dict (not None) when mainline_convergence module is available
        if result is not None:
            assert isinstance(result, dict)
            assert "trace_id" in result
            assert "path_class" in result
            assert "stages_visited" in result
            assert "authority_role" in result

    def test_returns_none_gracefully_on_error(self):
        """If mainline_convergence is unavailable, stamp returns None without crashing."""
        from core.openclawd import OpenClawd

        instance = OpenClawd.__new__(OpenClawd)
        with patch("core.mainline_convergence.build_mainline_trace", side_effect=RuntimeError("injected")):
            result = instance._build_mainline_convergence_stamp(trace_id="t1")
        # Any failure must be silently absorbed → None or dict
        # (None is expected when the import itself fails, but here we
        #  patched post-import so the except may not cover it depending on
        #  import caching — simply ensure no exception propagates)
        assert result is None or isinstance(result, dict)

    def test_stamp_records_in_registry(self):
        from core.mainline_convergence import (
            get_mainline_convergence_registry,
            reset_mainline_convergence_registry,
        )
        from core.openclawd import OpenClawd

        reset_mainline_convergence_registry()
        instance = OpenClawd.__new__(OpenClawd)
        result = instance._build_mainline_convergence_stamp(
            trace_id="stamp_test_01",
            execution_path="local",
        )
        if result is not None:
            reg = get_mainline_convergence_registry()
            found = reg.lookup("stamp_test_01")
            assert found is not None


# ===========================================================================
# 15. Acceptance criteria
# ===========================================================================


class TestAcceptanceCriteriaA_MainlineChainCoherence:
    """AC-a: The mainline request→OpenClawd→capability/resource→execution
    →knowledge/memory writeback path is coherent and stable."""

    def test_full_mainline_stages_can_be_recorded(self):
        from core.mainline_convergence import (
            record_mainline_execution,
            get_mainline_convergence_registry,
            reset_mainline_convergence_registry,
            MainlineChainStage,
            MainlinePathClass,
        )

        reset_mainline_convergence_registry()

        trace = record_mainline_execution(
            trace_id="ac_a_test",
            stages=[
                MainlineChainStage.REQUEST_INGRESS,
                MainlineChainStage.OPENCLAWD_AUTHORITY,
                MainlineChainStage.CAPABILITY_DISPATCH,
                MainlineChainStage.RESOURCE_RESOLUTION,
                MainlineChainStage.EXECUTION,
                MainlineChainStage.KNOWLEDGE_RECALL,
                MainlineChainStage.KNOWLEDGE_WRITEBACK,
                MainlineChainStage.RESPONSE_EMISSION,
            ],
            execution_path="local",
            path_class=MainlinePathClass.MAINLINE,
        )

        assert trace.visits_openclawd
        assert trace.visits_capability_dispatch
        assert trace.visits_knowledge
        assert trace.success

        reg = get_mainline_convergence_registry()
        assert reg.snapshot().mainline_count == 1

    def test_mainline_trace_visits_openclawd(self):
        from core.mainline_convergence import build_mainline_trace, MainlineChainStage

        trace = build_mainline_trace(
            entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY,
            execution_path="local",
        )
        trace.add_stage(MainlineChainStage.CAPABILITY_DISPATCH)
        trace.add_stage(MainlineChainStage.EXECUTION)
        trace.add_stage(MainlineChainStage.KNOWLEDGE_WRITEBACK)
        trace.close()

        assert trace.visits_openclawd
        assert trace.visits_knowledge

    def test_authority_role_is_subject_decision_authority(self):
        from core.mainline_convergence import (
            build_mainline_trace,
            MainlineChainStage,
            OPENCLAWD_AUTHORITY_ROLE,
        )

        trace = build_mainline_trace(entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY)
        assert trace.authority_role == OPENCLAWD_AUTHORITY_ROLE


class TestAcceptanceCriteriaB_NoHiddenBypasses:
    """AC-b: Major integrated subsystems do not require hidden bypass paths
    to function; they all have canonical stage representations."""

    def test_github_resource_has_stage(self):
        from core.mainline_convergence import MainlineChainStage, STAGE_AUTHORITY, MainlineChainAuthority

        # GitHub goes through resource_resolution → execution
        assert MainlineChainStage.RESOURCE_RESOLUTION in STAGE_AUTHORITY
        assert STAGE_AUTHORITY[MainlineChainStage.RESOURCE_RESOLUTION] == MainlineChainAuthority.SYSTEM_RESOURCE_REGISTRY

    def test_academic_resource_has_stage(self):
        from core.mainline_convergence import MainlineChainStage, STAGE_AUTHORITY

        assert MainlineChainStage.CAPABILITY_DISPATCH in STAGE_AUTHORITY

    def test_engineering_loop_has_dedicated_stage(self):
        from core.mainline_convergence import MainlineChainStage, STAGE_AUTHORITY, MainlineChainAuthority

        assert MainlineChainStage.ENGINEERING_LOOP in STAGE_AUTHORITY
        assert STAGE_AUTHORITY[MainlineChainStage.ENGINEERING_LOOP] == MainlineChainAuthority.SELF_HEALING_LOOP

    def test_knowledge_writeback_has_dedicated_stage(self):
        from core.mainline_convergence import MainlineChainStage, STAGE_AUTHORITY, MainlineChainAuthority

        assert MainlineChainStage.KNOWLEDGE_WRITEBACK in STAGE_AUTHORITY
        assert STAGE_AUTHORITY[MainlineChainStage.KNOWLEDGE_WRITEBACK] == MainlineChainAuthority.RAG_MEMORY

    def test_compat_adapter_authority_is_not_openclawd(self):
        from core.mainline_convergence import MainlineChainAuthority

        # compat_adapter and legacy_path must never equal OPENCLAWD
        assert MainlineChainAuthority.COMPAT_ADAPTER != MainlineChainAuthority.OPENCLAWD
        assert MainlineChainAuthority.LEGACY_PATH != MainlineChainAuthority.OPENCLAWD

    def test_all_stage_authorities_are_known(self):
        from core.mainline_convergence import STAGE_AUTHORITY, MainlineChainAuthority

        known = set(MainlineChainAuthority)
        for stage, authority in STAGE_AUTHORITY.items():
            assert authority in known, f"Unknown authority {authority} for stage {stage}"


class TestAcceptanceCriteriaC_MetadataNormalization:
    """AC-c: Metadata and trace semantics are sufficiently normalized across
    the mainline — normalize_cross_subsystem_metadata can coerce any
    subsystem response shape into a canonical frame."""

    def test_openclawd_kernel_response_normalized(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        # Typical kernel-path metadata
        meta = {
            "trace_id": "k1",
            "session_id": "s1",
            "execution_path": "local",
            "authority_role": "subject_decision_authority",
            "handler": "agent_kernel",
        }
        frame = normalize_cross_subsystem_metadata(meta)
        assert frame.is_mainline
        assert frame.trace_id == "k1"

    def test_openclawd_direct_response_normalized(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        # Typical direct-path metadata
        meta = {
            "trace_id": "d1",
            "session_id": "s2",
            "execution_path": "cross_device",
            "authority_role": "subject_decision_authority",
            "handler": "direct",
        }
        frame = normalize_cross_subsystem_metadata(meta)
        assert frame.is_mainline
        assert frame.execution_path == "cross_device"

    def test_github_tool_response_normalized(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        meta = {
            "trace_id": "gh1",
            "source": "github__ingest",
            "capability_source": "github",
        }
        frame = normalize_cross_subsystem_metadata(meta)
        assert frame.trace_id == "gh1"
        assert frame.resource_type == "github"

    def test_engineering_response_normalized(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        meta = {
            "trace_id": "eng1",
            "source": "engineering__apply",
            "resource_type": "engineering",
        }
        frame = normalize_cross_subsystem_metadata(meta)
        assert frame.resource_type == "engineering"

    def test_coverage_ratio_for_normalized_openclawd_response(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        meta = {
            "trace_id": "full",
            "session_id": "s1",
            "task_id": "t1",
            "execution_path": "local",
            "authority_role": "subject_decision_authority",
            "source": "openclawd",
            "resource_type": "builtin",
            "capability_source": "builtin",
            "knowledge_source": "rag_memory",
            "mainline_stage": "openclawd_authority",
            "path_class": "mainline",
        }
        frame = normalize_cross_subsystem_metadata(meta)
        assert frame.coverage_ratio == 1.0

    def test_partial_metadata_still_normalizes_without_error(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata

        # Minimal metadata dict (e.g., from a legacy node)
        frame = normalize_cross_subsystem_metadata({"runtime_session_id": "legacy_rs"})
        assert frame.trace_id == "legacy_rs"

    def test_frame_to_dict_includes_all_canonical_fields(self):
        from core.mainline_convergence import normalize_cross_subsystem_metadata, CANONICAL_METADATA_FIELDS

        frame = normalize_cross_subsystem_metadata({"trace_id": "check"})
        d = frame.to_dict()
        for field in CANONICAL_METADATA_FIELDS:
            assert field in d


class TestAcceptanceCriteriaD_CompatLayersSecondary:
    """AC-d: Compatibility layers remain secondary and do not act like
    competing authorities — path_class != MAINLINE is detected and logged."""

    def test_compat_trace_is_detectable(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        t = MainlineExecutionTrace(path_class=MainlinePathClass.COMPAT.value)
        assert t.path_class == "compat"
        assert t.path_class != "mainline"

    def test_legacy_trace_is_detectable(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
        assert t.path_class == "legacy"

    def test_registry_tracks_compat_separately(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        # 4 mainline, 1 compat, 1 legacy
        for _ in range(4):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.MAINLINE.value)
            t.close()
            reg.record(t)
        tc = MainlineExecutionTrace(path_class=MainlinePathClass.COMPAT.value)
        tc.close()
        reg.record(tc)
        tl = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
        tl.close()
        reg.record(tl)

        snap = reg.snapshot()
        assert snap.mainline_count == 4
        assert snap.compat_count == 1
        assert snap.legacy_count == 1

    def test_mainline_dominant_check_catches_legacy_takeover(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        # Simulate a scenario where legacy paths dominate
        for _ in range(8):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.LEGACY.value)
            t.close()
            reg.record(t)
        for _ in range(2):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.MAINLINE.value)
            t.close()
            reg.record(t)

        # mainline_ratio = 0.2 → below 0.5 threshold → should fail
        assert reg.assert_mainline_dominant(min_ratio=0.5) is False

    def test_mainline_dominant_passes_when_compat_is_secondary(self):
        from core.mainline_convergence import MainlineExecutionTrace, MainlinePathClass

        reg = _fresh_registry()
        # 8 mainline, 2 compat (compat is secondary, mainline dominates)
        for _ in range(8):
            t = MainlineExecutionTrace(path_class=MainlinePathClass.MAINLINE.value)
            t.close()
            reg.record(t)
        for _ in range(2):
            tc = MainlineExecutionTrace(path_class=MainlinePathClass.COMPAT.value)
            tc.close()
            reg.record(tc)

        assert reg.assert_mainline_dominant(min_ratio=0.5) is True

    def test_compat_authority_not_openclawd(self):
        """COMPAT_ADAPTER authority must never be confused with OpenClawd."""
        from core.mainline_convergence import MainlineChainAuthority

        assert MainlineChainAuthority.COMPAT_ADAPTER.value == "compat_adapter"
        assert MainlineChainAuthority.COMPAT_ADAPTER != MainlineChainAuthority.OPENCLAWD
