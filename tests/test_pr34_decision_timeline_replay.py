#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr34_decision_timeline_replay.py
============================================
Tests for PR-34: Add decision timeline replay and explainability traces for
control-loop outcomes.

Coverage
--------
1.  DecisionKind enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

2.  DecisionTraceRecord
    - construction with defaults (auto-generated record_id, current timestamp)
    - construction with all fields
    - to_dict is JSON-serialisable (json.dumps succeeds)
    - to_dict / from_dict round-trip preserves all fields
    - stable field names

3.  ControlTimelineEvent
    - construction with defaults
    - construction with explicit sequence and record
    - to_dict is JSON-serialisable
    - to_dict / from_dict round-trip preserves all fields
    - nested record reconstructed from from_dict

4.  ExplainabilitySnapshot
    - construction with defaults (empty events)
    - to_dict is JSON-serialisable
    - to_dict / from_dict round-trip preserves all fields
    - kind_counts correctly tallied

5.  DecisionTimeline
    - initial state is empty (event_count == 0)
    - append returns ControlTimelineEvent with correct sequence
    - sequence is monotonically increasing
    - clear resets event_count and sequence
    - snapshot returns ordered events (ascending sequence)
    - snapshot kind_counts is correct
    - snapshot is independent of subsequent appends (copy semantics)

6.  Singletons
    - get_decision_timeline returns same object on repeated calls
    - reset_decision_timeline clears singleton (new object returned)

7.  record_decision_event (public builder)
    - route_selection kind produces ControlTimelineEvent
    - fallback_transition kind produces ControlTimelineEvent
    - operator_override kind produces ControlTimelineEvent
    - trust_safety_gating kind produces ControlTimelineEvent
    - execution_locality_change kind produces ControlTimelineEvent
    - event is appended to global timeline
    - returns None on unexpected error (non-fatal)

8.  record_route_selection_event
    - produces route_selection event from routing dict
    - also emits fallback_transition event when fallback_reason is set
      and route is not native_multimodal
    - no fallback event when route is native_multimodal (no fallback)
    - never raises; returns None on failure

9.  record_operator_override_event
    - returns None when no active override (empty snapshot)
    - returns event when active overrides present
    - override_domains extracted from applied_records
    - never raises

10. record_trust_safety_gating_event
    - returns None when no gating reason and low risk tier
    - returns event when gating_reason present
    - returns event when elevated risk_tier present
    - never raises

11. record_source_switch_event
    - returns None when no switch events in snapshot
    - returns event when primary switch events present
    - source_modality, previous/new source IDs extracted correctly
    - never raises

12. build_explainability_snapshot
    - returns ExplainabilitySnapshot from global timeline
    - total_events matches event list length
    - kind_counts sums to total_events
    - never raises; returns empty snapshot on error

13. Route/model selection emits structured trace (acceptance)
    - after record_route_selection_event the timeline has a route_selection event
    - event.record.route_kind matches route dict's route_type
    - event.record.rationale is non-empty and matches route_reason

14. Fallback transitions appear in replay timeline (acceptance)
    - after a fallback route event the timeline contains a fallback_transition record
    - fallback_transition record.fallback_reason is non-empty
    - previous_route_kind is present

15. Source switch / recovery correlated in trace (acceptance)
    - record_source_switch_event inserts a source_switch record
    - source_switch record has source_modality, previous/new source IDs

16. Operator override influence in explanation artifacts (acceptance)
    - record_operator_override_event inserts an operator_override record
    - override_domains and override_reason are preserved

17. Serialisation and determinism (acceptance)
    - to_dict → json.dumps → json.loads → from_dict round-trip is stable
    - from_dict(to_dict(snap)).events[n].record fields match original
    - two snapshots from the same timeline have same events (deterministic)

18. Explanations derive from canonical decisions (acceptance)
    - ExplainabilitySnapshot.events are always ControlTimelineEvent objects
    - each event.record.kind is a known DecisionKind value
    - rationale fields are non-empty strings derived from canonical inputs

19. DesktopPresenceRuntime.decision_timeline_replay
    - returns snapshot_id, events, total_events, kind_counts keys
    - prefers embedded result["metadata"]["decision_timeline_snapshot"]
    - falls back to live timeline snapshot when no result provided
    - never raises; returns error key on unexpected failure
"""
from __future__ import annotations

import json
import sys
import types
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure repository root is importable
# ---------------------------------------------------------------------------
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.decision_timeline import (
    DecisionKind,
    DecisionTraceRecord,
    ControlTimelineEvent,
    ExplainabilitySnapshot,
    DecisionTimeline,
    get_decision_timeline,
    reset_decision_timeline,
    record_decision_event,
    record_route_selection_event,
    record_operator_override_event,
    record_trust_safety_gating_event,
    record_source_switch_event,
    build_explainability_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_timeline() -> DecisionTimeline:
    """Reset and return a fresh global timeline singleton."""
    reset_decision_timeline()
    return get_decision_timeline()


# ---------------------------------------------------------------------------
# 1. DecisionKind enum
# ---------------------------------------------------------------------------


class TestDecisionKind:
    def test_all_expected_values_present(self):
        expected = {
            "route_selection",
            "fallback_transition",
            "source_switch",
            "operator_override",
            "trust_safety_gating",
            "execution_locality_change",
            "unknown",
        }
        actual = {member.value for member in DecisionKind}
        assert expected == actual

    def test_string_values_are_stable(self):
        assert DecisionKind.ROUTE_SELECTION.value == "route_selection"
        assert DecisionKind.FALLBACK_TRANSITION.value == "fallback_transition"
        assert DecisionKind.SOURCE_SWITCH.value == "source_switch"
        assert DecisionKind.OPERATOR_OVERRIDE.value == "operator_override"
        assert DecisionKind.TRUST_SAFETY_GATING.value == "trust_safety_gating"
        assert DecisionKind.EXECUTION_LOCALITY_CHANGE.value == "execution_locality_change"
        assert DecisionKind.UNKNOWN.value == "unknown"

    def test_from_string_round_trips_all_known(self):
        for member in DecisionKind:
            assert DecisionKind.from_string(member.value) == member

    def test_from_string_returns_unknown_for_bad_input(self):
        assert DecisionKind.from_string("totally_invalid") == DecisionKind.UNKNOWN
        assert DecisionKind.from_string("") == DecisionKind.UNKNOWN


# ---------------------------------------------------------------------------
# 2. DecisionTraceRecord
# ---------------------------------------------------------------------------


class TestDecisionTraceRecord:
    def test_construction_with_defaults(self):
        r = DecisionTraceRecord()
        assert isinstance(r.record_id, str) and r.record_id
        assert r.kind == DecisionKind.UNKNOWN.value
        assert r.decision_summary == ""
        assert r.rationale == ""
        assert r.override_domains == []
        assert r.gated_domains == []
        assert r.extra == {}
        assert isinstance(r.timestamp, float)

    def test_construction_with_all_fields(self):
        r = DecisionTraceRecord(
            record_id="rec-1",
            kind=DecisionKind.ROUTE_SELECTION.value,
            decision_summary="native_multimodal selected",
            rationale="tier-1 routing",
            route_kind="native_multimodal",
            selected_model="gpt-4o",
            previous_route_kind="text_only",
            fallback_reason="provider unavailable",
            source_modality="audio",
            previous_source_id="src-a",
            new_source_id="src-b",
            source_switch_reason="re-election",
            override_domains=["multimodal_mode"],
            override_reason="maintenance",
            gating_reason="high risk tier",
            gated_domains=["remote_execution"],
            previous_locality="local",
            new_locality="remote",
            causal_policy="cross_device_expansion_policy",
            trace_id="trace-42",
            runtime_session_id="sess-99",
            extra={"foo": "bar"},
        )
        assert r.record_id == "rec-1"
        assert r.kind == "route_selection"
        assert r.route_kind == "native_multimodal"
        assert r.selected_model == "gpt-4o"
        assert r.override_domains == ["multimodal_mode"]
        assert r.gated_domains == ["remote_execution"]
        assert r.trace_id == "trace-42"

    def test_to_dict_is_json_serialisable(self):
        r = DecisionTraceRecord(
            kind=DecisionKind.FALLBACK_TRANSITION.value,
            decision_summary="fallback to text_only",
            rationale="provider unavailable",
            route_kind="text_only",
            previous_route_kind="native_multimodal",
            fallback_reason="no native MM provider",
        )
        d = r.to_dict()
        assert json.dumps(d)  # Must not raise

    def test_to_dict_from_dict_round_trip(self):
        r = DecisionTraceRecord(
            kind=DecisionKind.OPERATOR_OVERRIDE.value,
            decision_summary="operator forced text-only",
            rationale="maintenance window",
            override_domains=["multimodal_mode"],
            override_reason="maintenance_window",
            trace_id="t-1",
            runtime_session_id="s-1",
            extra={"key": "value"},
        )
        d = r.to_dict()
        r2 = DecisionTraceRecord.from_dict(d)
        assert r2.record_id == r.record_id
        assert r2.kind == r.kind
        assert r2.decision_summary == r.decision_summary
        assert r2.rationale == r.rationale
        assert r2.override_domains == r.override_domains
        assert r2.override_reason == r.override_reason
        assert r2.trace_id == r.trace_id
        assert r2.runtime_session_id == r.runtime_session_id
        assert r2.extra == r.extra

    def test_stable_field_names(self):
        d = DecisionTraceRecord().to_dict()
        for key in (
            "record_id", "kind", "decision_summary", "rationale",
            "route_kind", "selected_model", "previous_route_kind", "fallback_reason",
            "source_modality", "previous_source_id", "new_source_id", "source_switch_reason",
            "override_domains", "override_reason", "gating_reason", "gated_domains",
            "previous_locality", "new_locality", "causal_policy",
            "trace_id", "runtime_session_id", "timestamp", "extra",
        ):
            assert key in d, f"Missing field: {key}"

    def test_from_dict_unknown_keys_ignored(self):
        d = DecisionTraceRecord().to_dict()
        d["__future_extension__"] = "value"
        r = DecisionTraceRecord.from_dict(d)
        assert r.decision_summary == ""
        assert not hasattr(r, "__future_extension__")


# ---------------------------------------------------------------------------
# 3. ControlTimelineEvent
# ---------------------------------------------------------------------------


class TestControlTimelineEvent:
    def test_construction_with_defaults(self):
        ev = ControlTimelineEvent()
        assert isinstance(ev.event_id, str) and ev.event_id
        assert ev.sequence == 0
        assert isinstance(ev.record, DecisionTraceRecord)
        assert isinstance(ev.emitted_at, float)

    def test_construction_with_explicit_fields(self):
        rec = DecisionTraceRecord(kind=DecisionKind.SOURCE_SWITCH.value, decision_summary="switch")
        ev = ControlTimelineEvent(event_id="ev-1", sequence=5, record=rec, emitted_at=1_000.0)
        assert ev.event_id == "ev-1"
        assert ev.sequence == 5
        assert ev.record is rec
        assert ev.emitted_at == 1_000.0

    def test_to_dict_is_json_serialisable(self):
        ev = ControlTimelineEvent(
            sequence=1,
            record=DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value),
        )
        assert json.dumps(ev.to_dict())

    def test_to_dict_from_dict_round_trip(self):
        rec = DecisionTraceRecord(
            kind=DecisionKind.FALLBACK_TRANSITION.value,
            decision_summary="fallback",
            rationale="no provider",
            route_kind="text_only",
            previous_route_kind="native_multimodal",
        )
        ev = ControlTimelineEvent(sequence=3, record=rec)
        d = ev.to_dict()
        ev2 = ControlTimelineEvent.from_dict(d)
        assert ev2.event_id == ev.event_id
        assert ev2.sequence == ev.sequence
        assert ev2.record.kind == ev.record.kind
        assert ev2.record.route_kind == ev.record.route_kind
        assert ev2.record.previous_route_kind == ev.record.previous_route_kind

    def test_nested_record_reconstructed(self):
        ev = ControlTimelineEvent(
            sequence=2,
            record=DecisionTraceRecord(kind=DecisionKind.OPERATOR_OVERRIDE.value, override_reason="test"),
        )
        ev2 = ControlTimelineEvent.from_dict(ev.to_dict())
        assert ev2.record.kind == DecisionKind.OPERATOR_OVERRIDE.value
        assert ev2.record.override_reason == "test"


# ---------------------------------------------------------------------------
# 4. ExplainabilitySnapshot
# ---------------------------------------------------------------------------


class TestExplainabilitySnapshot:
    def test_construction_with_defaults(self):
        snap = ExplainabilitySnapshot()
        assert isinstance(snap.snapshot_id, str) and snap.snapshot_id
        assert snap.events == []
        assert snap.total_events == 0
        assert snap.kind_counts == {}

    def test_to_dict_is_json_serialisable(self):
        snap = ExplainabilitySnapshot(
            events=[
                ControlTimelineEvent(
                    sequence=1,
                    record=DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value),
                )
            ],
            total_events=1,
            kind_counts={"route_selection": 1},
        )
        assert json.dumps(snap.to_dict())

    def test_to_dict_from_dict_round_trip(self):
        rec = DecisionTraceRecord(kind=DecisionKind.SOURCE_SWITCH.value, source_modality="audio")
        ev = ControlTimelineEvent(sequence=7, record=rec)
        snap = ExplainabilitySnapshot(
            events=[ev],
            total_events=1,
            trace_id="t-snap",
            runtime_session_id="s-snap",
            kind_counts={"source_switch": 1},
        )
        d = snap.to_dict()
        snap2 = ExplainabilitySnapshot.from_dict(d)
        assert snap2.snapshot_id == snap.snapshot_id
        assert snap2.total_events == 1
        assert snap2.trace_id == "t-snap"
        assert snap2.runtime_session_id == "s-snap"
        assert len(snap2.events) == 1
        assert snap2.events[0].record.kind == DecisionKind.SOURCE_SWITCH.value
        assert snap2.kind_counts == {"source_switch": 1}

    def test_kind_counts_correctly_tallied(self):
        # Build snapshot manually and verify kind_counts
        snap = ExplainabilitySnapshot(
            events=[
                ControlTimelineEvent(record=DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value)),
                ControlTimelineEvent(record=DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value)),
                ControlTimelineEvent(record=DecisionTraceRecord(kind=DecisionKind.FALLBACK_TRANSITION.value)),
            ],
            total_events=3,
            kind_counts={"route_selection": 2, "fallback_transition": 1},
        )
        assert snap.kind_counts["route_selection"] == 2
        assert snap.kind_counts["fallback_transition"] == 1


# ---------------------------------------------------------------------------
# 5. DecisionTimeline
# ---------------------------------------------------------------------------


class TestDecisionTimeline:
    def test_initial_state_is_empty(self):
        tl = DecisionTimeline()
        assert tl.event_count == 0

    def test_append_returns_control_timeline_event(self):
        tl = DecisionTimeline()
        rec = DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value)
        ev = tl.append(rec)
        assert isinstance(ev, ControlTimelineEvent)
        assert ev.sequence == 1
        assert ev.record is rec

    def test_sequence_is_monotonically_increasing(self):
        tl = DecisionTimeline()
        sequences = []
        for i in range(5):
            rec = DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value)
            ev = tl.append(rec)
            sequences.append(ev.sequence)
        assert sequences == sorted(sequences)
        assert sequences == list(range(1, 6))

    def test_clear_resets_event_count_and_sequence(self):
        tl = DecisionTimeline()
        for _ in range(3):
            tl.append(DecisionTraceRecord())
        assert tl.event_count == 3
        tl.clear()
        assert tl.event_count == 0
        # sequence resets too
        ev = tl.append(DecisionTraceRecord())
        assert ev.sequence == 1

    def test_snapshot_returns_ordered_events(self):
        tl = DecisionTimeline()
        for kind in [DecisionKind.ROUTE_SELECTION, DecisionKind.FALLBACK_TRANSITION, DecisionKind.OPERATOR_OVERRIDE]:
            tl.append(DecisionTraceRecord(kind=kind.value))
        snap = tl.snapshot()
        seqs = [ev.sequence for ev in snap.events]
        assert seqs == sorted(seqs)

    def test_snapshot_kind_counts_correct(self):
        tl = DecisionTimeline()
        for _ in range(3):
            tl.append(DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value))
        for _ in range(2):
            tl.append(DecisionTraceRecord(kind=DecisionKind.FALLBACK_TRANSITION.value))
        snap = tl.snapshot()
        assert snap.kind_counts.get("route_selection") == 3
        assert snap.kind_counts.get("fallback_transition") == 2

    def test_snapshot_is_independent_copy(self):
        tl = DecisionTimeline()
        tl.append(DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value))
        snap = tl.snapshot()
        # Appending after snapshot does not affect the snapshot
        tl.append(DecisionTraceRecord(kind=DecisionKind.FALLBACK_TRANSITION.value))
        assert len(snap.events) == 1
        assert tl.event_count == 2

    def test_max_events_eviction(self):
        tl = DecisionTimeline(max_events=5)
        for i in range(10):
            tl.append(DecisionTraceRecord())
        assert tl.event_count == 5

    def test_thread_safety(self):
        """Multiple threads can append concurrently without corrupting state."""
        tl = DecisionTimeline(max_events=1000)
        errors: List[Exception] = []

        def _worker():
            try:
                for _ in range(50):
                    tl.append(DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert tl.event_count == 200


# ---------------------------------------------------------------------------
# 6. Singletons
# ---------------------------------------------------------------------------


class TestSingletons:
    def test_get_decision_timeline_returns_same_object(self):
        reset_decision_timeline()
        tl1 = get_decision_timeline()
        tl2 = get_decision_timeline()
        assert tl1 is tl2

    def test_reset_decision_timeline_clears_singleton(self):
        reset_decision_timeline()
        tl1 = get_decision_timeline()
        tl1.append(DecisionTraceRecord())
        reset_decision_timeline()
        tl2 = get_decision_timeline()
        assert tl1 is not tl2
        assert tl2.event_count == 0


# ---------------------------------------------------------------------------
# 7. record_decision_event (public builder)
# ---------------------------------------------------------------------------


class TestRecordDecisionEvent:
    def setup_method(self):
        reset_decision_timeline()

    def test_route_selection_kind(self):
        ev = record_decision_event(
            kind=DecisionKind.ROUTE_SELECTION,
            decision_summary="native_multimodal",
            rationale="tier-1",
            route_kind="native_multimodal",
        )
        assert isinstance(ev, ControlTimelineEvent)
        assert ev.record.kind == DecisionKind.ROUTE_SELECTION.value
        assert ev.record.route_kind == "native_multimodal"

    def test_fallback_transition_kind(self):
        ev = record_decision_event(
            kind=DecisionKind.FALLBACK_TRANSITION,
            decision_summary="fallback",
            rationale="no provider",
            route_kind="text_only",
            previous_route_kind="native_multimodal",
            fallback_reason="provider_unavailable",
        )
        assert ev is not None
        assert ev.record.kind == DecisionKind.FALLBACK_TRANSITION.value
        assert ev.record.previous_route_kind == "native_multimodal"
        assert ev.record.fallback_reason == "provider_unavailable"

    def test_operator_override_kind(self):
        ev = record_decision_event(
            kind=DecisionKind.OPERATOR_OVERRIDE,
            decision_summary="override",
            rationale="maintenance",
            override_domains=["multimodal_mode"],
            override_reason="maintenance_window",
        )
        assert ev is not None
        assert ev.record.kind == DecisionKind.OPERATOR_OVERRIDE.value
        assert ev.record.override_domains == ["multimodal_mode"]

    def test_trust_safety_gating_kind(self):
        ev = record_decision_event(
            kind=DecisionKind.TRUST_SAFETY_GATING,
            decision_summary="gated",
            rationale="elevated risk",
            gating_reason="risk_tier_high",
            gated_domains=["remote_execution"],
        )
        assert ev is not None
        assert ev.record.kind == DecisionKind.TRUST_SAFETY_GATING.value
        assert ev.record.gated_domains == ["remote_execution"]

    def test_execution_locality_change_kind(self):
        ev = record_decision_event(
            kind=DecisionKind.EXECUTION_LOCALITY_CHANGE,
            decision_summary="locality changed",
            rationale="cross-device expansion",
            previous_locality="local",
            new_locality="remote",
            causal_policy="cross_device_policy",
        )
        assert ev is not None
        assert ev.record.kind == DecisionKind.EXECUTION_LOCALITY_CHANGE.value
        assert ev.record.new_locality == "remote"

    def test_event_appended_to_global_timeline(self):
        tl = get_decision_timeline()
        before = tl.event_count
        record_decision_event(kind=DecisionKind.ROUTE_SELECTION, decision_summary="test")
        assert tl.event_count == before + 1


# ---------------------------------------------------------------------------
# 8. record_route_selection_event
# ---------------------------------------------------------------------------


class TestRecordRouteSelectionEvent:
    def setup_method(self):
        reset_decision_timeline()

    def test_produces_route_selection_event(self):
        route_dict = {
            "route_type": "native_multimodal",
            "is_native_multimodal": True,
            "route_reason": "perception confidence high",
        }
        ev = record_route_selection_event(route_dict=route_dict, trace_id="t-1")
        assert ev is not None
        assert ev.record.kind == DecisionKind.ROUTE_SELECTION.value
        assert ev.record.route_kind == "native_multimodal"

    def test_also_emits_fallback_event_when_fallback_present(self):
        route_dict = {
            "route_type": "text_only",
            "is_native_multimodal": False,
            "route_reason": "degraded",
            "fallback_reason": "native MM provider unavailable",
        }
        record_route_selection_event(route_dict=route_dict, trace_id="t-2")
        tl = get_decision_timeline()
        kinds = [ev.record.kind for ev in tl.snapshot().events]
        assert DecisionKind.ROUTE_SELECTION.value in kinds
        assert DecisionKind.FALLBACK_TRANSITION.value in kinds

    def test_no_fallback_event_for_native_multimodal(self):
        route_dict = {
            "route_type": "native_multimodal",
            "is_native_multimodal": True,
            "route_reason": "native MM available",
            "fallback_reason": None,
        }
        record_route_selection_event(route_dict=route_dict, trace_id="t-3")
        tl = get_decision_timeline()
        kinds = [ev.record.kind for ev in tl.snapshot().events]
        assert DecisionKind.ROUTE_SELECTION.value in kinds
        assert DecisionKind.FALLBACK_TRANSITION.value not in kinds

    def test_never_raises_on_invalid_input(self):
        # Should not raise even with None dict
        ev = record_route_selection_event(route_dict={})
        # Returns None or event (either is acceptable); must not raise
        assert ev is None or isinstance(ev, ControlTimelineEvent)


# ---------------------------------------------------------------------------
# 9. record_operator_override_event
# ---------------------------------------------------------------------------


class TestRecordOperatorOverrideEvent:
    def setup_method(self):
        reset_decision_timeline()

    def test_returns_none_when_no_active_override(self):
        ev = record_operator_override_event(
            override_snapshot_dict={},
            trace_id="t-1",
        )
        assert ev is None

    def test_returns_event_when_active_override(self):
        snap_dict = {
            "active_override_set": {
                "multimodal_mode": "force_off",
                "override_reason": "maintenance_window",
            },
            "applied_records": [
                {"domain": "multimodal_mode", "override_reason": "maintenance_window"},
            ],
        }
        ev = record_operator_override_event(
            override_snapshot_dict=snap_dict,
            trace_id="t-2",
        )
        assert ev is not None
        assert ev.record.kind == DecisionKind.OPERATOR_OVERRIDE.value
        assert "multimodal_mode" in ev.record.override_domains

    def test_never_raises(self):
        ev = record_operator_override_event(override_snapshot_dict=None)  # type: ignore[arg-type]
        assert ev is None or isinstance(ev, ControlTimelineEvent)


# ---------------------------------------------------------------------------
# 10. record_trust_safety_gating_event
# ---------------------------------------------------------------------------


class TestRecordTrustSafetyGatingEvent:
    def setup_method(self):
        reset_decision_timeline()

    def test_returns_none_when_no_gating_low_risk(self):
        ev = record_trust_safety_gating_event(
            permission_safety_dict={"execution_risk_tier": "low"},
        )
        assert ev is None

    def test_returns_event_when_gating_reason_present(self):
        ev = record_trust_safety_gating_event(
            permission_safety_dict={
                "gating_reason": "risk_tier_high",
                "execution_risk_tier": "high",
            },
        )
        assert ev is not None
        assert ev.record.kind == DecisionKind.TRUST_SAFETY_GATING.value
        assert ev.record.gating_reason == "risk_tier_high"

    def test_returns_event_for_elevated_risk_tier(self):
        ev = record_trust_safety_gating_event(
            permission_safety_dict={"execution_risk_tier": "critical"},
        )
        assert ev is not None

    def test_never_raises(self):
        ev = record_trust_safety_gating_event(permission_safety_dict=None)  # type: ignore[arg-type]
        assert ev is None or isinstance(ev, ControlTimelineEvent)


# ---------------------------------------------------------------------------
# 11. record_source_switch_event
# ---------------------------------------------------------------------------


class TestRecordSourceSwitchEvent:
    def setup_method(self):
        reset_decision_timeline()

    def test_returns_none_when_no_switch_events(self):
        ev = record_source_switch_event(
            source_recovery_dict={"primary_source_switch_events": []},
        )
        assert ev is None

    def test_returns_event_when_switch_present(self):
        snap_dict = {
            "primary_source_switch_events": [
                {
                    "modality": "audio",
                    "previous_primary_id": "builtin:microphone",
                    "new_primary_id": "builtin:microphone-v2",
                    "switch_reason": "re-election",
                }
            ]
        }
        ev = record_source_switch_event(source_recovery_dict=snap_dict)
        assert ev is not None
        assert ev.record.kind == DecisionKind.SOURCE_SWITCH.value
        assert ev.record.source_modality == "audio"
        assert ev.record.previous_source_id == "builtin:microphone"
        assert ev.record.new_source_id == "builtin:microphone-v2"
        assert ev.record.source_switch_reason == "re-election"

    def test_never_raises(self):
        ev = record_source_switch_event(source_recovery_dict=None)  # type: ignore[arg-type]
        assert ev is None or isinstance(ev, ControlTimelineEvent)


# ---------------------------------------------------------------------------
# 12. build_explainability_snapshot
# ---------------------------------------------------------------------------


class TestBuildExplainabilitySnapshot:
    def setup_method(self):
        reset_decision_timeline()

    def test_returns_explainability_snapshot(self):
        record_decision_event(
            kind=DecisionKind.ROUTE_SELECTION,
            decision_summary="test",
            rationale="test rationale",
        )
        snap = build_explainability_snapshot(trace_id="t-1", runtime_session_id="s-1")
        assert isinstance(snap, ExplainabilitySnapshot)
        assert snap.total_events == 1
        assert snap.trace_id == "t-1"
        assert snap.runtime_session_id == "s-1"

    def test_total_events_matches_event_list(self):
        for _ in range(4):
            record_decision_event(kind=DecisionKind.ROUTE_SELECTION, decision_summary="x")
        snap = build_explainability_snapshot()
        assert snap.total_events == len(snap.events)

    def test_kind_counts_sums_to_total_events(self):
        record_decision_event(kind=DecisionKind.ROUTE_SELECTION, decision_summary="a")
        record_decision_event(kind=DecisionKind.FALLBACK_TRANSITION, decision_summary="b")
        record_decision_event(kind=DecisionKind.ROUTE_SELECTION, decision_summary="c")
        snap = build_explainability_snapshot()
        total_from_counts = sum(snap.kind_counts.values())
        assert total_from_counts == snap.total_events

    def test_never_raises(self):
        # Patch get_decision_timeline to raise; should return empty snapshot
        with patch(
            "core.decision_timeline.get_decision_timeline",
            side_effect=RuntimeError("forced failure"),
        ):
            snap = build_explainability_snapshot()
        assert isinstance(snap, ExplainabilitySnapshot)
        assert snap.events == []


# ---------------------------------------------------------------------------
# 13. Route/model selection emits structured trace (acceptance)
# ---------------------------------------------------------------------------


class TestRouteSelectionAcceptance:
    def setup_method(self):
        reset_decision_timeline()

    def test_route_selection_event_in_timeline(self):
        route_dict = {
            "route_type": "native_multimodal",
            "is_native_multimodal": True,
            "route_reason": "native MM provider available",
            "selected_model": "gpt-4o",
        }
        record_route_selection_event(route_dict=route_dict, trace_id="t-route")
        snap = build_explainability_snapshot()
        kinds = [ev.record.kind for ev in snap.events]
        assert DecisionKind.ROUTE_SELECTION.value in kinds

    def test_route_kind_matches_route_dict(self):
        route_dict = {
            "route_type": "partial_multimodal",
            "is_native_multimodal": False,
            "route_reason": "partial support",
        }
        record_route_selection_event(route_dict=route_dict)
        snap = build_explainability_snapshot()
        route_ev = next(
            (ev for ev in snap.events if ev.record.kind == DecisionKind.ROUTE_SELECTION.value),
            None,
        )
        assert route_ev is not None
        assert route_ev.record.route_kind == "partial_multimodal"

    def test_rationale_non_empty_from_route_reason(self):
        route_dict = {
            "route_type": "text_only",
            "route_reason": "no multimodal provider available",
        }
        record_route_selection_event(route_dict=route_dict)
        snap = build_explainability_snapshot()
        route_ev = next(
            ev for ev in snap.events if ev.record.kind == DecisionKind.ROUTE_SELECTION.value
        )
        assert route_ev.record.rationale
        assert "no multimodal provider" in route_ev.record.rationale


# ---------------------------------------------------------------------------
# 14. Fallback transitions appear in replay timeline (acceptance)
# ---------------------------------------------------------------------------


class TestFallbackTransitionAcceptance:
    def setup_method(self):
        reset_decision_timeline()

    def test_fallback_transition_present_after_route_with_fallback(self):
        route_dict = {
            "route_type": "text_only",
            "is_native_multimodal": False,
            "route_reason": "degraded",
            "fallback_reason": "native MM provider reported unhealthy",
        }
        record_route_selection_event(route_dict=route_dict, trace_id="t-fb")
        snap = build_explainability_snapshot()
        kinds = [ev.record.kind for ev in snap.events]
        assert DecisionKind.FALLBACK_TRANSITION.value in kinds

    def test_fallback_reason_non_empty(self):
        route_dict = {
            "route_type": "text_only",
            "fallback_reason": "capability_mismatch",
        }
        record_route_selection_event(route_dict=route_dict)
        snap = build_explainability_snapshot()
        fb_ev = next(
            ev for ev in snap.events if ev.record.kind == DecisionKind.FALLBACK_TRANSITION.value
        )
        assert fb_ev.record.fallback_reason == "capability_mismatch"

    def test_previous_route_kind_present(self):
        route_dict = {
            "route_type": "text_only",
            "fallback_reason": "health_check_failed",
        }
        record_route_selection_event(route_dict=route_dict)
        snap = build_explainability_snapshot()
        fb_ev = next(
            ev for ev in snap.events if ev.record.kind == DecisionKind.FALLBACK_TRANSITION.value
        )
        assert fb_ev.record.previous_route_kind is not None


# ---------------------------------------------------------------------------
# 15. Source switch / recovery correlated in trace (acceptance)
# ---------------------------------------------------------------------------


class TestSourceSwitchAcceptance:
    def setup_method(self):
        reset_decision_timeline()

    def test_source_switch_record_has_modality_and_ids(self):
        snap_dict = {
            "primary_source_switch_events": [
                {
                    "modality": "video",
                    "previous_primary_id": "builtin:webcam",
                    "new_primary_id": "external:usb-cam",
                    "switch_reason": "quality_upgrade",
                }
            ]
        }
        record_source_switch_event(source_recovery_dict=snap_dict, trace_id="t-sw")
        snap = build_explainability_snapshot()
        sw_ev = next(
            ev for ev in snap.events if ev.record.kind == DecisionKind.SOURCE_SWITCH.value
        )
        assert sw_ev.record.source_modality == "video"
        assert sw_ev.record.previous_source_id == "builtin:webcam"
        assert sw_ev.record.new_source_id == "external:usb-cam"
        assert sw_ev.record.source_switch_reason == "quality_upgrade"


# ---------------------------------------------------------------------------
# 16. Operator override influence in explanation artifacts (acceptance)
# ---------------------------------------------------------------------------


class TestOperatorOverrideAcceptance:
    def setup_method(self):
        reset_decision_timeline()

    def test_override_domains_and_reason_preserved(self):
        snap_dict = {
            "active_override_set": {
                "multimodal_mode": "force_off",
                "override_reason": "maintenance_window",
            },
            "applied_records": [
                {"domain": "multimodal_mode", "override_reason": "maintenance_window"},
                {"domain": "execution_locality", "override_reason": "maintenance_window"},
            ],
        }
        record_operator_override_event(override_snapshot_dict=snap_dict, trace_id="t-ov")
        snap = build_explainability_snapshot()
        ov_ev = next(
            ev for ev in snap.events if ev.record.kind == DecisionKind.OPERATOR_OVERRIDE.value
        )
        assert "multimodal_mode" in ov_ev.record.override_domains
        assert ov_ev.record.override_reason == "maintenance_window"


# ---------------------------------------------------------------------------
# 17. Serialisation and determinism (acceptance)
# ---------------------------------------------------------------------------


class TestSerialisationAndDeterminism:
    def setup_method(self):
        reset_decision_timeline()

    def test_full_round_trip_via_json(self):
        record_route_selection_event(
            route_dict={
                "route_type": "native_multimodal",
                "is_native_multimodal": True,
                "route_reason": "high confidence",
            },
            trace_id="t-rt",
        )
        snap = build_explainability_snapshot(trace_id="t-rt", runtime_session_id="s-rt")
        raw = snap.to_dict()
        json_str = json.dumps(raw)
        recovered = json.loads(json_str)
        snap2 = ExplainabilitySnapshot.from_dict(recovered)

        assert snap2.snapshot_id == snap.snapshot_id
        assert snap2.total_events == snap.total_events
        assert len(snap2.events) == len(snap.events)
        for ev, ev2 in zip(snap.events, snap2.events):
            assert ev2.record.kind == ev.record.kind
            assert ev2.record.route_kind == ev.record.route_kind

    def test_two_snapshots_from_same_timeline_have_same_events(self):
        tl = get_decision_timeline()
        tl.append(DecisionTraceRecord(kind=DecisionKind.ROUTE_SELECTION.value, rationale="x"))
        snap1 = tl.snapshot(trace_id="t")
        snap2 = tl.snapshot(trace_id="t")
        assert len(snap1.events) == len(snap2.events)
        for e1, e2 in zip(snap1.events, snap2.events):
            assert e1.event_id == e2.event_id
            assert e1.sequence == e2.sequence


# ---------------------------------------------------------------------------
# 18. Explanations derive from canonical decisions (acceptance)
# ---------------------------------------------------------------------------


class TestExplanationsFromCanonicalDecisions:
    def setup_method(self):
        reset_decision_timeline()

    def test_events_are_control_timeline_event_objects(self):
        record_decision_event(
            kind=DecisionKind.ROUTE_SELECTION,
            decision_summary="test",
            rationale="canonical",
        )
        snap = build_explainability_snapshot()
        for ev in snap.events:
            assert isinstance(ev, ControlTimelineEvent)

    def test_each_event_kind_is_known_decision_kind(self):
        for kind in [
            DecisionKind.ROUTE_SELECTION,
            DecisionKind.FALLBACK_TRANSITION,
            DecisionKind.OPERATOR_OVERRIDE,
        ]:
            record_decision_event(kind=kind, decision_summary="test", rationale="x")
        snap = build_explainability_snapshot()
        known_values = {member.value for member in DecisionKind}
        for ev in snap.events:
            assert ev.record.kind in known_values

    def test_rationale_fields_non_empty_from_canonical_input(self):
        record_route_selection_event(
            route_dict={
                "route_type": "text_only",
                "route_reason": "capability mismatch with request",
                "fallback_reason": "no native MM provider",
            }
        )
        snap = build_explainability_snapshot()
        for ev in snap.events:
            assert ev.record.rationale, (
                f"Event {ev.record.kind} has empty rationale"
            )


# ---------------------------------------------------------------------------
# 19. DesktopPresenceRuntime.decision_timeline_replay
# ---------------------------------------------------------------------------


class TestDesktopPresenceRuntimeDecisionTimelineReplay:
    def setup_method(self):
        reset_decision_timeline()

    def _make_runtime(self):
        """Return a DesktopPresenceRuntime instance with minimal dependencies mocked."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        try:
            from core.multimodal.perception_source_registry import PerceptionSourceRegistry
            rt._source_registry = PerceptionSourceRegistry()
        except Exception:
            rt._source_registry = None
        rt._config = {}
        return rt

    def test_returns_required_keys(self):
        rt = self._make_runtime()
        result = rt.decision_timeline_replay()
        assert "snapshot_id" in result
        assert "events" in result
        assert "total_events" in result
        assert "kind_counts" in result

    def test_prefers_embedded_snapshot(self):
        snap = build_explainability_snapshot(trace_id="t-embed")
        snap_dict = snap.to_dict()
        fake_result = {"metadata": {"decision_timeline_snapshot": snap_dict}}
        rt = self._make_runtime()
        result = rt.decision_timeline_replay(result=fake_result)
        assert result["snapshot_id"] == snap_dict["snapshot_id"]

    def test_falls_back_to_live_timeline(self):
        record_decision_event(kind=DecisionKind.ROUTE_SELECTION, decision_summary="live")
        rt = self._make_runtime()
        result = rt.decision_timeline_replay()  # No result provided
        assert result["total_events"] >= 1

    def test_never_raises_on_bad_input(self):
        rt = self._make_runtime()
        # Should not raise
        result = rt.decision_timeline_replay(result={"metadata": {}})
        assert isinstance(result, dict)
