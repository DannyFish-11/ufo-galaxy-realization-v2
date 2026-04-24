#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_flow_level_operator_surface.py
==========================================
PR-7V2 — Flow-Level Operator Surface contracts.

Validates:
  1.  FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY sentinel is importable.
  2.  FLOW_LEVEL_OPERATOR_SURFACE_POLICY is a non-empty string.
  3.  AndroidExecutionPhase members are correct strings.
  4.  AndroidExecutionPhase.is_terminal() returns True for completed / failed.
  5.  AndroidExecutionPhase.is_blocking() returns True for stagnation / gate.
  6.  AndroidExecutionPhase.from_string() handles unknown gracefully.
  7.  AndroidCanonicalExecutionEvent is a dataclass with required fields.
  8.  AndroidCanonicalExecutionEvent.to_dict() is JSON-serialisable.
  9.  FlowOperatorProjection is a dataclass with required operator artifacts.
  10. FlowOperatorProjection.to_dict() is JSON-serialisable.
  11. FlowOperatorProjection.to_dict() contains all required operator-facing keys.
  12. get_flow_level_operator_surface() returns FlowLevelOperatorSurface.
  13. reset_flow_level_operator_surface() resets the singleton.
  14. Singleton identity: two calls return the same object.
  15. inspect_flow(unknown_id) returns None.
  16. inspect_flow(known_id) returns FlowOperatorProjection with correct identity.
  17. inspect_flow projection has flow_kind populated.
  18. inspect_flow projection has flow_phase populated.
  19. inspect_flow projection has correct canonical_task_id from object_mapping.
  20. inspect_flow projection has correct device_id from object_mapping.
  21. inspect_flow projection has review_notes list.
  22. inspect_flow is accessible via OperatorSurface.inspect_flow().
  23. OperatorSurface.inspect_flow(unknown) returns None.
  24. AndroidExecutionPhase re-exported from core.operator_surface.
  25. FlowOperatorProjection re-exported from core.operator_surface.
  26. inspect_flow result is JSON-serialisable end-to-end.
  27. AndroidCanonicalExecutionEvent with blocking phase has is_blocking True.
  28. FlowOperatorProjection default current_execution_phase is unknown.
  29. FlowLevelOperatorSurface.__all__ contains expected names.
  30. inspect_flow projection current_execution_phase defaults to unknown when
     no truth alignment events recorded.
"""

from __future__ import annotations

import json
import sys
import os
import uuid
from typing import Any, Dict

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.flow_level_operator_surface import (
    FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY,
    FLOW_LEVEL_OPERATOR_SURFACE_POLICY,
    AndroidExecutionPhase,
    AndroidCanonicalExecutionEvent,
    FlowOperatorProjection,
    FlowLevelOperatorSurface,
    get_flow_level_operator_surface,
    reset_flow_level_operator_surface,
)
import core.flow_level_operator_surface as _flos_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_all():
    """Reset all relevant singletons before/after each test."""
    reset_flow_level_operator_surface()
    try:
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()
    except Exception:
        pass
    try:
        from core.operator_surface import reset_operator_surface
        reset_operator_surface()
    except Exception:
        pass
    yield
    reset_flow_level_operator_surface()
    try:
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()
    except Exception:
        pass
    try:
        from core.operator_surface import reset_operator_surface
        reset_operator_surface()
    except Exception:
        pass


def _register_flow(
    *,
    canonical_task_id: str = "",
    device_id: str = "",
    flow_kind: str = "task_assign",
) -> "Any":
    """Create and register a DelegatedFlowEntity in the runtime."""
    from core.delegated_flow_entity import (
        create_delegated_flow_entity,
        record_delegated_flow,
        DelegatedFlowKind,
    )
    entity = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.from_string(flow_kind),
        canonical_task_id=canonical_task_id,
        device_id=device_id,
    )
    record_delegated_flow(entity)
    return entity


# ===========================================================================
# 1–2: Authority sentinels
# ===========================================================================

class TestAuthoritySentinels:
    def test_01_authority_importable(self):
        assert FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY
        assert isinstance(FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY, str)

    def test_02_policy_is_string(self):
        assert FLOW_LEVEL_OPERATOR_SURFACE_POLICY
        assert isinstance(FLOW_LEVEL_OPERATOR_SURFACE_POLICY, str)


# ===========================================================================
# 3–6: AndroidExecutionPhase
# ===========================================================================

class TestAndroidExecutionPhase:
    def test_03_phase_members_are_strings(self):
        for phase in AndroidExecutionPhase:
            assert isinstance(phase.value, str)

    def test_04_is_terminal(self):
        assert AndroidExecutionPhase.completed.is_terminal()
        assert AndroidExecutionPhase.failed.is_terminal()
        assert not AndroidExecutionPhase.execution.is_terminal()
        assert not AndroidExecutionPhase.planning.is_terminal()

    def test_05_is_blocking(self):
        assert AndroidExecutionPhase.stagnation.is_blocking()
        assert AndroidExecutionPhase.gate_decision.is_blocking()
        assert not AndroidExecutionPhase.execution.is_blocking()
        assert not AndroidExecutionPhase.planning.is_blocking()

    def test_06_from_string_unknown_graceful(self):
        assert AndroidExecutionPhase.from_string("nonexistent") is AndroidExecutionPhase.unknown
        assert AndroidExecutionPhase.from_string("") is AndroidExecutionPhase.unknown
        assert AndroidExecutionPhase.from_string(None) is AndroidExecutionPhase.unknown  # type: ignore[arg-type]

    def test_06b_from_string_valid(self):
        assert AndroidExecutionPhase.from_string("planning") is AndroidExecutionPhase.planning
        assert AndroidExecutionPhase.from_string("grounding") is AndroidExecutionPhase.grounding
        assert AndroidExecutionPhase.from_string("replan") is AndroidExecutionPhase.replan


# ===========================================================================
# 7–8: AndroidCanonicalExecutionEvent
# ===========================================================================

class TestAndroidCanonicalExecutionEvent:
    def test_07_dataclass_fields(self):
        ev = AndroidCanonicalExecutionEvent(
            flow_id="flow_x",
            phase=AndroidExecutionPhase.execution,
            step_index=3,
            detail="step 3 of 7",
        )
        assert ev.flow_id == "flow_x"
        assert ev.phase == AndroidExecutionPhase.execution
        assert ev.step_index == 3
        assert ev.detail == "step 3 of 7"
        assert ev.is_blocking is False

    def test_08_to_dict_json_serialisable(self):
        ev = AndroidCanonicalExecutionEvent(
            flow_id="f1",
            phase=AndroidExecutionPhase.stagnation,
            is_blocking=True,
            blocking_reason="no progress in 5 steps",
        )
        d = ev.to_dict()
        json.dumps(d)  # must not raise
        assert d["phase"] == "stagnation"
        assert d["is_blocking"] is True
        assert d["blocking_reason"] == "no progress in 5 steps"


# ===========================================================================
# 9–11: FlowOperatorProjection
# ===========================================================================

class TestFlowOperatorProjection:
    _REQUIRED_KEYS = [
        "flow_id",
        "flow_lineage_id",
        "flow_segment_id",
        "trace_id",
        "flow_kind",
        "flow_phase",
        "canonical_task_id",
        "dispatch_record_id",
        "contract_id",
        "binding_id",
        "device_id",
        "android_flow_id",
        "current_execution_phase",
        "last_android_execution_event",
        "blocking_reason",
        "recovery_status",
        "truth_alignment_status",
        "canonical_result_status",
        "created_at",
        "last_updated_at",
        "review_notes",
        "_source",
    ]

    def test_09_dataclass_fields(self):
        proj = FlowOperatorProjection(flow_id="f1", flow_kind="task_assign")
        assert proj.flow_id == "f1"
        assert proj.flow_kind == "task_assign"
        assert isinstance(proj.review_notes, list)

    def test_10_to_dict_json_serialisable(self):
        proj = FlowOperatorProjection(
            flow_id="f1",
            current_execution_phase="execution",
            recovery_status="not_recovered",
        )
        json.dumps(proj.to_dict())  # must not raise

    def test_11_to_dict_required_keys(self):
        proj = FlowOperatorProjection(flow_id="f1")
        d = proj.to_dict()
        for key in self._REQUIRED_KEYS:
            assert key in d, f"{key!r} missing from FlowOperatorProjection.to_dict()"


# ===========================================================================
# 12–15: Singleton and graceful degradation
# ===========================================================================

class TestSingletonAndGraceful:
    def test_12_get_returns_instance(self):
        surface = get_flow_level_operator_surface()
        assert isinstance(surface, FlowLevelOperatorSurface)

    def test_13_reset_creates_new_instance(self):
        s1 = get_flow_level_operator_surface()
        reset_flow_level_operator_surface()
        s2 = get_flow_level_operator_surface()
        assert s1 is not s2

    def test_14_singleton_identity(self):
        s1 = get_flow_level_operator_surface()
        s2 = get_flow_level_operator_surface()
        assert s1 is s2

    def test_15_inspect_flow_unknown_returns_none(self):
        surface = get_flow_level_operator_surface()
        assert surface.inspect_flow("nonexistent_flow_id") is None


# ===========================================================================
# 16–21: Live flow inspection
# ===========================================================================

class TestLiveFlowInspection:
    def test_16_inspect_flow_known_returns_projection(self):
        entity = _register_flow(canonical_task_id="task_abc", device_id="dev_1")
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert isinstance(proj, FlowOperatorProjection)
        assert proj.flow_id == entity.delegated_flow_id

    def test_17_inspect_flow_kind_populated(self):
        entity = _register_flow(flow_kind="goal_execution")
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert proj.flow_kind == "goal_execution"

    def test_18_inspect_flow_phase_populated(self):
        entity = _register_flow()
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert proj.flow_phase != ""  # at minimum "created"

    def test_19_inspect_flow_canonical_task_id(self):
        entity = _register_flow(canonical_task_id="canonical_xyz")
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert proj.canonical_task_id == "canonical_xyz"

    def test_20_inspect_flow_device_id(self):
        entity = _register_flow(device_id="android_device_42")
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert proj.device_id == "android_device_42"

    def test_21_inspect_flow_review_notes_is_list(self):
        entity = _register_flow()
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert isinstance(proj.review_notes, list)


# ===========================================================================
# 22–23: OperatorSurface.inspect_flow delegation
# ===========================================================================

class TestOperatorSurfaceDelegation:
    def test_22_operator_surface_inspect_flow_known(self):
        from core.operator_surface import get_operator_surface
        entity = _register_flow(canonical_task_id="t99")
        surface = get_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert proj.flow_id == entity.delegated_flow_id

    def test_23_operator_surface_inspect_flow_unknown(self):
        from core.operator_surface import get_operator_surface
        surface = get_operator_surface()
        assert surface.inspect_flow("nonexistent") is None


# ===========================================================================
# 24–26: Re-exports and serialisation
# ===========================================================================

class TestReExportsAndSerialisation:
    def test_24_android_execution_phase_re_exported(self):
        from core.operator_surface import AndroidExecutionPhase as AP
        assert AP.planning == AndroidExecutionPhase.planning

    def test_25_flow_operator_projection_re_exported(self):
        from core.operator_surface import FlowOperatorProjection as FOP
        assert FOP is FlowOperatorProjection

    def test_26_inspect_flow_result_json_serialisable(self):
        entity = _register_flow(canonical_task_id="serialise_task")
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        json.dumps(proj.to_dict())  # must not raise


# ===========================================================================
# 27–30: Edge cases and defaults
# ===========================================================================

class TestEdgeCasesAndDefaults:
    def test_27_blocking_event_has_is_blocking_true(self):
        ev = AndroidCanonicalExecutionEvent(
            phase=AndroidExecutionPhase.gate_decision,
            is_blocking=True,
            blocking_reason="Safety gate triggered",
        )
        assert ev.is_blocking is True
        d = ev.to_dict()
        assert d["is_blocking"] is True

    def test_28_default_execution_phase_is_unknown(self):
        proj = FlowOperatorProjection()
        assert proj.current_execution_phase == AndroidExecutionPhase.unknown.value

    def test_29_all_exports_present(self):
        expected = [
            "FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY",
            "FLOW_LEVEL_OPERATOR_SURFACE_POLICY",
            "AndroidExecutionPhase",
            "AndroidCanonicalExecutionEvent",
            "FlowOperatorProjection",
            "FlowLevelOperatorSurface",
            "get_flow_level_operator_surface",
            "reset_flow_level_operator_surface",
        ]
        for name in expected:
            assert name in _flos_mod.__all__, f"{name!r} missing from __all__"

    def test_30_no_truth_alignment_events_phase_unknown(self):
        """When no truth alignment events recorded, phase stays unknown."""
        entity = _register_flow()
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(entity.delegated_flow_id)
        assert proj is not None
        assert proj.current_execution_phase == AndroidExecutionPhase.unknown.value
        assert proj.last_android_execution_event is None
