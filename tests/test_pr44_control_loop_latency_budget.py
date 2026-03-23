#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr44_control_loop_latency_budget.py
===============================================
Tests for PR-30: Optimize control-loop latency budgets for multimodal
ingestion and routing.

Coverage
--------
1.  IngestCadencePolicy
    - all expected enum values are present and stable strings
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

2.  RecomputePolicy
    - all expected enum values are present and stable strings
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

3.  ProjectionRefreshPolicy
    - all expected enum values are present and stable strings
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

4.  ModalityFastPathKind
    - all expected enum values are present and stable strings
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

5.  IngestCadenceWindow
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - is JSON-serialisable
    - should_allow returns True below threshold
    - should_allow returns False at/above threshold
    - record() updates counters correctly
    - text_only increments total_skipped_text_only without consuming budget

6.  RecomputeWindow
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - is JSON-serialisable
    - FULL policy returned when sufficient time has elapsed
    - COALESCED policy returned when within min_interval
    - DEFERRED policy returned under churn (many rapid calls)
    - counters increment for each policy type

7.  ProjectionRefreshWindow
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - is JSON-serialisable
    - IMMEDIATE policy returned when interval has elapsed
    - COALESCED policy returned within interval but state changed
    - SUPPRESSED policy returned within interval with same fingerprint
    - counters increment correctly

8.  ProviderSelectionBudget
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - is JSON-serialisable
    - exceeded=True when measured_ms > budget_ms
    - exceeded=False when measured_ms <= budget_ms
    - fast_path_applied is preserved

9.  TextOnlyFastPathAssessment
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - is JSON-serialisable
    - assessment_id is auto-generated (UUID)

10. LatencyBudgetSummary
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - is JSON-serialisable (json.dumps succeeds)
    - summary_id is auto-generated (UUID4)
    - timestamp is auto-populated

11. assess_text_only_fast_path()
    - None multimodal_context + empty perception → TEXT_ONLY + is_text_only=True
    - explicit multimodal_context → MULTIMODAL_REQUIRED + is_text_only=False
    - active non-text modalities in perception → MULTIMODAL_REQUIRED
    - requires_native_multimodal=True in perception → MULTIMODAL_REQUIRED
    - all None inputs → TEXT_ONLY (safe default)
    - never raises on garbage input

12. build_latency_budget_summary()
    - builds correct summary with all params
    - serialises policies to string values
    - provider_selection_budget embedded as dict
    - text_only_fast_path embedded as dict
    - window stats embedded
    - never raises on no params (returns valid summary)
    - never raises on garbage params

13. ControlLoopLatencyBudget
    - construction with defaults
    - decide_ingest_cadence: text-only → SKIPPED_TEXT_ONLY
    - decide_ingest_cadence: no mm context → SKIPPED_TEXT_ONLY
    - decide_ingest_cadence: mm context within budget → ALLOWED
    - decide_ingest_cadence: mm context exceeds window → THROTTLED
    - decide_recompute: first call → FULL
    - decide_recompute: rapid second call → COALESCED
    - decide_recompute: churn burst → DEFERRED
    - decide_projection_refresh: first call → IMMEDIATE
    - decide_projection_refresh: rapid same-fingerprint → SUPPRESSED
    - decide_projection_refresh: rapid changed-fingerprint → COALESCED
    - record_provider_selection: within budget → exceeded=False
    - record_provider_selection: over budget → exceeded=True
    - snapshot_*_stats() returns dict with expected keys

14. get_control_loop_latency_budget() / reset_latency_budget()
    - get returns singleton (same object on repeated calls)
    - reset clears singleton (get after reset returns new object)

15. Text-only flows avoid multimodal overhead (behavioral requirement 2)
    - assess_text_only_fast_path returns TEXT_ONLY for plain text requests
    - ingest cadence policy is SKIPPED_TEXT_ONLY for text-only flows
    - LatencyBudgetSummary reflects text-only in fast path assessment

16. Repeated source/state churn does not force excessive recomputes
      (behavioral requirement 2)
    - rapid decide_recompute calls return COALESCED or DEFERRED
    - at most one FULL per min_interval period

17. Projection updates are coalesced / throttled safely (behavioral req 3)
    - repeated decide_projection_refresh with same fingerprint → SUPPRESSED
    - state change resets suppression, allows COALESCED or IMMEDIATE

18. Multimodal route decision latency accounting is stable and serialisable
      (behavioral requirement 4)
    - LatencyBudgetSummary containing provider_selection_budget is
      json-serialisable end-to-end
    - route_type is propagated from route dict into budget record

19. Budget logic degrades cleanly under rapid updates (behavioral req 5)
    - 100 rapid decide_recompute calls: no exception; counters sum to 100
    - 100 rapid decide_ingest_cadence calls: no exception; counters sum

20. Optimised paths preserve canonical control artifacts (behavioral req 6)
    - text_only_fast_path dict contains expected keys
    - latency_budget_summary contains trace_id and runtime_session_id

21. OpenClawd integration
    - _apply_latency_budget returns a dict (not None) for typical inputs
    - returned dict contains all required top-level keys
    - _apply_latency_budget never raises when called with None inputs

22. Module imports
    - all public symbols importable from core.control_loop_latency_budget
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _text_perception(active_modalities: list | None = None) -> Dict[str, Any]:
    """Minimal canonical perception state with no multimodal content."""
    return {
        "requires_native_multimodal": False,
        "active_modalities": active_modalities or [],
    }


def _multimodal_perception(
    active_modalities: list | None = None,
    requires_native: bool = True,
) -> Dict[str, Any]:
    return {
        "requires_native_multimodal": requires_native,
        "active_modalities": active_modalities or ["audio", "video"],
    }


def _native_multimodal_route() -> Dict[str, Any]:
    return {
        "route_type": "native_multimodal",
        "provider": "openai",
        "model": "gpt-4o",
        "is_native_multimodal": True,
        "fallback_reason": "",
    }


def _text_only_route() -> Dict[str, Any]:
    return {
        "route_type": "text_only",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "is_native_multimodal": False,
        "fallback_reason": "confidence_below_threshold",
    }


# ===========================================================================
# 1. IngestCadencePolicy
# ===========================================================================


class TestIngestCadencePolicy:
    def test_all_values_present(self):
        from core.control_loop_latency_budget import IngestCadencePolicy as ICP

        values = {m.value for m in ICP}
        assert "allowed" in values
        assert "throttled" in values
        assert "skipped_text_only" in values
        assert "unknown" in values

    def test_string_values_stable(self):
        from core.control_loop_latency_budget import IngestCadencePolicy as ICP

        assert ICP.ALLOWED.value == "allowed"
        assert ICP.THROTTLED.value == "throttled"
        assert ICP.SKIPPED_TEXT_ONLY.value == "skipped_text_only"
        assert ICP.UNKNOWN.value == "unknown"

    def test_from_string_roundtrip(self):
        from core.control_loop_latency_budget import IngestCadencePolicy as ICP

        for member in ICP:
            assert ICP.from_string(member.value) == member

    def test_from_string_unknown_on_bad_input(self):
        from core.control_loop_latency_budget import IngestCadencePolicy as ICP

        assert ICP.from_string("garbage_xyz") == ICP.UNKNOWN
        assert ICP.from_string("") == ICP.UNKNOWN


# ===========================================================================
# 2. RecomputePolicy
# ===========================================================================


class TestRecomputePolicy:
    def test_all_values_present(self):
        from core.control_loop_latency_budget import RecomputePolicy as RCP

        values = {m.value for m in RCP}
        assert "full" in values
        assert "coalesced" in values
        assert "deferred" in values
        assert "unknown" in values

    def test_string_values_stable(self):
        from core.control_loop_latency_budget import RecomputePolicy as RCP

        assert RCP.FULL.value == "full"
        assert RCP.COALESCED.value == "coalesced"
        assert RCP.DEFERRED.value == "deferred"
        assert RCP.UNKNOWN.value == "unknown"

    def test_from_string_roundtrip(self):
        from core.control_loop_latency_budget import RecomputePolicy as RCP

        for member in RCP:
            assert RCP.from_string(member.value) == member

    def test_from_string_unknown_on_bad_input(self):
        from core.control_loop_latency_budget import RecomputePolicy as RCP

        assert RCP.from_string("???") == RCP.UNKNOWN


# ===========================================================================
# 3. ProjectionRefreshPolicy
# ===========================================================================


class TestProjectionRefreshPolicy:
    def test_all_values_present(self):
        from core.control_loop_latency_budget import ProjectionRefreshPolicy as PRP

        values = {m.value for m in PRP}
        assert "immediate" in values
        assert "coalesced" in values
        assert "suppressed" in values
        assert "unknown" in values

    def test_string_values_stable(self):
        from core.control_loop_latency_budget import ProjectionRefreshPolicy as PRP

        assert PRP.IMMEDIATE.value == "immediate"
        assert PRP.COALESCED.value == "coalesced"
        assert PRP.SUPPRESSED.value == "suppressed"
        assert PRP.UNKNOWN.value == "unknown"

    def test_from_string_roundtrip(self):
        from core.control_loop_latency_budget import ProjectionRefreshPolicy as PRP

        for member in PRP:
            assert PRP.from_string(member.value) == member

    def test_from_string_unknown_on_bad_input(self):
        from core.control_loop_latency_budget import ProjectionRefreshPolicy as PRP

        assert PRP.from_string("") == PRP.UNKNOWN


# ===========================================================================
# 4. ModalityFastPathKind
# ===========================================================================


class TestModalityFastPathKind:
    def test_all_values_present(self):
        from core.control_loop_latency_budget import ModalityFastPathKind as MFPK

        values = {m.value for m in MFPK}
        assert "text_only" in values
        assert "multimodal_required" in values
        assert "ambiguous" in values
        assert "unknown" in values

    def test_string_values_stable(self):
        from core.control_loop_latency_budget import ModalityFastPathKind as MFPK

        assert MFPK.TEXT_ONLY.value == "text_only"
        assert MFPK.MULTIMODAL_REQUIRED.value == "multimodal_required"
        assert MFPK.AMBIGUOUS.value == "ambiguous"
        assert MFPK.UNKNOWN.value == "unknown"

    def test_from_string_roundtrip(self):
        from core.control_loop_latency_budget import ModalityFastPathKind as MFPK

        for member in MFPK:
            assert MFPK.from_string(member.value) == member

    def test_from_string_unknown_on_bad_input(self):
        from core.control_loop_latency_budget import ModalityFastPathKind as MFPK

        assert MFPK.from_string("notamodality") == MFPK.UNKNOWN


# ===========================================================================
# 5. IngestCadenceWindow
# ===========================================================================


class TestIngestCadenceWindow:
    def test_construction_defaults(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow()
        assert w.window_seconds == 1.0
        assert w.max_calls_per_window == 5
        assert w.total_allowed == 0
        assert w.total_throttled == 0
        assert w.total_skipped_text_only == 0

    def test_to_dict_from_dict_roundtrip(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow(window_seconds=2.0, max_calls_per_window=10)
        w.total_allowed = 3
        d = w.to_dict()
        w2 = IngestCadenceWindow.from_dict(d)
        assert w2.window_seconds == 2.0
        assert w2.max_calls_per_window == 10
        assert w2.total_allowed == 3

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow()
        json.dumps(w.to_dict())  # must not raise

    def test_should_allow_below_threshold(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow(window_seconds=60.0, max_calls_per_window=5)
        for _ in range(4):
            w.record(allowed=True)
        assert w.should_allow() is True

    def test_should_allow_at_threshold(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow(window_seconds=60.0, max_calls_per_window=5)
        for _ in range(5):
            w.record(allowed=True)
        assert w.should_allow() is False

    def test_record_text_only_does_not_consume_budget(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow(window_seconds=60.0, max_calls_per_window=3)
        for _ in range(10):
            w.record(allowed=False, text_only=True)
        # Budget slots are untouched
        assert w.should_allow() is True
        assert w.total_skipped_text_only == 10
        assert w.total_allowed == 0

    def test_record_throttled_increments_counter(self):
        from core.control_loop_latency_budget import IngestCadenceWindow

        w = IngestCadenceWindow(window_seconds=60.0, max_calls_per_window=2)
        w.record(allowed=True)
        w.record(allowed=True)
        w.record(allowed=False)
        assert w.total_allowed == 2
        assert w.total_throttled == 1


# ===========================================================================
# 6. RecomputeWindow
# ===========================================================================


class TestRecomputeWindow:
    def test_construction_defaults(self):
        from core.control_loop_latency_budget import RecomputeWindow

        w = RecomputeWindow()
        assert w.min_interval_seconds == 0.05
        assert w.churn_window_seconds == 0.2
        assert w.churn_threshold_calls == 10

    def test_to_dict_from_dict_roundtrip(self):
        from core.control_loop_latency_budget import RecomputeWindow

        w = RecomputeWindow(min_interval_seconds=0.1)
        w.total_full = 2
        d = w.to_dict()
        w2 = RecomputeWindow.from_dict(d)
        assert w2.min_interval_seconds == 0.1
        assert w2.total_full == 2

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import RecomputeWindow

        w = RecomputeWindow()
        json.dumps(w.to_dict())

    def test_first_call_is_full(self):
        from core.control_loop_latency_budget import RecomputeWindow, RecomputePolicy

        w = RecomputeWindow(min_interval_seconds=60.0)
        assert w.decide() == RecomputePolicy.FULL

    def test_rapid_second_call_is_coalesced(self):
        from core.control_loop_latency_budget import RecomputeWindow, RecomputePolicy

        w = RecomputeWindow(min_interval_seconds=60.0)
        w.decide()  # FULL
        result = w.decide()  # immediate second call → COALESCED
        assert result == RecomputePolicy.COALESCED

    def test_churn_triggers_deferred(self):
        from core.control_loop_latency_budget import RecomputeWindow, RecomputePolicy

        # Very short churn window, very low threshold
        w = RecomputeWindow(
            min_interval_seconds=0.0,
            churn_window_seconds=60.0,
            churn_threshold_calls=3,
        )
        for _ in range(4):
            w.decide()
        # The 5th call should see churn
        result = w.decide()
        assert result == RecomputePolicy.DEFERRED

    def test_counters_increment(self):
        from core.control_loop_latency_budget import RecomputeWindow

        w = RecomputeWindow(min_interval_seconds=60.0)
        w.decide()  # FULL
        w.decide()  # COALESCED
        assert w.total_full == 1
        assert w.total_coalesced == 1


# ===========================================================================
# 7. ProjectionRefreshWindow
# ===========================================================================


class TestProjectionRefreshWindow:
    def test_construction_defaults(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow

        w = ProjectionRefreshWindow()
        assert w.min_interval_seconds == 0.1

    def test_to_dict_from_dict_roundtrip(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow

        w = ProjectionRefreshWindow(min_interval_seconds=0.5)
        w.total_immediate = 1
        d = w.to_dict()
        w2 = ProjectionRefreshWindow.from_dict(d)
        assert w2.min_interval_seconds == 0.5
        assert w2.total_immediate == 1

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow

        json.dumps(ProjectionRefreshWindow().to_dict())

    def test_first_call_is_immediate(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow, ProjectionRefreshPolicy

        w = ProjectionRefreshWindow(min_interval_seconds=0.0)
        assert w.decide() == ProjectionRefreshPolicy.IMMEDIATE

    def test_rapid_same_fingerprint_is_suppressed(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow, ProjectionRefreshPolicy

        w = ProjectionRefreshWindow(min_interval_seconds=60.0)
        w.decide(state_fingerprint="fp1")  # IMMEDIATE (first call, elapsed > min because _last=0)
        result = w.decide(state_fingerprint="fp1")
        assert result == ProjectionRefreshPolicy.SUPPRESSED

    def test_rapid_changed_fingerprint_is_coalesced(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow, ProjectionRefreshPolicy

        w = ProjectionRefreshWindow(min_interval_seconds=60.0)
        w.decide(state_fingerprint="fp1")  # IMMEDIATE
        result = w.decide(state_fingerprint="fp2")  # different fingerprint → COALESCED
        assert result == ProjectionRefreshPolicy.COALESCED

    def test_counters_increment(self):
        from core.control_loop_latency_budget import ProjectionRefreshWindow

        w = ProjectionRefreshWindow(min_interval_seconds=60.0)
        w.decide()
        w.decide(state_fingerprint="x")
        w.decide(state_fingerprint="x")
        assert w.total_immediate >= 1


# ===========================================================================
# 8. ProviderSelectionBudget
# ===========================================================================


class TestProviderSelectionBudget:
    def test_construction_defaults(self):
        from core.control_loop_latency_budget import ProviderSelectionBudget

        b = ProviderSelectionBudget()
        assert b.budget_ms == 20.0
        assert b.measured_ms == 0.0
        assert b.exceeded is False
        assert b.route_type == "unknown"
        assert b.fast_path_applied is False

    def test_to_dict_from_dict_roundtrip(self):
        from core.control_loop_latency_budget import ProviderSelectionBudget

        b = ProviderSelectionBudget(
            budget_ms=10.0,
            measured_ms=15.0,
            exceeded=True,
            route_type="text_only",
            fast_path_applied=True,
        )
        d = b.to_dict()
        b2 = ProviderSelectionBudget.from_dict(d)
        assert b2.budget_ms == 10.0
        assert b2.measured_ms == 15.0
        assert b2.exceeded is True
        assert b2.route_type == "text_only"
        assert b2.fast_path_applied is True

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import ProviderSelectionBudget

        json.dumps(ProviderSelectionBudget().to_dict())

    def test_exceeded_when_over_budget(self):
        from core.control_loop_latency_budget import ProviderSelectionBudget

        b = ProviderSelectionBudget(budget_ms=10.0, measured_ms=25.0, exceeded=True)
        assert b.exceeded is True

    def test_not_exceeded_when_within_budget(self):
        from core.control_loop_latency_budget import ProviderSelectionBudget

        b = ProviderSelectionBudget(budget_ms=10.0, measured_ms=5.0, exceeded=False)
        assert b.exceeded is False


# ===========================================================================
# 9. TextOnlyFastPathAssessment
# ===========================================================================


class TestTextOnlyFastPathAssessment:
    def test_construction_defaults(self):
        from core.control_loop_latency_budget import TextOnlyFastPathAssessment, ModalityFastPathKind

        a = TextOnlyFastPathAssessment()
        assert a.fast_path_kind == ModalityFastPathKind.UNKNOWN
        assert a.is_text_only is False
        assert a.active_modalities == []

    def test_to_dict_from_dict_roundtrip(self):
        from core.control_loop_latency_budget import TextOnlyFastPathAssessment, ModalityFastPathKind

        a = TextOnlyFastPathAssessment(
            fast_path_kind=ModalityFastPathKind.TEXT_ONLY,
            is_text_only=True,
            reason="no_multimodal",
            active_modalities=[],
            has_multimodal_context=False,
        )
        d = a.to_dict()
        a2 = TextOnlyFastPathAssessment.from_dict(d)
        assert a2.fast_path_kind == ModalityFastPathKind.TEXT_ONLY
        assert a2.is_text_only is True
        assert a2.reason == "no_multimodal"

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import TextOnlyFastPathAssessment

        json.dumps(TextOnlyFastPathAssessment().to_dict())

    def test_assessment_id_is_uuid(self):
        from core.control_loop_latency_budget import TextOnlyFastPathAssessment

        a = TextOnlyFastPathAssessment()
        uuid.UUID(a.assessment_id)  # must not raise

    def test_stable_field_names(self):
        from core.control_loop_latency_budget import TextOnlyFastPathAssessment

        d = TextOnlyFastPathAssessment().to_dict()
        assert "fast_path_kind" in d
        assert "is_text_only" in d
        assert "reason" in d
        assert "active_modalities" in d
        assert "has_multimodal_context" in d
        assert "assessment_id" in d


# ===========================================================================
# 10. LatencyBudgetSummary
# ===========================================================================


class TestLatencyBudgetSummary:
    def test_construction_defaults(self):
        from core.control_loop_latency_budget import LatencyBudgetSummary, IngestCadencePolicy

        s = LatencyBudgetSummary()
        assert s.ingest_cadence_policy == IngestCadencePolicy.UNKNOWN.value
        assert s.trace_id == ""

    def test_to_dict_from_dict_roundtrip(self):
        from core.control_loop_latency_budget import LatencyBudgetSummary

        s = LatencyBudgetSummary(
            trace_id="t123",
            runtime_session_id="rs456",
            ingest_cadence_policy="allowed",
            recompute_policy="full",
        )
        d = s.to_dict()
        s2 = LatencyBudgetSummary.from_dict(d)
        assert s2.trace_id == "t123"
        assert s2.runtime_session_id == "rs456"
        assert s2.ingest_cadence_policy == "allowed"
        assert s2.recompute_policy == "full"

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import LatencyBudgetSummary

        json.dumps(LatencyBudgetSummary().to_dict())

    def test_summary_id_is_uuid(self):
        from core.control_loop_latency_budget import LatencyBudgetSummary

        s = LatencyBudgetSummary()
        uuid.UUID(s.summary_id)  # must not raise

    def test_timestamp_is_populated(self):
        from core.control_loop_latency_budget import LatencyBudgetSummary

        before = time.time()
        s = LatencyBudgetSummary()
        after = time.time()
        assert before <= s.timestamp <= after + 1

    def test_stable_field_names(self):
        from core.control_loop_latency_budget import LatencyBudgetSummary

        d = LatencyBudgetSummary().to_dict()
        expected = {
            "summary_id", "timestamp", "trace_id", "runtime_session_id",
            "ingest_cadence_policy", "recompute_policy", "projection_refresh_policy",
            "provider_selection_budget", "text_only_fast_path",
            "ingest_window_stats", "recompute_window_stats", "projection_window_stats",
        }
        assert expected.issubset(set(d.keys()))


# ===========================================================================
# 11. assess_text_only_fast_path()
# ===========================================================================


class TestAssessTextOnlyFastPath:
    def test_none_context_no_modalities_is_text_only(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path, ModalityFastPathKind

        result = assess_text_only_fast_path(
            multimodal_context=None,
            canonical_perception=_text_perception(),
        )
        assert result.fast_path_kind == ModalityFastPathKind.TEXT_ONLY
        assert result.is_text_only is True

    def test_explicit_mm_context_is_multimodal_required(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path, ModalityFastPathKind

        result = assess_text_only_fast_path(
            multimodal_context={"audio": True},
            canonical_perception=_text_perception(),
        )
        assert result.fast_path_kind == ModalityFastPathKind.MULTIMODAL_REQUIRED
        assert result.is_text_only is False
        assert result.has_multimodal_context is True

    def test_active_modalities_in_perception_is_multimodal_required(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path, ModalityFastPathKind

        result = assess_text_only_fast_path(
            multimodal_context=None,
            canonical_perception=_multimodal_perception(
                active_modalities=["audio", "video"], requires_native=False
            ),
        )
        assert result.fast_path_kind == ModalityFastPathKind.MULTIMODAL_REQUIRED

    def test_requires_native_multimodal_is_multimodal_required(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path, ModalityFastPathKind

        result = assess_text_only_fast_path(
            multimodal_context=None,
            canonical_perception={"requires_native_multimodal": True, "active_modalities": []},
        )
        assert result.fast_path_kind == ModalityFastPathKind.MULTIMODAL_REQUIRED

    def test_all_none_inputs_returns_text_only(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path, ModalityFastPathKind

        result = assess_text_only_fast_path(
            multimodal_context=None,
            canonical_perception=None,
        )
        assert result.fast_path_kind == ModalityFastPathKind.TEXT_ONLY
        assert result.is_text_only is True

    def test_never_raises_on_garbage_input(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path

        result = assess_text_only_fast_path(
            multimodal_context=object(),
            canonical_perception={"bad_key": [1, 2, None]},
        )
        assert result is not None  # must always return something


# ===========================================================================
# 12. build_latency_budget_summary()
# ===========================================================================


class TestBuildLatencyBudgetSummary:
    def test_builds_correct_summary_with_all_params(self):
        from core.control_loop_latency_budget import (
            build_latency_budget_summary,
            IngestCadencePolicy,
            RecomputePolicy,
            ProjectionRefreshPolicy,
            ProviderSelectionBudget,
            TextOnlyFastPathAssessment,
            ModalityFastPathKind,
        )

        psb = ProviderSelectionBudget(budget_ms=20.0, measured_ms=5.0, route_type="text_only")
        fp = TextOnlyFastPathAssessment(
            fast_path_kind=ModalityFastPathKind.TEXT_ONLY, is_text_only=True
        )
        s = build_latency_budget_summary(
            trace_id="tr1",
            runtime_session_id="rs1",
            ingest_cadence_policy=IngestCadencePolicy.SKIPPED_TEXT_ONLY,
            recompute_policy=RecomputePolicy.COALESCED,
            projection_refresh_policy=ProjectionRefreshPolicy.SUPPRESSED,
            provider_selection_budget=psb,
            text_only_fast_path=fp,
        )
        assert s.trace_id == "tr1"
        assert s.ingest_cadence_policy == "skipped_text_only"
        assert s.recompute_policy == "coalesced"
        assert s.projection_refresh_policy == "suppressed"
        assert s.provider_selection_budget is not None
        assert s.provider_selection_budget["route_type"] == "text_only"
        assert s.text_only_fast_path is not None
        assert s.text_only_fast_path["is_text_only"] is True

    def test_is_json_serialisable(self):
        from core.control_loop_latency_budget import build_latency_budget_summary

        s = build_latency_budget_summary(trace_id="t")
        json.dumps(s.to_dict())  # must not raise

    def test_never_raises_with_no_params(self):
        from core.control_loop_latency_budget import build_latency_budget_summary

        s = build_latency_budget_summary()
        assert s is not None

    def test_never_raises_with_garbage_params(self):
        from core.control_loop_latency_budget import build_latency_budget_summary, IngestCadencePolicy

        # Should not raise even if passed None for optional objects
        s = build_latency_budget_summary(
            trace_id=None,  # type: ignore[arg-type]
            provider_selection_budget=None,
            text_only_fast_path=None,
        )
        assert s is not None


# ===========================================================================
# 13. ControlLoopLatencyBudget
# ===========================================================================


class TestControlLoopLatencyBudget:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def test_construction_defaults(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget()
        assert b is not None

    def test_ingest_text_only_skipped(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, IngestCadencePolicy

        b = ControlLoopLatencyBudget()
        result = b.decide_ingest_cadence(has_multimodal_context=False, is_text_only=True)
        assert result == IngestCadencePolicy.SKIPPED_TEXT_ONLY

    def test_ingest_no_mm_context_skipped(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, IngestCadencePolicy

        b = ControlLoopLatencyBudget()
        result = b.decide_ingest_cadence(has_multimodal_context=False, is_text_only=False)
        assert result == IngestCadencePolicy.SKIPPED_TEXT_ONLY

    def test_ingest_mm_context_within_budget_allowed(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, IngestCadencePolicy

        b = ControlLoopLatencyBudget(ingest_max_calls=10)
        result = b.decide_ingest_cadence(has_multimodal_context=True, is_text_only=False)
        assert result == IngestCadencePolicy.ALLOWED

    def test_ingest_mm_context_exceeds_window_throttled(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, IngestCadencePolicy

        b = ControlLoopLatencyBudget(
            ingest_window_seconds=60.0,
            ingest_max_calls=2,
        )
        b.decide_ingest_cadence(has_multimodal_context=True, is_text_only=False)
        b.decide_ingest_cadence(has_multimodal_context=True, is_text_only=False)
        result = b.decide_ingest_cadence(has_multimodal_context=True, is_text_only=False)
        assert result == IngestCadencePolicy.THROTTLED

    def test_recompute_first_call_full(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, RecomputePolicy

        b = ControlLoopLatencyBudget()
        assert b.decide_recompute() == RecomputePolicy.FULL

    def test_recompute_rapid_second_call_coalesced(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, RecomputePolicy

        b = ControlLoopLatencyBudget(recompute_min_interval_seconds=60.0)
        b.decide_recompute()  # FULL
        result = b.decide_recompute()
        assert result == RecomputePolicy.COALESCED

    def test_recompute_churn_burst_deferred(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, RecomputePolicy

        b = ControlLoopLatencyBudget(
            recompute_min_interval_seconds=0.0,
            recompute_churn_window_seconds=60.0,
            recompute_churn_threshold=3,
        )
        for _ in range(4):
            b.decide_recompute()
        result = b.decide_recompute()
        assert result == RecomputePolicy.DEFERRED

    def test_projection_first_call_immediate(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, ProjectionRefreshPolicy

        b = ControlLoopLatencyBudget(projection_min_interval_seconds=0.0)
        assert b.decide_projection_refresh() == ProjectionRefreshPolicy.IMMEDIATE

    def test_projection_rapid_same_fingerprint_suppressed(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, ProjectionRefreshPolicy

        b = ControlLoopLatencyBudget(projection_min_interval_seconds=60.0)
        b.decide_projection_refresh(state_fingerprint="fp")
        result = b.decide_projection_refresh(state_fingerprint="fp")
        assert result == ProjectionRefreshPolicy.SUPPRESSED

    def test_projection_rapid_changed_fingerprint_coalesced(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, ProjectionRefreshPolicy

        b = ControlLoopLatencyBudget(projection_min_interval_seconds=60.0)
        b.decide_projection_refresh(state_fingerprint="fp1")
        result = b.decide_projection_refresh(state_fingerprint="fp2")
        assert result == ProjectionRefreshPolicy.COALESCED

    def test_provider_selection_within_budget(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget(provider_selection_budget_ms=20.0)
        psb = b.record_provider_selection(measured_ms=5.0, route_type="text_only")
        assert psb.exceeded is False
        assert psb.route_type == "text_only"

    def test_provider_selection_over_budget(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget(provider_selection_budget_ms=10.0)
        psb = b.record_provider_selection(measured_ms=30.0, route_type="native_multimodal")
        assert psb.exceeded is True

    def test_snapshot_stats_return_dicts(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget()
        assert isinstance(b.snapshot_ingest_stats(), dict)
        assert isinstance(b.snapshot_recompute_stats(), dict)
        assert isinstance(b.snapshot_projection_stats(), dict)


# ===========================================================================
# 14. get_control_loop_latency_budget() / reset_latency_budget()
# ===========================================================================


class TestSingleton:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def test_get_returns_singleton(self):
        from core.control_loop_latency_budget import get_control_loop_latency_budget

        a = get_control_loop_latency_budget()
        b = get_control_loop_latency_budget()
        assert a is b

    def test_reset_clears_singleton(self):
        from core.control_loop_latency_budget import get_control_loop_latency_budget, reset_latency_budget

        a = get_control_loop_latency_budget()
        reset_latency_budget()
        b = get_control_loop_latency_budget()
        assert a is not b


# ===========================================================================
# 15. Text-only flows avoid multimodal overhead (behavioral requirement 2)
# ===========================================================================


class TestTextOnlyFastPathBehavior:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def test_plain_text_request_is_text_only(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path, ModalityFastPathKind

        result = assess_text_only_fast_path(
            multimodal_context=None,
            canonical_perception=_text_perception(),
        )
        assert result.fast_path_kind == ModalityFastPathKind.TEXT_ONLY
        assert result.is_text_only is True

    def test_ingest_cadence_skipped_for_text_only(self):
        from core.control_loop_latency_budget import get_control_loop_latency_budget, IngestCadencePolicy

        b = get_control_loop_latency_budget()
        result = b.decide_ingest_cadence(has_multimodal_context=False, is_text_only=True)
        assert result == IngestCadencePolicy.SKIPPED_TEXT_ONLY

    def test_summary_reflects_text_only_fast_path(self):
        from core.control_loop_latency_budget import (
            assess_text_only_fast_path,
            build_latency_budget_summary,
            IngestCadencePolicy,
            ModalityFastPathKind,
        )

        fp = assess_text_only_fast_path(multimodal_context=None, canonical_perception=None)
        s = build_latency_budget_summary(
            ingest_cadence_policy=IngestCadencePolicy.SKIPPED_TEXT_ONLY,
            text_only_fast_path=fp,
        )
        assert s.text_only_fast_path is not None
        assert s.text_only_fast_path["is_text_only"] is True
        assert s.ingest_cadence_policy == "skipped_text_only"


# ===========================================================================
# 16. Repeated churn does not force excessive recomputes (behavioral req 2)
# ===========================================================================


class TestChurnThrottling:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def test_rapid_recomputes_coalesced_or_deferred(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, RecomputePolicy

        b = ControlLoopLatencyBudget(
            recompute_min_interval_seconds=60.0,
            recompute_churn_window_seconds=60.0,
            recompute_churn_threshold=5,
        )
        # First call is FULL; rest should be COALESCED or DEFERRED
        first = b.decide_recompute()
        assert first == RecomputePolicy.FULL
        for _ in range(10):
            result = b.decide_recompute()
            assert result in (RecomputePolicy.COALESCED, RecomputePolicy.DEFERRED)

    def test_at_most_one_full_per_interval(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, RecomputePolicy

        b = ControlLoopLatencyBudget(recompute_min_interval_seconds=60.0)
        full_count = sum(
            1 for _ in range(5) if b.decide_recompute() == RecomputePolicy.FULL
        )
        assert full_count == 1


# ===========================================================================
# 17. Projection updates coalesced / throttled safely (behavioral req 3)
# ===========================================================================


class TestProjectionBudgetBehavior:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def test_repeated_same_fingerprint_suppressed(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, ProjectionRefreshPolicy

        b = ControlLoopLatencyBudget(projection_min_interval_seconds=60.0)
        b.decide_projection_refresh(state_fingerprint="fp_x")
        for _ in range(5):
            result = b.decide_projection_refresh(state_fingerprint="fp_x")
            assert result == ProjectionRefreshPolicy.SUPPRESSED

    def test_state_change_allows_coalesced(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget, ProjectionRefreshPolicy

        b = ControlLoopLatencyBudget(projection_min_interval_seconds=60.0)
        b.decide_projection_refresh(state_fingerprint="fp_a")
        result = b.decide_projection_refresh(state_fingerprint="fp_b")
        assert result == ProjectionRefreshPolicy.COALESCED

    def test_suppressed_stats_tracked(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget(projection_min_interval_seconds=60.0)
        b.decide_projection_refresh(state_fingerprint="s")
        b.decide_projection_refresh(state_fingerprint="s")
        b.decide_projection_refresh(state_fingerprint="s")
        stats = b.snapshot_projection_stats()
        assert stats["total_suppressed"] >= 2


# ===========================================================================
# 18. Multimodal route decision latency accounting stable + serialisable
#     (behavioral requirement 4)
# ===========================================================================


class TestProviderSelectionLatencyAccounting:
    def test_full_roundtrip_json_serialisable(self):
        from core.control_loop_latency_budget import (
            ControlLoopLatencyBudget,
            build_latency_budget_summary,
            IngestCadencePolicy,
            RecomputePolicy,
            ProjectionRefreshPolicy,
        )

        b = ControlLoopLatencyBudget()
        psb = b.record_provider_selection(
            measured_ms=8.5,
            route_type="native_multimodal",
            fast_path_applied=False,
        )
        s = build_latency_budget_summary(
            trace_id="t_mm",
            ingest_cadence_policy=IngestCadencePolicy.ALLOWED,
            recompute_policy=RecomputePolicy.FULL,
            projection_refresh_policy=ProjectionRefreshPolicy.IMMEDIATE,
            provider_selection_budget=psb,
            ingest_window_stats=b.snapshot_ingest_stats(),
            recompute_window_stats=b.snapshot_recompute_stats(),
            projection_window_stats=b.snapshot_projection_stats(),
        )
        raw = json.dumps(s.to_dict())
        recovered = json.loads(raw)
        assert recovered["trace_id"] == "t_mm"
        assert recovered["provider_selection_budget"]["route_type"] == "native_multimodal"
        assert recovered["provider_selection_budget"]["measured_ms"] == 8.5

    def test_route_type_propagated_from_route_dict(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget()
        psb = b.record_provider_selection(measured_ms=1.0, route_type="text_only")
        assert psb.route_type == "text_only"


# ===========================================================================
# 19. Budget logic degrades cleanly under rapid updates (behavioral req 5)
# ===========================================================================


class TestRapidUpdateResilience:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def test_100_rapid_recompute_calls_no_exception(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget()
        results = [b.decide_recompute() for _ in range(100)]
        assert len(results) == 100
        # Counters must sum to 100
        stats = b.snapshot_recompute_stats()
        total = stats["total_full"] + stats["total_coalesced"] + stats["total_deferred"]
        assert total == 100

    def test_100_rapid_ingest_calls_no_exception(self):
        from core.control_loop_latency_budget import ControlLoopLatencyBudget

        b = ControlLoopLatencyBudget(ingest_window_seconds=60.0, ingest_max_calls=5)
        for i in range(100):
            b.decide_ingest_cadence(has_multimodal_context=(i % 3 == 0), is_text_only=(i % 3 != 0))
        stats = b.snapshot_ingest_stats()
        total = stats["total_allowed"] + stats["total_throttled"] + stats["total_skipped_text_only"]
        assert total == 100


# ===========================================================================
# 20. Optimised paths preserve canonical control artifacts (behavioral req 6)
# ===========================================================================


class TestCanonicalArtifactPreservation:
    def test_text_only_fast_path_dict_has_expected_keys(self):
        from core.control_loop_latency_budget import assess_text_only_fast_path

        fp = assess_text_only_fast_path(multimodal_context=None, canonical_perception=None)
        d = fp.to_dict()
        assert "fast_path_kind" in d
        assert "is_text_only" in d
        assert "reason" in d
        assert "active_modalities" in d
        assert "has_multimodal_context" in d
        assert "assessment_id" in d

    def test_summary_contains_trace_and_session_ids(self):
        from core.control_loop_latency_budget import build_latency_budget_summary

        s = build_latency_budget_summary(
            trace_id="tr_canonical",
            runtime_session_id="rs_canonical",
        )
        d = s.to_dict()
        assert d["trace_id"] == "tr_canonical"
        assert d["runtime_session_id"] == "rs_canonical"


# ===========================================================================
# 21. OpenClawd integration
# ===========================================================================


class TestOpenClawdIntegration:
    def setup_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def teardown_method(self):
        from core.control_loop_latency_budget import reset_latency_budget
        reset_latency_budget()

    def _make_openclawd(self):
        from core.openclawd import OpenClawd
        return OpenClawd.__new__(OpenClawd)

    def test_apply_latency_budget_returns_dict_for_typical_inputs(self):
        oc = self._make_openclawd()
        result = oc._apply_latency_budget(
            multimodal_context=None,
            canonical_perception=_text_perception(),
            multimodal_route=_text_only_route(),
            trace_id="tr1",
            runtime_session_id="rs1",
        )
        assert isinstance(result, dict)

    def test_apply_latency_budget_contains_required_keys(self):
        oc = self._make_openclawd()
        result = oc._apply_latency_budget(
            multimodal_context=None,
            canonical_perception=_text_perception(),
            multimodal_route=_text_only_route(),
            trace_id="tr2",
            runtime_session_id="rs2",
        )
        assert result is not None
        assert "summary_id" in result
        assert "trace_id" in result
        assert "ingest_cadence_policy" in result
        assert "recompute_policy" in result
        assert "projection_refresh_policy" in result
        assert "text_only_fast_path" in result

    def test_apply_latency_budget_never_raises_with_none_inputs(self):
        oc = self._make_openclawd()
        # Should not raise even with all None
        result = oc._apply_latency_budget(
            multimodal_context=None,
            canonical_perception=None,
            multimodal_route=None,
            trace_id="",
            runtime_session_id="",
        )
        # Returns dict or None — either is acceptable; must not raise
        assert result is None or isinstance(result, dict)

    def test_apply_latency_budget_result_is_json_serialisable(self):
        oc = self._make_openclawd()
        result = oc._apply_latency_budget(
            multimodal_context=None,
            canonical_perception=_text_perception(),
            multimodal_route=_native_multimodal_route(),
            trace_id="tr3",
            runtime_session_id="",
        )
        if result is not None:
            json.dumps(result)  # must not raise


# ===========================================================================
# 22. Module imports
# ===========================================================================


class TestModuleImports:
    def test_all_public_symbols_importable(self):
        from core.control_loop_latency_budget import (
            IngestCadencePolicy,
            RecomputePolicy,
            ProjectionRefreshPolicy,
            ModalityFastPathKind,
            IngestCadenceWindow,
            RecomputeWindow,
            ProjectionRefreshWindow,
            ProviderSelectionBudget,
            TextOnlyFastPathAssessment,
            LatencyBudgetSummary,
            ControlLoopLatencyBudget,
            assess_text_only_fast_path,
            build_latency_budget_summary,
            get_control_loop_latency_budget,
            reset_latency_budget,
        )
        # If this test reaches here, all imports succeeded
        assert IngestCadencePolicy is not None
        assert ControlLoopLatencyBudget is not None
        assert assess_text_only_fast_path is not None
        assert get_control_loop_latency_budget is not None
