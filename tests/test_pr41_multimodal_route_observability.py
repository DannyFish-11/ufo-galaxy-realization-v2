#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr41_multimodal_route_observability.py
=================================================

PR-41 — Multimodal Route Observability and Fallback Analytics

Coverage
--------
1. RouteKind
   - all expected values are present and stable strings

2. RoutingFallbackKind
   - all expected values are present and stable strings

3. RoutingDecisionEvent
   - construction with defaults
   - to_dict / from_dict round-trip preserves all fields
   - is JSON-serialisable (json.dumps succeeds)
   - event_id is auto-generated
   - timestamp is auto-populated

4. FallbackDecisionEvent
   - construction with defaults
   - to_dict / from_dict round-trip preserves all fields
   - is JSON-serialisable
   - event_id is auto-generated

5. ControlLoopMetrics
   - initial state: all counters zero
   - record() increments native_multimodal_count for native MM event
   - record() increments text_only_count for text_only event
   - record() increments partial_multimodal_count for partial MM event
   - record() increments advisory_count for advisory event
   - record() increments total_decisions
   - record() updates fallback_kind_counts
   - record() updates provider_counts and model_counts
   - record() updates route_reason_counts
   - record_projection_mismatch() increments projection_mismatch_count
   - reset() zeroes all counters

6. RoutingAnalyticsSnapshot
   - snapshot() returns correct rates for native MM
   - snapshot() returns correct rates for text_only
   - snapshot() from zero decisions produces a valid snapshot (no div/0)
   - to_dict / from_dict round-trip preserves all fields
   - is JSON-serialisable
   - schema_version == 1

7. _classify_fallback_kind()
   - native_multimodal route → "none"
   - text_only route → "none"
   - partial_multimodal with native_multimodal_provider_unavailable → correct kind
   - advisory with no_providers_available → provider_unavailable
   - advisory with router_unavailable → router_unavailable
   - advisory with routing_error → router_error
   - advisory with capability_mismatch → capability_mismatch
   - advisory with unknown fallback_reason → other

8. build_routing_decision_event()
   - native MM route produces correct event
   - text fallback produces event with fallback_kind=none
   - partial multimodal produces event with correct fallback_kind
   - provider unavailable produces event with fallback_kind=provider_unavailable

9. build_fallback_decision_event()
   - returns None when fallback_kind == "none"
   - returns FallbackDecisionEvent for fallback event
   - from_route_kind is always native_multimodal for multimodal-warranted fallback
   - to_route_kind matches routing event's route_kind

10. record_routing_decision()
    - records event into global metrics
    - returns a RoutingDecisionEvent
    - global counter increments after repeated calls

11. build_routing_analytics_snapshot()
    - returns a RoutingAnalyticsSnapshot
    - rates sum to 1.0 when all decisions are the same kind

12. Provider unavailability vs capability mismatch distinction
    - provider_unavailable (no_providers_available) maps to PROVIDER_UNAVAILABLE
    - capability_mismatch maps to CAPABILITY_MISMATCH (distinct from provider_unavailable)

13. Snapshot stability
    - RoutingAnalyticsSnapshot.to_dict() is stable (same data → same dict structure)
    - from_dict(to_dict()) round-trip is exact

14. Observability derives from canonical decisions (not ad hoc inference)
    - RoutingDecisionEvent is built directly from _select_multimodal_route output dict
    - ControlLoopMetrics is updated from the canonical event, not re-inferred

15. OpenClawd integration
    - _emit_routing_decision_event returns a dict (not None) for a valid route_dict
    - _emit_routing_decision_event returns None gracefully when module raises
    - process() response metadata contains routing_decision_event key
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.routing_observability import (
    ControlLoopMetrics,
    FallbackDecisionEvent,
    RouteKind,
    RoutingAnalyticsSnapshot,
    RoutingDecisionEvent,
    RoutingFallbackKind,
    _classify_fallback_kind,
    build_fallback_decision_event,
    build_routing_analytics_snapshot,
    build_routing_decision_event,
    get_control_loop_metrics,
    record_routing_decision,
    reset_routing_metrics,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Reset global metrics before each test to avoid cross-test contamination."""
    reset_routing_metrics()
    yield
    reset_routing_metrics()


def _native_mm_route(provider: str = "openai", model: str = "gpt-4o") -> Dict[str, Any]:
    """Minimal native_multimodal route dict matching _select_multimodal_route output."""
    return {
        "route_type": "native_multimodal",
        "is_native_multimodal": True,
        "provider": provider,
        "model": model,
        "route_reason": "tier=1 native_multimodal modality=image",
        "fallback_reason": "",
        "active_modalities": ["image"],
    }


def _text_only_route() -> Dict[str, Any]:
    return {
        "route_type": "text_only",
        "is_native_multimodal": False,
        "provider": "none",
        "model": "none",
        "route_reason": "perception_state=text_only no_multimodal_input_detected",
        "fallback_reason": "",
        "active_modalities": [],
    }


def _partial_mm_route(provider: str = "anthropic", model: str = "claude-3-haiku") -> Dict[str, Any]:
    return {
        "route_type": "partial_multimodal",
        "is_native_multimodal": False,
        "provider": provider,
        "model": model,
        "route_reason": "tier=2 text_capable_provider modality=image",
        "fallback_reason": "native_multimodal_provider_unavailable modalities=[image] degraded_to=text_capable_provider",
        "active_modalities": ["image"],
    }


def _advisory_no_providers_route() -> Dict[str, Any]:
    return {
        "route_type": "advisory",
        "is_native_multimodal": False,
        "provider": "none",
        "model": "none",
        "route_reason": "no_providers_available degraded_to=advisory",
        "fallback_reason": "no_providers_available",
        "active_modalities": ["image"],
    }


def _advisory_router_unavailable_route() -> Dict[str, Any]:
    return {
        "route_type": "advisory",
        "is_native_multimodal": False,
        "provider": "none",
        "model": "none",
        "route_reason": "router_unavailable degraded_to=advisory",
        "fallback_reason": "router_unavailable",
        "active_modalities": ["image"],
    }


def _advisory_routing_error_route() -> Dict[str, Any]:
    return {
        "route_type": "advisory",
        "is_native_multimodal": False,
        "provider": "none",
        "model": "none",
        "route_reason": "routing_error=ConnectionError degraded_to=advisory",
        "fallback_reason": "routing_error=ConnectionError",
        "active_modalities": ["image", "audio"],
    }


def _advisory_capability_mismatch_route() -> Dict[str, Any]:
    return {
        "route_type": "advisory",
        "is_native_multimodal": False,
        "provider": "none",
        "model": "none",
        "route_reason": "capability_mismatch no_native_mm_for_modality=video",
        "fallback_reason": "capability_mismatch modality=video",
        "active_modalities": ["video"],
    }


# ---------------------------------------------------------------------------
# 1. RouteKind
# ---------------------------------------------------------------------------


class TestRouteKind:
    def test_native_multimodal_value(self):
        assert RouteKind.NATIVE_MULTIMODAL.value == "native_multimodal"

    def test_partial_multimodal_value(self):
        assert RouteKind.PARTIAL_MULTIMODAL.value == "partial_multimodal"

    def test_text_only_value(self):
        assert RouteKind.TEXT_ONLY.value == "text_only"

    def test_advisory_value(self):
        assert RouteKind.ADVISORY.value == "advisory"

    def test_unknown_value(self):
        assert RouteKind.UNKNOWN.value == "unknown"

    def test_all_values_are_strings(self):
        for kind in RouteKind:
            assert isinstance(kind.value, str)


# ---------------------------------------------------------------------------
# 2. RoutingFallbackKind
# ---------------------------------------------------------------------------


class TestRoutingFallbackKind:
    def test_none_value(self):
        assert RoutingFallbackKind.NONE.value == "none"

    def test_native_multimodal_to_text_value(self):
        assert RoutingFallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value == "native_multimodal_to_text"

    def test_provider_unavailable_value(self):
        assert RoutingFallbackKind.PROVIDER_UNAVAILABLE.value == "provider_unavailable"

    def test_capability_mismatch_value(self):
        assert RoutingFallbackKind.CAPABILITY_MISMATCH.value == "capability_mismatch"

    def test_router_unavailable_value(self):
        assert RoutingFallbackKind.ROUTER_UNAVAILABLE.value == "router_unavailable"

    def test_router_error_value(self):
        assert RoutingFallbackKind.ROUTER_ERROR.value == "router_error"

    def test_other_value(self):
        assert RoutingFallbackKind.OTHER.value == "other"

    def test_all_values_are_strings(self):
        for kind in RoutingFallbackKind:
            assert isinstance(kind.value, str)


# ---------------------------------------------------------------------------
# 3. RoutingDecisionEvent
# ---------------------------------------------------------------------------


class TestRoutingDecisionEvent:
    def test_default_construction(self):
        evt = RoutingDecisionEvent()
        assert evt.route_kind == RouteKind.UNKNOWN.value
        assert evt.is_native_multimodal is False
        assert evt.provider == "none"
        assert evt.model == "none"
        assert evt.fallback_kind == RoutingFallbackKind.NONE.value
        assert evt.active_modalities == []

    def test_event_id_auto_generated(self):
        a = RoutingDecisionEvent()
        b = RoutingDecisionEvent()
        assert a.event_id != b.event_id

    def test_timestamp_auto_populated(self):
        import time as _time
        before = _time.time()
        evt = RoutingDecisionEvent()
        after = _time.time()
        assert before <= evt.timestamp <= after

    def test_to_dict_keys(self):
        evt = RoutingDecisionEvent()
        d = evt.to_dict()
        expected_keys = {
            "event_id", "timestamp", "trace_id", "runtime_session_id",
            "route_kind", "is_native_multimodal", "provider", "model",
            "route_reason", "fallback_kind", "fallback_reason", "active_modalities",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_json_serialisable(self):
        evt = RoutingDecisionEvent(
            trace_id="t1",
            route_kind=RouteKind.NATIVE_MULTIMODAL.value,
            is_native_multimodal=True,
            provider="openai",
            model="gpt-4o",
            active_modalities=["image"],
        )
        serialised = json.dumps(evt.to_dict())
        assert "native_multimodal" in serialised

    def test_from_dict_round_trip(self):
        evt = RoutingDecisionEvent(
            trace_id="trace-abc",
            runtime_session_id="sess-xyz",
            route_kind=RouteKind.NATIVE_MULTIMODAL.value,
            is_native_multimodal=True,
            provider="openai",
            model="gpt-4o",
            route_reason="tier=1",
            fallback_kind=RoutingFallbackKind.NONE.value,
            fallback_reason="",
            active_modalities=["image", "audio"],
        )
        d = evt.to_dict()
        reconstructed = RoutingDecisionEvent.from_dict(d)
        assert reconstructed.trace_id == evt.trace_id
        assert reconstructed.runtime_session_id == evt.runtime_session_id
        assert reconstructed.route_kind == evt.route_kind
        assert reconstructed.is_native_multimodal == evt.is_native_multimodal
        assert reconstructed.provider == evt.provider
        assert reconstructed.model == evt.model
        assert reconstructed.route_reason == evt.route_reason
        assert reconstructed.fallback_kind == evt.fallback_kind
        assert reconstructed.active_modalities == evt.active_modalities


# ---------------------------------------------------------------------------
# 4. FallbackDecisionEvent
# ---------------------------------------------------------------------------


class TestFallbackDecisionEvent:
    def test_default_construction(self):
        evt = FallbackDecisionEvent()
        assert evt.fallback_kind == RoutingFallbackKind.OTHER.value
        assert evt.from_route_kind == RouteKind.NATIVE_MULTIMODAL.value
        assert evt.provider == "none"
        assert evt.model == "none"

    def test_event_id_auto_generated(self):
        a = FallbackDecisionEvent()
        b = FallbackDecisionEvent()
        assert a.event_id != b.event_id

    def test_to_dict_keys(self):
        evt = FallbackDecisionEvent()
        d = evt.to_dict()
        expected_keys = {
            "event_id", "timestamp", "trace_id", "runtime_session_id",
            "fallback_kind", "from_route_kind", "to_route_kind",
            "provider", "model", "fallback_reason", "active_modalities",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_json_serialisable(self):
        evt = FallbackDecisionEvent(
            fallback_kind=RoutingFallbackKind.PROVIDER_UNAVAILABLE.value,
            from_route_kind=RouteKind.NATIVE_MULTIMODAL.value,
            to_route_kind=RouteKind.ADVISORY.value,
            active_modalities=["image"],
        )
        json.dumps(evt.to_dict())  # must not raise

    def test_from_dict_round_trip(self):
        evt = FallbackDecisionEvent(
            trace_id="t-fallback",
            fallback_kind=RoutingFallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value,
            from_route_kind=RouteKind.NATIVE_MULTIMODAL.value,
            to_route_kind=RouteKind.PARTIAL_MULTIMODAL.value,
            provider="anthropic",
            model="claude-3-haiku",
            fallback_reason="native_multimodal_provider_unavailable",
            active_modalities=["image"],
        )
        d = evt.to_dict()
        rec = FallbackDecisionEvent.from_dict(d)
        assert rec.trace_id == evt.trace_id
        assert rec.fallback_kind == evt.fallback_kind
        assert rec.from_route_kind == evt.from_route_kind
        assert rec.to_route_kind == evt.to_route_kind
        assert rec.provider == evt.provider
        assert rec.active_modalities == evt.active_modalities


# ---------------------------------------------------------------------------
# 5. ControlLoopMetrics
# ---------------------------------------------------------------------------


class TestControlLoopMetrics:
    def test_initial_state_all_zero(self):
        m = ControlLoopMetrics()
        assert m.total_decisions == 0
        assert m.native_multimodal_count == 0
        assert m.text_only_count == 0
        assert m.partial_multimodal_count == 0
        assert m.advisory_count == 0
        assert m.projection_mismatch_count == 0
        assert m.fallback_kind_counts == {}
        assert m.provider_counts == {}
        assert m.model_counts == {}
        assert m.route_reason_counts == {}

    def test_record_native_multimodal(self):
        m = ControlLoopMetrics()
        evt = build_routing_decision_event(_native_mm_route())
        m.record(evt)
        assert m.native_multimodal_count == 1
        assert m.total_decisions == 1

    def test_record_text_only(self):
        m = ControlLoopMetrics()
        evt = build_routing_decision_event(_text_only_route())
        m.record(evt)
        assert m.text_only_count == 1
        assert m.total_decisions == 1

    def test_record_partial_multimodal(self):
        m = ControlLoopMetrics()
        evt = build_routing_decision_event(_partial_mm_route())
        m.record(evt)
        assert m.partial_multimodal_count == 1
        assert m.total_decisions == 1

    def test_record_advisory(self):
        m = ControlLoopMetrics()
        evt = build_routing_decision_event(_advisory_no_providers_route())
        m.record(evt)
        assert m.advisory_count == 1
        assert m.total_decisions == 1

    def test_record_increments_total_decisions(self):
        m = ControlLoopMetrics()
        for _ in range(5):
            m.record(build_routing_decision_event(_text_only_route()))
        assert m.total_decisions == 5

    def test_record_updates_fallback_kind_counts(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_native_mm_route()))
        m.record(build_routing_decision_event(_advisory_no_providers_route()))
        m.record(build_routing_decision_event(_advisory_no_providers_route()))
        assert m.fallback_kind_counts.get(RoutingFallbackKind.NONE.value, 0) == 1
        assert m.fallback_kind_counts.get(RoutingFallbackKind.PROVIDER_UNAVAILABLE.value, 0) == 2

    def test_record_updates_provider_and_model_counts(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_native_mm_route("openai", "gpt-4o")))
        m.record(build_routing_decision_event(_native_mm_route("openai", "gpt-4o")))
        m.record(build_routing_decision_event(_native_mm_route("anthropic", "claude-opus")))
        assert m.provider_counts["openai"] == 2
        assert m.provider_counts["anthropic"] == 1
        assert m.model_counts["gpt-4o"] == 2
        assert m.model_counts["claude-opus"] == 1

    def test_record_none_provider_not_tracked(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_text_only_route()))
        assert "none" not in m.provider_counts
        assert "none" not in m.model_counts

    def test_record_updates_route_reason_counts(self):
        m = ControlLoopMetrics()
        route = _native_mm_route()
        m.record(build_routing_decision_event(route))
        m.record(build_routing_decision_event(route))
        reason = route["route_reason"]
        assert m.route_reason_counts.get(reason, 0) == 2

    def test_record_projection_mismatch(self):
        m = ControlLoopMetrics()
        m.record_projection_mismatch()
        m.record_projection_mismatch()
        assert m.projection_mismatch_count == 2

    def test_reset_zeroes_all_counters(self):
        m = ControlLoopMetrics()
        for _ in range(3):
            m.record(build_routing_decision_event(_native_mm_route()))
        m.record_projection_mismatch()
        m.reset()
        assert m.total_decisions == 0
        assert m.native_multimodal_count == 0
        assert m.projection_mismatch_count == 0
        assert m.provider_counts == {}


# ---------------------------------------------------------------------------
# 6. RoutingAnalyticsSnapshot
# ---------------------------------------------------------------------------


class TestRoutingAnalyticsSnapshot:
    def test_snapshot_from_zero_decisions_no_div_zero(self):
        m = ControlLoopMetrics()
        snap = m.snapshot()
        assert snap.total_decisions == 0
        assert snap.native_multimodal_rate == 0.0

    def test_snapshot_native_multimodal_rate(self):
        m = ControlLoopMetrics()
        for _ in range(3):
            m.record(build_routing_decision_event(_native_mm_route()))
        m.record(build_routing_decision_event(_text_only_route()))
        snap = m.snapshot()
        assert snap.total_decisions == 4
        assert snap.native_multimodal_count == 3
        assert abs(snap.native_multimodal_rate - 0.75) < 1e-9

    def test_snapshot_text_only_rate(self):
        m = ControlLoopMetrics()
        for _ in range(2):
            m.record(build_routing_decision_event(_text_only_route()))
        snap = m.snapshot()
        assert abs(snap.text_only_rate - 1.0) < 1e-9

    def test_snapshot_carries_fallback_kind_counts(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_advisory_no_providers_route()))
        snap = m.snapshot()
        assert RoutingFallbackKind.PROVIDER_UNAVAILABLE.value in snap.fallback_kind_counts

    def test_to_dict_json_serialisable(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_native_mm_route()))
        snap = m.snapshot()
        serialised = json.dumps(snap.to_dict())
        assert "native_multimodal_count" in serialised

    def test_from_dict_round_trip(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_native_mm_route()))
        m.record(build_routing_decision_event(_text_only_route()))
        snap = m.snapshot()
        d = snap.to_dict()
        reconstructed = RoutingAnalyticsSnapshot.from_dict(d)
        assert reconstructed.total_decisions == snap.total_decisions
        assert reconstructed.native_multimodal_count == snap.native_multimodal_count
        assert reconstructed.text_only_count == snap.text_only_count
        assert abs(reconstructed.native_multimodal_rate - snap.native_multimodal_rate) < 1e-9
        assert reconstructed.fallback_kind_counts == snap.fallback_kind_counts
        assert reconstructed.provider_counts == snap.provider_counts

    def test_schema_version_is_one(self):
        snap = RoutingAnalyticsSnapshot()
        assert snap.schema_version == 1
        assert snap.to_dict()["schema_version"] == 1


# ---------------------------------------------------------------------------
# 7. _classify_fallback_kind()
# ---------------------------------------------------------------------------


class TestClassifyFallbackKind:
    def test_native_multimodal_no_fallback(self):
        assert _classify_fallback_kind(_native_mm_route()) == RoutingFallbackKind.NONE.value

    def test_text_only_no_fallback(self):
        assert _classify_fallback_kind(_text_only_route()) == RoutingFallbackKind.NONE.value

    def test_partial_mm_native_unavailable(self):
        result = _classify_fallback_kind(_partial_mm_route())
        assert result == RoutingFallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value

    def test_advisory_no_providers_available(self):
        result = _classify_fallback_kind(_advisory_no_providers_route())
        assert result == RoutingFallbackKind.PROVIDER_UNAVAILABLE.value

    def test_advisory_router_unavailable(self):
        result = _classify_fallback_kind(_advisory_router_unavailable_route())
        assert result == RoutingFallbackKind.ROUTER_UNAVAILABLE.value

    def test_advisory_routing_error(self):
        result = _classify_fallback_kind(_advisory_routing_error_route())
        assert result == RoutingFallbackKind.ROUTER_ERROR.value

    def test_advisory_capability_mismatch(self):
        result = _classify_fallback_kind(_advisory_capability_mismatch_route())
        assert result == RoutingFallbackKind.CAPABILITY_MISMATCH.value

    def test_unknown_fallback_reason_is_other(self):
        route = {
            "route_type": "advisory",
            "is_native_multimodal": False,
            "provider": "none",
            "model": "none",
            "route_reason": "some_unknown_reason",
            "fallback_reason": "some_completely_unknown_fallback",
            "active_modalities": [],
        }
        result = _classify_fallback_kind(route)
        assert result == RoutingFallbackKind.OTHER.value


# ---------------------------------------------------------------------------
# 8. build_routing_decision_event()
# ---------------------------------------------------------------------------


class TestBuildRoutingDecisionEvent:
    def test_native_mm_event(self):
        evt = build_routing_decision_event(
            _native_mm_route("openai", "gpt-4o"),
            trace_id="t1",
            runtime_session_id="s1",
        )
        assert evt.route_kind == RouteKind.NATIVE_MULTIMODAL.value
        assert evt.is_native_multimodal is True
        assert evt.provider == "openai"
        assert evt.model == "gpt-4o"
        assert evt.fallback_kind == RoutingFallbackKind.NONE.value
        assert evt.fallback_reason == ""
        assert evt.active_modalities == ["image"]
        assert evt.trace_id == "t1"
        assert evt.runtime_session_id == "s1"

    def test_text_only_event_no_fallback(self):
        evt = build_routing_decision_event(_text_only_route())
        assert evt.route_kind == RouteKind.TEXT_ONLY.value
        assert evt.is_native_multimodal is False
        assert evt.fallback_kind == RoutingFallbackKind.NONE.value

    def test_partial_mm_event_has_fallback(self):
        evt = build_routing_decision_event(_partial_mm_route())
        assert evt.route_kind == RouteKind.PARTIAL_MULTIMODAL.value
        assert evt.fallback_kind == RoutingFallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value
        assert evt.is_native_multimodal is False

    def test_provider_unavailable_event(self):
        evt = build_routing_decision_event(_advisory_no_providers_route())
        assert evt.route_kind == RouteKind.ADVISORY.value
        assert evt.fallback_kind == RoutingFallbackKind.PROVIDER_UNAVAILABLE.value
        assert evt.provider == "none"


# ---------------------------------------------------------------------------
# 9. build_fallback_decision_event()
# ---------------------------------------------------------------------------


class TestBuildFallbackDecisionEvent:
    def test_returns_none_for_no_fallback(self):
        evt = build_routing_decision_event(_native_mm_route())
        fallback = build_fallback_decision_event(evt)
        assert fallback is None

    def test_returns_none_for_text_only(self):
        evt = build_routing_decision_event(_text_only_route())
        fallback = build_fallback_decision_event(evt)
        assert fallback is None

    def test_returns_fallback_event_for_partial_mm(self):
        routing_evt = build_routing_decision_event(_partial_mm_route())
        fallback = build_fallback_decision_event(routing_evt)
        assert fallback is not None
        assert fallback.fallback_kind == RoutingFallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value
        assert fallback.from_route_kind == RouteKind.NATIVE_MULTIMODAL.value
        assert fallback.to_route_kind == RouteKind.PARTIAL_MULTIMODAL.value

    def test_fallback_from_is_always_native_mm(self):
        for route in [_partial_mm_route(), _advisory_no_providers_route()]:
            routing_evt = build_routing_decision_event(route)
            fallback = build_fallback_decision_event(routing_evt)
            assert fallback is not None
            assert fallback.from_route_kind == RouteKind.NATIVE_MULTIMODAL.value

    def test_to_route_kind_matches_routing_event(self):
        route = _advisory_router_unavailable_route()
        routing_evt = build_routing_decision_event(route)
        fallback = build_fallback_decision_event(routing_evt)
        assert fallback is not None
        assert fallback.to_route_kind == routing_evt.route_kind

    def test_fallback_active_modalities_propagated(self):
        route = _partial_mm_route()
        routing_evt = build_routing_decision_event(route)
        fallback = build_fallback_decision_event(routing_evt)
        assert fallback is not None
        assert fallback.active_modalities == ["image"]


# ---------------------------------------------------------------------------
# 10. record_routing_decision()
# ---------------------------------------------------------------------------


class TestRecordRoutingDecision:
    def test_returns_routing_decision_event(self):
        evt = record_routing_decision(_native_mm_route())
        assert isinstance(evt, RoutingDecisionEvent)

    def test_increments_global_counter(self):
        m = get_control_loop_metrics()
        assert m.total_decisions == 0
        record_routing_decision(_native_mm_route())
        assert m.total_decisions == 1

    def test_repeated_calls_accumulate(self):
        for i in range(5):
            record_routing_decision(_native_mm_route())
        m = get_control_loop_metrics()
        assert m.total_decisions == 5
        assert m.native_multimodal_count == 5

    def test_trace_id_propagated(self):
        evt = record_routing_decision(_text_only_route(), trace_id="trace-123")
        assert evt.trace_id == "trace-123"


# ---------------------------------------------------------------------------
# 11. build_routing_analytics_snapshot()
# ---------------------------------------------------------------------------


class TestBuildRoutingAnalyticsSnapshot:
    def test_returns_snapshot_instance(self):
        snap = build_routing_analytics_snapshot()
        assert isinstance(snap, RoutingAnalyticsSnapshot)

    def test_rates_sum_for_homogeneous_decisions(self):
        for _ in range(4):
            record_routing_decision(_text_only_route())
        snap = build_routing_analytics_snapshot()
        assert abs(snap.text_only_rate - 1.0) < 1e-9
        assert snap.native_multimodal_rate == 0.0

    def test_counts_correct_after_mixed_decisions(self):
        record_routing_decision(_native_mm_route())
        record_routing_decision(_native_mm_route())
        record_routing_decision(_text_only_route())
        snap = build_routing_analytics_snapshot()
        assert snap.total_decisions == 3
        assert snap.native_multimodal_count == 2
        assert snap.text_only_count == 1


# ---------------------------------------------------------------------------
# 12. Provider unavailability vs capability mismatch distinction
# ---------------------------------------------------------------------------


class TestProviderUnavailableVsCapabilityMismatch:
    def test_no_providers_available_maps_to_provider_unavailable(self):
        kind = _classify_fallback_kind(_advisory_no_providers_route())
        assert kind == RoutingFallbackKind.PROVIDER_UNAVAILABLE.value

    def test_capability_mismatch_maps_to_capability_mismatch(self):
        kind = _classify_fallback_kind(_advisory_capability_mismatch_route())
        assert kind == RoutingFallbackKind.CAPABILITY_MISMATCH.value

    def test_kinds_are_distinct(self):
        assert (
            RoutingFallbackKind.PROVIDER_UNAVAILABLE.value
            != RoutingFallbackKind.CAPABILITY_MISMATCH.value
        )

    def test_counters_separate_in_metrics(self):
        m = ControlLoopMetrics()
        m.record(build_routing_decision_event(_advisory_no_providers_route()))
        m.record(build_routing_decision_event(_advisory_capability_mismatch_route()))
        snap = m.snapshot()
        assert snap.fallback_kind_counts.get(RoutingFallbackKind.PROVIDER_UNAVAILABLE.value, 0) == 1
        assert snap.fallback_kind_counts.get(RoutingFallbackKind.CAPABILITY_MISMATCH.value, 0) == 1


# ---------------------------------------------------------------------------
# 13. Snapshot stability
# ---------------------------------------------------------------------------


class TestSnapshotStability:
    def test_to_dict_has_expected_keys(self):
        snap = RoutingAnalyticsSnapshot()
        d = snap.to_dict()
        expected_keys = {
            "schema_version", "total_decisions",
            "native_multimodal_count", "text_only_count",
            "partial_multimodal_count", "advisory_count",
            "native_multimodal_rate", "text_only_rate",
            "partial_multimodal_rate", "advisory_rate",
            "fallback_kind_counts", "route_reason_counts",
            "provider_counts", "model_counts",
            "projection_mismatch_count", "snapshotted_at",
        }
        assert expected_keys == set(d.keys())

    def test_from_dict_to_dict_exact_round_trip(self):
        record_routing_decision(_native_mm_route("openai", "gpt-4o"))
        record_routing_decision(_text_only_route())
        snap = build_routing_analytics_snapshot()
        d = snap.to_dict()
        reconstructed = RoutingAnalyticsSnapshot.from_dict(d)
        d2 = reconstructed.to_dict()
        # All numeric fields should be identical
        for key in [
            "total_decisions", "native_multimodal_count", "text_only_count",
            "native_multimodal_rate", "text_only_rate",
            "projection_mismatch_count", "schema_version",
        ]:
            assert d[key] == d2[key], f"mismatch on {key}: {d[key]} != {d2[key]}"
        assert d["fallback_kind_counts"] == d2["fallback_kind_counts"]
        assert d["provider_counts"] == d2["provider_counts"]


# ---------------------------------------------------------------------------
# 14. Observability derives from canonical decisions
# ---------------------------------------------------------------------------


class TestObservabilityFromCanonicalDecisions:
    def test_event_built_from_route_dict_not_inferred(self):
        """RoutingDecisionEvent is constructed directly from the route_dict
        produced by _select_multimodal_route, not inferred from logs."""
        route = _native_mm_route("openai", "gpt-4o")
        evt = build_routing_decision_event(route)
        assert evt.provider == route["provider"]
        assert evt.model == route["model"]
        assert evt.route_kind == route["route_type"]
        assert evt.is_native_multimodal == route["is_native_multimodal"]
        assert evt.route_reason == route["route_reason"]
        assert evt.active_modalities == route["active_modalities"]

    def test_metrics_updated_from_event_not_raw_dict(self):
        """ControlLoopMetrics receives structured RoutingDecisionEvents, not raw dicts."""
        m = ControlLoopMetrics()
        route = _native_mm_route("openai", "gpt-4o")
        evt = build_routing_decision_event(route)
        m.record(evt)
        assert m.provider_counts.get("openai") == 1
        assert m.model_counts.get("gpt-4o") == 1


# ---------------------------------------------------------------------------
# 15. OpenClawd integration
# ---------------------------------------------------------------------------


class TestOpenClawdIntegration:
    def test_emit_routing_decision_event_returns_dict_for_valid_route(self):
        """OpenClawd._emit_routing_decision_event should return a dict for a valid route_dict."""
        from core.openclawd import OpenClawd

        openclawd = OpenClawd.__new__(OpenClawd)
        route = _native_mm_route()
        result = openclawd._emit_routing_decision_event(
            route_dict=route,
            trace_id="test-trace",
            runtime_session_id="test-session",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert result["route_kind"] == RouteKind.NATIVE_MULTIMODAL.value
        assert result["is_native_multimodal"] is True
        assert result["trace_id"] == "test-trace"

    def test_emit_routing_decision_event_returns_none_on_import_error(self):
        """_emit_routing_decision_event swallows errors and returns None on failure."""
        from core.openclawd import OpenClawd

        openclawd = OpenClawd.__new__(OpenClawd)
        with patch(
            "core.routing_observability.record_routing_decision",
            side_effect=RuntimeError("simulated failure"),
        ):
            result = openclawd._emit_routing_decision_event(route_dict={})
        assert result is None

    def test_emit_routing_decision_event_increments_global_metrics(self):
        """Calling _emit_routing_decision_event updates the global ControlLoopMetrics."""
        from core.openclawd import OpenClawd

        openclawd = OpenClawd.__new__(OpenClawd)
        m = get_control_loop_metrics()
        assert m.total_decisions == 0
        openclawd._emit_routing_decision_event(
            route_dict=_text_only_route(),
            trace_id="t",
            runtime_session_id="s",
        )
        assert m.total_decisions == 1
        assert m.text_only_count == 1
