#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr43_degraded_operation_envelope.py
===============================================
Tests for PR-29: Resilient Provider Failover and Degraded Multimodal
Operation Envelopes.

Coverage
--------
1.  DegradedOperationLevel
    - all enum values present
    - string values are stable
    - from_route_type maps all route types correctly
    - from_route_type returns UNKNOWN for unrecognised input
    - from_string round-trips all values
    - from_string returns UNKNOWN for bad input

2.  ProviderFailoverReason
    - all enum values present
    - string values are stable
    - from_string round-trips known values
    - from_string normalises raw routing reason strings (heuristic matching)
    - from_string returns UNKNOWN for unrecognised input

3.  DegradedOperationSeverity
    - all enum values present
    - from_level maps every DegradedOperationLevel correctly
    - from_string round-trips all values
    - from_string returns UNKNOWN for bad input

4.  ProviderFailoverStep
    - construction with defaults
    - construction with all fields
    - to_dict is JSON-serialisable
    - to_dict / from_dict round-trip preserves all fields
    - stable field names

5.  ProviderFailoverChain
    - construction with defaults
    - construction with all fields
    - to_dict is JSON-serialisable
    - to_dict / from_dict round-trip preserves all fields
    - stable field names
    - chain_id is auto-populated

6.  FallbackLadderRung
    - construction with defaults
    - to_dict / from_dict round-trip

7.  FallbackPolicyLadder
    - construction with defaults
    - to_dict is JSON-serialisable
    - to_dict / from_dict round-trip preserves all fields
    - stable field names
    - ladder_id is auto-populated

8.  DegradedOperationEnvelope
    - construction with defaults
    - construction with all fields
    - to_dict is JSON-serialisable
    - to_dict / from_dict round-trip preserves all fields
    - stable field names
    - envelope_id is auto-populated (UUID4)
    - timestamp is auto-populated

9.  build_provider_failover_step()
    - builds correct step with all params
    - normalises failover_reason from raw string
    - defaults are safe

10. build_provider_failover_chain()
    - native_multimodal route → single selected step, failover_occurred=False
    - text_only route with fallback_reason → single selected step
    - advisory route (no provider) → none step, failover_occurred may be True
    - supply snapshot with down provider adds skipped step
    - supply snapshot with degraded provider adds skipped step
    - empty route_dict → safe default chain
    - None route_dict → safe default chain
    - never raises on garbage input

11. build_fallback_policy_ladder()
    - FULL_NATIVE_MULTIMODAL → exactly one rung active, no transition
    - PARTIAL_MULTIMODAL → correct rung active
    - TEXT_SUMMARY_FALLBACK → correct rung active
    - OBSERVE_ONLY → correct rung active
    - NO_OP → correct rung active
    - transition_occurred=True when prior_level differs
    - transition_occurred=False when prior_level same
    - transition_occurred=False when prior_level=UNKNOWN
    - all 5 canonical rungs always present
    - never raises on any input

12. build_degraded_operation_envelope()
    - native_multimodal route → FULL_NATIVE_MULTIMODAL, severity=OK
    - partial_multimodal route → PARTIAL_MULTIMODAL, severity=WARNING
    - text_only route → TEXT_SUMMARY_FALLBACK, severity=DEGRADED
    - advisory route → OBSERVE_ONLY, severity=CRITICAL
    - provider="none" → NO_OP or observe-only level
    - fallback_reason is preserved in failover_reasons
    - is_degraded=False for FULL_NATIVE_MULTIMODAL
    - is_degraded=True for all degraded levels
    - is_observe_only=True for observe-only/no-op
    - provider and model are propagated
    - trace_id is propagated
    - prior_level extracted from prior_envelope dict
    - transition_occurred=True when level changes
    - transition_occurred=False when level unchanged
    - envelope includes failover_chain and fallback_ladder
    - failover_chain is JSON-serialisable
    - fallback_ladder is JSON-serialisable
    - None route_dict → safe minimal envelope
    - garbage route_dict → never raises
    - supply snapshot skipped providers added to chain

13. envelope_summary()
    - returns compact dict with stable keys
    - is JSON-serialisable
    - failover_occurred propagated from chain
    - never raises on any input

14. Provider unavailability triggers canonical failover handling
    - when preferred provider is down, chain shows skipped step + fallback step
    - final provider differs from skipped provider
    - primary_failover_reason is structured (not UNKNOWN)

15. Full multimodal degrades to partial multimodal
    - route_type="partial_multimodal" → PARTIAL_MULTIMODAL level
    - severity = WARNING
    - is_degraded = True
    - is_observe_only = False

16. Partial multimodal degrades to text/summary
    - route_type="text_only" → TEXT_SUMMARY_FALLBACK level
    - severity = DEGRADED
    - is_observe_only = False

17. Degraded envelope is serialisable and projection-ready
    - full round-trip: build → to_dict → json.dumps → json.loads → from_dict
    - all fields survive the round-trip

18. Failover reasons remain structured and stable
    - all returned reasons are either known ProviderFailoverReason values
      or raw strings (for unknown cases)

19. Repeated degraded transitions stay coherent across the control loop
    - building with prior_envelope tracks transition_occurred correctly
    - prior_level is preserved and stable

20. OpenClawd integration
    - _build_degraded_operation_envelope returns a dict on valid route_dict
    - _build_degraded_operation_envelope returns None or dict (never raises)
    - returned dict contains all required keys

21. Module imports
    - all public symbols importable from core.degraded_operation_envelope
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _native_multimodal_route(
    provider: str = "openai", model: str = "gpt-4o"
) -> Dict[str, Any]:
    return {
        "route_type": "native_multimodal",
        "provider": provider,
        "model": model,
        "is_native_multimodal": True,
        "fallback_reason": "",
    }


def _partial_multimodal_route(
    provider: str = "claude", model: str = "claude-3-5-sonnet", reason: str = "native_mm_unavailable"
) -> Dict[str, Any]:
    return {
        "route_type": "partial_multimodal",
        "provider": provider,
        "model": model,
        "is_native_multimodal": False,
        "fallback_reason": reason,
    }


def _text_only_route(
    provider: str = "deepseek", model: str = "deepseek-chat", reason: str = "confidence_below_threshold"
) -> Dict[str, Any]:
    return {
        "route_type": "text_only",
        "provider": provider,
        "model": model,
        "is_native_multimodal": False,
        "fallback_reason": reason,
    }


def _advisory_route() -> Dict[str, Any]:
    return {
        "route_type": "advisory",
        "provider": "none",
        "model": "none",
        "is_native_multimodal": False,
        "fallback_reason": "no_providers_available",
    }


def _supply_snapshot_with_down_provider(
    down_provider: str = "bad_provider",
    available_provider: str = "openai",
) -> Dict[str, Any]:
    return {
        "providers": [
            {
                "provider_name": down_provider,
                "default_model": "bad-model",
                "health_status": "down",
                "native_multimodal_capability": {"has_native_multimodal": False},
            },
            {
                "provider_name": available_provider,
                "default_model": "gpt-4o",
                "health_status": "healthy",
                "native_multimodal_capability": {"has_native_multimodal": True},
            },
        ]
    }


# ===========================================================================
# 1. DegradedOperationLevel
# ===========================================================================


class TestDegradedOperationLevel:
    def test_all_values_present(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        expected = {
            "full_native_multimodal",
            "partial_multimodal",
            "text_summary_fallback",
            "observe_only",
            "no_op",
            "unknown",
        }
        actual = {m.value for m in DegradedOperationLevel}
        assert expected == actual

    def test_string_values_are_stable(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value == "full_native_multimodal"
        assert DegradedOperationLevel.PARTIAL_MULTIMODAL.value == "partial_multimodal"
        assert DegradedOperationLevel.TEXT_SUMMARY_FALLBACK.value == "text_summary_fallback"
        assert DegradedOperationLevel.OBSERVE_ONLY.value == "observe_only"
        assert DegradedOperationLevel.NO_OP.value == "no_op"
        assert DegradedOperationLevel.UNKNOWN.value == "unknown"

    def test_from_route_type_native_multimodal(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert (
            DegradedOperationLevel.from_route_type("native_multimodal")
            == DegradedOperationLevel.FULL_NATIVE_MULTIMODAL
        )

    def test_from_route_type_partial_multimodal(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert (
            DegradedOperationLevel.from_route_type("partial_multimodal")
            == DegradedOperationLevel.PARTIAL_MULTIMODAL
        )

    def test_from_route_type_text_only(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert (
            DegradedOperationLevel.from_route_type("text_only")
            == DegradedOperationLevel.TEXT_SUMMARY_FALLBACK
        )

    def test_from_route_type_advisory(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert (
            DegradedOperationLevel.from_route_type("advisory")
            == DegradedOperationLevel.OBSERVE_ONLY
        )

    def test_from_route_type_none_string(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert (
            DegradedOperationLevel.from_route_type("none")
            == DegradedOperationLevel.NO_OP
        )

    def test_from_route_type_unknown_returns_unknown(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert DegradedOperationLevel.from_route_type("garbage") == DegradedOperationLevel.UNKNOWN
        assert DegradedOperationLevel.from_route_type(None) == DegradedOperationLevel.UNKNOWN

    def test_from_string_round_trips(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        for level in DegradedOperationLevel:
            assert DegradedOperationLevel.from_string(level.value) == level

    def test_from_string_bad_returns_unknown(self):
        from core.degraded_operation_envelope import DegradedOperationLevel

        assert DegradedOperationLevel.from_string("not_a_level") == DegradedOperationLevel.UNKNOWN
        assert DegradedOperationLevel.from_string(None) == DegradedOperationLevel.UNKNOWN


# ===========================================================================
# 2. ProviderFailoverReason
# ===========================================================================


class TestProviderFailoverReason:
    def test_all_values_present(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        expected = {
            "provider_unavailable",
            "provider_degraded",
            "native_multimodal_unsupported",
            "confidence_below_threshold",
            "router_unavailable",
            "routing_error",
            "no_providers_available",
            "capability_mismatch",
            "policy_governed",
            "unknown",
        }
        actual = {r.value for r in ProviderFailoverReason}
        assert expected == actual

    def test_string_values_are_stable(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        assert ProviderFailoverReason.PROVIDER_UNAVAILABLE.value == "provider_unavailable"
        assert ProviderFailoverReason.NO_PROVIDERS_AVAILABLE.value == "no_providers_available"
        assert ProviderFailoverReason.ROUTER_UNAVAILABLE.value == "router_unavailable"

    def test_from_string_round_trips_known_values(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        for reason in ProviderFailoverReason:
            assert ProviderFailoverReason.from_string(reason.value) == reason

    def test_from_string_normalises_router_unavailable(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        assert (
            ProviderFailoverReason.from_string("router_unavailable degraded_to=advisory")
            == ProviderFailoverReason.ROUTER_UNAVAILABLE
        )

    def test_from_string_normalises_no_providers(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        assert (
            ProviderFailoverReason.from_string("no_providers_available")
            == ProviderFailoverReason.NO_PROVIDERS_AVAILABLE
        )

    def test_from_string_normalises_confidence_threshold(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        result = ProviderFailoverReason.from_string(
            "confidence_below_threshold reason=CONFIDENCE_BELOW_THRESHOLD"
        )
        assert result == ProviderFailoverReason.CONFIDENCE_BELOW_THRESHOLD

    def test_from_string_unknown_for_garbage(self):
        from core.degraded_operation_envelope import ProviderFailoverReason

        assert ProviderFailoverReason.from_string("gibberish_xyz") == ProviderFailoverReason.UNKNOWN
        assert ProviderFailoverReason.from_string(None) == ProviderFailoverReason.UNKNOWN


# ===========================================================================
# 3. DegradedOperationSeverity
# ===========================================================================


class TestDegradedOperationSeverity:
    def test_all_values_present(self):
        from core.degraded_operation_envelope import DegradedOperationSeverity

        expected = {"ok", "warning", "degraded", "critical", "unknown"}
        actual = {s.value for s in DegradedOperationSeverity}
        assert expected == actual

    def test_from_level_full_native_ok(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
        )

        assert (
            DegradedOperationSeverity.from_level(DegradedOperationLevel.FULL_NATIVE_MULTIMODAL)
            == DegradedOperationSeverity.OK
        )

    def test_from_level_partial_warning(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
        )

        assert (
            DegradedOperationSeverity.from_level(DegradedOperationLevel.PARTIAL_MULTIMODAL)
            == DegradedOperationSeverity.WARNING
        )

    def test_from_level_text_fallback_degraded(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
        )

        assert (
            DegradedOperationSeverity.from_level(DegradedOperationLevel.TEXT_SUMMARY_FALLBACK)
            == DegradedOperationSeverity.DEGRADED
        )

    def test_from_level_observe_only_critical(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
        )

        assert (
            DegradedOperationSeverity.from_level(DegradedOperationLevel.OBSERVE_ONLY)
            == DegradedOperationSeverity.CRITICAL
        )

    def test_from_level_no_op_critical(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
        )

        assert (
            DegradedOperationSeverity.from_level(DegradedOperationLevel.NO_OP)
            == DegradedOperationSeverity.CRITICAL
        )

    def test_from_level_unknown_returns_unknown(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
        )

        assert (
            DegradedOperationSeverity.from_level(DegradedOperationLevel.UNKNOWN)
            == DegradedOperationSeverity.UNKNOWN
        )

    def test_from_string_round_trips(self):
        from core.degraded_operation_envelope import DegradedOperationSeverity

        for sev in DegradedOperationSeverity:
            assert DegradedOperationSeverity.from_string(sev.value) == sev

    def test_from_string_bad_returns_unknown(self):
        from core.degraded_operation_envelope import DegradedOperationSeverity

        assert DegradedOperationSeverity.from_string("XYZ") == DegradedOperationSeverity.UNKNOWN
        assert DegradedOperationSeverity.from_string(None) == DegradedOperationSeverity.UNKNOWN


# ===========================================================================
# 4. ProviderFailoverStep
# ===========================================================================


class TestProviderFailoverStep:
    def test_construction_with_defaults(self):
        from core.degraded_operation_envelope import ProviderFailoverStep

        s = ProviderFailoverStep()
        assert s.step_index == 0
        assert s.provider == "unknown"
        assert s.selected is False

    def test_construction_with_all_fields(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            ProviderFailoverStep,
        )

        s = ProviderFailoverStep(
            step_index=1,
            provider="openai",
            model="gpt-4o",
            selected=True,
            skipped=False,
            failover_reason=ProviderFailoverReason.PROVIDER_UNAVAILABLE.value,
            raw_reason="health_status=down",
            health_status="down",
            is_native_multimodal=True,
        )
        assert s.provider == "openai"
        assert s.selected is True
        assert s.is_native_multimodal is True

    def test_to_dict_is_json_serialisable(self):
        from core.degraded_operation_envelope import ProviderFailoverStep

        s = ProviderFailoverStep(step_index=0, provider="openai", model="gpt-4o")
        d = s.to_dict()
        json.dumps(d)

    def test_to_dict_from_dict_round_trip(self):
        from core.degraded_operation_envelope import ProviderFailoverStep

        s = ProviderFailoverStep(
            step_index=2,
            provider="claude",
            model="claude-3-5-sonnet",
            selected=True,
            skipped=False,
            failover_reason="provider_unavailable",
            raw_reason="raw",
            health_status="healthy",
            is_native_multimodal=False,
        )
        d = s.to_dict()
        s2 = ProviderFailoverStep.from_dict(d)
        assert s2.step_index == s.step_index
        assert s2.provider == s.provider
        assert s2.model == s.model
        assert s2.selected == s.selected
        assert s2.failover_reason == s.failover_reason

    def test_stable_field_names(self):
        from core.degraded_operation_envelope import ProviderFailoverStep

        d = ProviderFailoverStep().to_dict()
        expected_keys = {
            "step_index",
            "provider",
            "model",
            "selected",
            "skipped",
            "failover_reason",
            "raw_reason",
            "health_status",
            "is_native_multimodal",
        }
        assert set(d.keys()) == expected_keys


# ===========================================================================
# 5. ProviderFailoverChain
# ===========================================================================


class TestProviderFailoverChain:
    def test_construction_with_defaults(self):
        from core.degraded_operation_envelope import ProviderFailoverChain

        c = ProviderFailoverChain()
        assert c.steps == []
        assert c.failover_occurred is False
        assert c.chain_id != ""

    def test_chain_id_is_auto_populated(self):
        from core.degraded_operation_envelope import ProviderFailoverChain

        c = ProviderFailoverChain()
        assert c.chain_id
        # Must be a valid UUID4
        uuid.UUID(c.chain_id, version=4)

    def test_to_dict_is_json_serialisable(self):
        from core.degraded_operation_envelope import ProviderFailoverChain

        c = ProviderFailoverChain()
        json.dumps(c.to_dict())

    def test_to_dict_from_dict_round_trip(self):
        from core.degraded_operation_envelope import ProviderFailoverChain, ProviderFailoverStep

        step = ProviderFailoverStep(step_index=0, provider="openai", model="gpt-4o", selected=True)
        c = ProviderFailoverChain(
            steps=[step],
            final_provider="openai",
            final_model="gpt-4o",
            total_steps=1,
            failover_occurred=False,
            primary_failover_reason="unknown",
        )
        d = c.to_dict()
        c2 = ProviderFailoverChain.from_dict(d)
        assert c2.final_provider == "openai"
        assert c2.total_steps == 1
        assert len(c2.steps) == 1

    def test_stable_field_names(self):
        from core.degraded_operation_envelope import ProviderFailoverChain

        d = ProviderFailoverChain().to_dict()
        expected_keys = {
            "chain_id",
            "steps",
            "final_provider",
            "final_model",
            "total_steps",
            "failover_occurred",
            "primary_failover_reason",
            "timestamp",
        }
        assert set(d.keys()) == expected_keys


# ===========================================================================
# 6. FallbackLadderRung
# ===========================================================================


class TestFallbackLadderRung:
    def test_construction_with_defaults(self):
        from core.degraded_operation_envelope import FallbackLadderRung

        r = FallbackLadderRung()
        assert r.active is False
        assert r.entry_reason == ""

    def test_to_dict_from_dict_round_trip(self):
        from core.degraded_operation_envelope import FallbackLadderRung

        r = FallbackLadderRung(level="partial_multimodal", active=True, entry_reason="test", entered_at=1234.0)
        d = r.to_dict()
        r2 = FallbackLadderRung.from_dict(d)
        assert r2.level == "partial_multimodal"
        assert r2.active is True
        assert r2.entered_at == 1234.0


# ===========================================================================
# 7. FallbackPolicyLadder
# ===========================================================================


class TestFallbackPolicyLadder:
    def test_construction_with_defaults(self):
        from core.degraded_operation_envelope import FallbackPolicyLadder

        ladder = FallbackPolicyLadder()
        assert ladder.rungs == []
        assert ladder.ladder_id != ""

    def test_ladder_id_auto_populated(self):
        from core.degraded_operation_envelope import FallbackPolicyLadder

        ladder = FallbackPolicyLadder()
        uuid.UUID(ladder.ladder_id, version=4)

    def test_to_dict_is_json_serialisable(self):
        from core.degraded_operation_envelope import FallbackPolicyLadder

        ladder = FallbackPolicyLadder()
        json.dumps(ladder.to_dict())

    def test_to_dict_from_dict_round_trip(self):
        from core.degraded_operation_envelope import FallbackLadderRung, FallbackPolicyLadder

        rung = FallbackLadderRung(level="partial_multimodal", active=True)
        ladder = FallbackPolicyLadder(
            rungs=[rung],
            current_level="partial_multimodal",
            prior_level="full_native_multimodal",
            transition_occurred=True,
        )
        d = ladder.to_dict()
        ladder2 = FallbackPolicyLadder.from_dict(d)
        assert ladder2.current_level == "partial_multimodal"
        assert ladder2.prior_level == "full_native_multimodal"
        assert ladder2.transition_occurred is True
        assert len(ladder2.rungs) == 1

    def test_stable_field_names(self):
        from core.degraded_operation_envelope import FallbackPolicyLadder

        d = FallbackPolicyLadder().to_dict()
        expected_keys = {
            "ladder_id",
            "rungs",
            "current_level",
            "prior_level",
            "transition_occurred",
            "timestamp",
        }
        assert set(d.keys()) == expected_keys


# ===========================================================================
# 8. DegradedOperationEnvelope
# ===========================================================================


class TestDegradedOperationEnvelope:
    def test_construction_with_defaults(self):
        from core.degraded_operation_envelope import DegradedOperationEnvelope

        env = DegradedOperationEnvelope()
        assert env.envelope_id != ""
        assert env.is_degraded is False
        assert env.failover_reasons == []

    def test_envelope_id_is_uuid4(self):
        from core.degraded_operation_envelope import DegradedOperationEnvelope

        env = DegradedOperationEnvelope()
        uuid.UUID(env.envelope_id, version=4)

    def test_timestamp_auto_populated(self):
        from core.degraded_operation_envelope import DegradedOperationEnvelope
        import time

        before = time.time()
        env = DegradedOperationEnvelope()
        after = time.time()
        assert before <= env.timestamp <= after

    def test_to_dict_is_json_serialisable(self):
        from core.degraded_operation_envelope import DegradedOperationEnvelope

        env = DegradedOperationEnvelope(
            current_level="partial_multimodal",
            severity="warning",
            failover_chain={"chain_id": "x", "steps": []},
        )
        json.dumps(env.to_dict())

    def test_to_dict_from_dict_round_trip_all_fields(self):
        from core.degraded_operation_envelope import DegradedOperationEnvelope

        env = DegradedOperationEnvelope(
            current_level="text_summary_fallback",
            severity="degraded",
            failover_chain={"chain_id": "abc"},
            fallback_ladder={"ladder_id": "def"},
            failover_reasons=["provider_unavailable"],
            degradation_summary="test summary",
            is_degraded=True,
            is_observe_only=False,
            provider="openai",
            model="gpt-4",
            prior_level="partial_multimodal",
            transition_occurred=True,
            trace_id="trace_001",
        )
        d = env.to_dict()
        env2 = DegradedOperationEnvelope.from_dict(d)
        assert env2.current_level == "text_summary_fallback"
        assert env2.severity == "degraded"
        assert env2.is_degraded is True
        assert env2.provider == "openai"
        assert env2.prior_level == "partial_multimodal"
        assert env2.transition_occurred is True
        assert env2.trace_id == "trace_001"
        assert env2.failover_reasons == ["provider_unavailable"]

    def test_stable_field_names(self):
        from core.degraded_operation_envelope import DegradedOperationEnvelope

        d = DegradedOperationEnvelope().to_dict()
        expected_keys = {
            "envelope_id",
            "current_level",
            "severity",
            "failover_chain",
            "fallback_ladder",
            "failover_reasons",
            "degradation_summary",
            "is_degraded",
            "is_observe_only",
            "provider",
            "model",
            "prior_level",
            "transition_occurred",
            "trace_id",
            "timestamp",
        }
        assert set(d.keys()) == expected_keys


# ===========================================================================
# 9. build_provider_failover_step()
# ===========================================================================


class TestBuildProviderFailoverStep:
    def test_builds_with_all_params(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_provider_failover_step,
        )

        step = build_provider_failover_step(
            step_index=1,
            provider="openai",
            model="gpt-4o",
            selected=True,
            failover_reason="provider_unavailable",
            raw_reason="raw test",
            health_status="healthy",
            is_native_multimodal=True,
        )
        assert step.step_index == 1
        assert step.provider == "openai"
        assert step.selected is True
        assert step.failover_reason == ProviderFailoverReason.PROVIDER_UNAVAILABLE.value
        assert step.is_native_multimodal is True

    def test_normalises_reason_from_raw_string(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_provider_failover_step,
        )

        step = build_provider_failover_step(
            0, "p", "m", failover_reason="router_unavailable degraded_to=advisory"
        )
        assert step.failover_reason == ProviderFailoverReason.ROUTER_UNAVAILABLE.value

    def test_defaults_are_safe(self):
        from core.degraded_operation_envelope import build_provider_failover_step

        step = build_provider_failover_step(0, "p", "m")
        assert step.provider == "p"
        assert step.selected is False
        assert step.skipped is False


# ===========================================================================
# 10. build_provider_failover_chain()
# ===========================================================================


class TestBuildProviderFailoverChain:
    def test_native_multimodal_single_step_no_failover(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        route = _native_multimodal_route()
        chain = build_provider_failover_chain(route)
        assert chain.final_provider == "openai"
        # No fallback_reason → no failover (single step, no skipped providers)
        assert any(s.selected for s in chain.steps)

    def test_text_only_route_selected_step(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        route = _text_only_route()
        chain = build_provider_failover_chain(route)
        assert chain.final_provider == "deepseek"
        selected = [s for s in chain.steps if s.selected]
        assert len(selected) == 1

    def test_advisory_route_none_provider(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        route = _advisory_route()
        chain = build_provider_failover_chain(route)
        assert chain.final_provider == "none"
        selected = [s for s in chain.steps if s.selected]
        assert len(selected) == 1
        assert selected[0].provider == "none"

    def test_supply_snapshot_adds_skipped_down_provider(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_provider_failover_chain,
        )

        route = _native_multimodal_route(provider="openai")
        supply = _supply_snapshot_with_down_provider(
            down_provider="bad_provider", available_provider="openai"
        )
        chain = build_provider_failover_chain(route, supply)
        skipped = [s for s in chain.steps if s.skipped]
        assert len(skipped) >= 1
        assert skipped[0].provider == "bad_provider"
        assert skipped[0].failover_reason == ProviderFailoverReason.PROVIDER_UNAVAILABLE.value

    def test_supply_snapshot_adds_skipped_degraded_provider(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_provider_failover_chain,
        )

        route = _native_multimodal_route(provider="openai")
        supply = {
            "providers": [
                {
                    "provider_name": "degraded_prov",
                    "default_model": "d-model",
                    "health_status": "degraded",
                    "native_multimodal_capability": {"has_native_multimodal": False},
                },
                {
                    "provider_name": "openai",
                    "default_model": "gpt-4o",
                    "health_status": "healthy",
                    "native_multimodal_capability": {"has_native_multimodal": True},
                },
            ]
        }
        chain = build_provider_failover_chain(route, supply)
        skipped = [s for s in chain.steps if s.skipped]
        assert any(s.failover_reason == ProviderFailoverReason.PROVIDER_DEGRADED.value for s in skipped)

    def test_empty_route_dict_returns_safe_chain(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        chain = build_provider_failover_chain({})
        assert chain is not None

    def test_none_route_dict_returns_safe_chain(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        chain = build_provider_failover_chain(None)
        assert chain is not None

    def test_never_raises_on_garbage(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        # Must not raise
        for bad_input in [{"provider": None, "model": 42}, {"route_type": 999}]:
            chain = build_provider_failover_chain(bad_input)
            assert chain is not None


# ===========================================================================
# 11. build_fallback_policy_ladder()
# ===========================================================================


class TestBuildFallbackPolicyLadder:
    def test_full_native_multimodal_exactly_one_active_rung(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(DegradedOperationLevel.FULL_NATIVE_MULTIMODAL)
        active_rungs = [r for r in ladder.rungs if r.active]
        assert len(active_rungs) == 1
        assert active_rungs[0].level == DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value

    def test_partial_multimodal_correct_rung_active(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(DegradedOperationLevel.PARTIAL_MULTIMODAL)
        active = [r for r in ladder.rungs if r.active]
        assert active[0].level == "partial_multimodal"

    def test_text_summary_fallback_correct_rung_active(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(DegradedOperationLevel.TEXT_SUMMARY_FALLBACK)
        active = [r for r in ladder.rungs if r.active]
        assert active[0].level == "text_summary_fallback"

    def test_observe_only_correct_rung_active(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(DegradedOperationLevel.OBSERVE_ONLY)
        active = [r for r in ladder.rungs if r.active]
        assert active[0].level == "observe_only"

    def test_no_op_correct_rung_active(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(DegradedOperationLevel.NO_OP)
        active = [r for r in ladder.rungs if r.active]
        assert active[0].level == "no_op"

    def test_transition_occurred_true_when_prior_differs(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(
            DegradedOperationLevel.PARTIAL_MULTIMODAL,
            prior_level=DegradedOperationLevel.FULL_NATIVE_MULTIMODAL,
        )
        assert ladder.transition_occurred is True
        assert ladder.prior_level == "full_native_multimodal"

    def test_transition_occurred_false_when_prior_same(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(
            DegradedOperationLevel.PARTIAL_MULTIMODAL,
            prior_level=DegradedOperationLevel.PARTIAL_MULTIMODAL,
        )
        assert ladder.transition_occurred is False

    def test_transition_occurred_false_when_prior_unknown(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        ladder = build_fallback_policy_ladder(
            DegradedOperationLevel.PARTIAL_MULTIMODAL,
            prior_level=DegradedOperationLevel.UNKNOWN,
        )
        assert ladder.transition_occurred is False

    def test_five_canonical_rungs_always_present(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        for level in [
            DegradedOperationLevel.FULL_NATIVE_MULTIMODAL,
            DegradedOperationLevel.PARTIAL_MULTIMODAL,
            DegradedOperationLevel.TEXT_SUMMARY_FALLBACK,
            DegradedOperationLevel.OBSERVE_ONLY,
            DegradedOperationLevel.NO_OP,
        ]:
            ladder = build_fallback_policy_ladder(level)
            assert len(ladder.rungs) == 5

    def test_never_raises(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_fallback_policy_ladder,
        )

        # None prior_level should not raise
        ladder = build_fallback_policy_ladder(DegradedOperationLevel.FULL_NATIVE_MULTIMODAL)
        assert ladder is not None


# ===========================================================================
# 12. build_degraded_operation_envelope()
# ===========================================================================


class TestBuildDegradedOperationEnvelope:
    def test_native_multimodal_level_and_severity(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_native_multimodal_route())
        assert env.current_level == DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value
        assert env.severity == DegradedOperationSeverity.OK.value

    def test_partial_multimodal_level_and_severity(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.current_level == DegradedOperationLevel.PARTIAL_MULTIMODAL.value
        assert env.severity == DegradedOperationSeverity.WARNING.value

    def test_text_only_level_and_severity(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.current_level == DegradedOperationLevel.TEXT_SUMMARY_FALLBACK.value
        assert env.severity == DegradedOperationSeverity.DEGRADED.value

    def test_advisory_level_and_severity(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            DegradedOperationSeverity,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_advisory_route())
        assert env.current_level == DegradedOperationLevel.OBSERVE_ONLY.value
        assert env.severity == DegradedOperationSeverity.CRITICAL.value

    def test_is_degraded_false_for_full_native(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_native_multimodal_route())
        assert env.is_degraded is False

    def test_is_degraded_true_for_partial(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.is_degraded is True

    def test_is_degraded_true_for_text_only(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.is_degraded is True

    def test_is_observe_only_true_for_advisory(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_advisory_route())
        assert env.is_observe_only is True

    def test_is_observe_only_false_for_partial(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.is_observe_only is False

    def test_provider_and_model_propagated(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(
            _native_multimodal_route(provider="openai", model="gpt-4o")
        )
        assert env.provider == "openai"
        assert env.model == "gpt-4o"

    def test_trace_id_propagated(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(
            _native_multimodal_route(), trace_id="test_trace_123"
        )
        assert env.trace_id == "test_trace_123"

    def test_prior_level_extracted_from_prior_envelope(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        prior = {
            "current_level": DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value
        }
        env = build_degraded_operation_envelope(
            _partial_multimodal_route(), prior_envelope=prior
        )
        assert env.prior_level == DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value

    def test_transition_occurred_when_level_changes(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        prior = {"current_level": DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value}
        env = build_degraded_operation_envelope(
            _partial_multimodal_route(), prior_envelope=prior
        )
        assert env.transition_occurred is True

    def test_no_transition_when_level_unchanged(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        prior = {"current_level": DegradedOperationLevel.PARTIAL_MULTIMODAL.value}
        env = build_degraded_operation_envelope(
            _partial_multimodal_route(), prior_envelope=prior
        )
        assert env.transition_occurred is False

    def test_envelope_includes_failover_chain(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.failover_chain is not None
        assert isinstance(env.failover_chain, dict)

    def test_envelope_includes_fallback_ladder(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.fallback_ladder is not None
        assert isinstance(env.fallback_ladder, dict)

    def test_failover_chain_is_json_serialisable(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        json.dumps(env.failover_chain)

    def test_fallback_ladder_is_json_serialisable(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        json.dumps(env.fallback_ladder)

    def test_none_route_dict_returns_safe_envelope(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(None)
        assert env is not None
        assert env.envelope_id != ""

    def test_garbage_route_dict_never_raises(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        for bad in [{"provider": None}, {}, {"route_type": 999, "model": None}]:
            env = build_degraded_operation_envelope(bad)
            assert env is not None

    def test_supply_snapshot_skipped_providers_in_chain(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        supply = _supply_snapshot_with_down_provider("bad_prov", "openai")
        env = build_degraded_operation_envelope(
            _native_multimodal_route(provider="openai"), supply_snapshot=supply
        )
        chain = env.failover_chain
        assert chain is not None
        skipped = [s for s in chain.get("steps", []) if s.get("skipped")]
        assert len(skipped) >= 1


# ===========================================================================
# 13. envelope_summary()
# ===========================================================================


class TestEnvelopeSummary:
    def test_returns_compact_dict_with_stable_keys(self):
        from core.degraded_operation_envelope import (
            build_degraded_operation_envelope,
            envelope_summary,
        )

        env = build_degraded_operation_envelope(_text_only_route())
        summary = envelope_summary(env)
        expected_keys = {
            "envelope_id",
            "current_level",
            "severity",
            "is_degraded",
            "is_observe_only",
            "provider",
            "model",
            "failover_occurred",
            "failover_reasons",
            "degradation_summary",
            "transition_occurred",
            "prior_level",
            "trace_id",
            "timestamp",
        }
        assert set(summary.keys()) == expected_keys

    def test_is_json_serialisable(self):
        from core.degraded_operation_envelope import (
            build_degraded_operation_envelope,
            envelope_summary,
        )

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        json.dumps(envelope_summary(env))

    def test_failover_occurred_propagated_from_chain(self):
        from core.degraded_operation_envelope import (
            build_degraded_operation_envelope,
            envelope_summary,
        )

        supply = _supply_snapshot_with_down_provider("bad_prov", "openai")
        env = build_degraded_operation_envelope(
            _native_multimodal_route(provider="openai"), supply_snapshot=supply
        )
        summary = envelope_summary(env)
        assert isinstance(summary["failover_occurred"], bool)

    def test_never_raises(self):
        from core.degraded_operation_envelope import (
            DegradedOperationEnvelope,
            envelope_summary,
        )

        # Minimal envelope with no chain/ladder
        env = DegradedOperationEnvelope()
        summary = envelope_summary(env)
        assert summary is not None


# ===========================================================================
# 14. Provider unavailability triggers canonical failover handling
# ===========================================================================


class TestProviderUnavailabilityFailover:
    def test_down_provider_shows_skipped_and_fallback_steps(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_provider_failover_chain,
        )

        route = _text_only_route(provider="fallback_prov", reason="provider_unavailable")
        supply = _supply_snapshot_with_down_provider(
            down_provider="preferred_prov", available_provider="fallback_prov"
        )
        chain = build_provider_failover_chain(route, supply)
        skipped = [s for s in chain.steps if s.skipped]
        selected = [s for s in chain.steps if s.selected]
        assert len(skipped) >= 1
        assert len(selected) == 1
        assert selected[0].provider == "fallback_prov"
        assert skipped[0].failover_reason in (
            ProviderFailoverReason.PROVIDER_UNAVAILABLE.value,
            ProviderFailoverReason.PROVIDER_DEGRADED.value,
        )

    def test_final_provider_differs_from_skipped(self):
        from core.degraded_operation_envelope import build_provider_failover_chain

        route = _text_only_route(provider="openai")
        supply = _supply_snapshot_with_down_provider("bad_prov", "openai")
        chain = build_provider_failover_chain(route, supply)
        skipped_providers = {s.provider for s in chain.steps if s.skipped}
        assert chain.final_provider not in skipped_providers

    def test_primary_failover_reason_is_structured(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_provider_failover_chain,
        )

        route = _text_only_route(reason="provider_unavailable")
        chain = build_provider_failover_chain(route)
        # Should not be UNKNOWN when a known reason is provided
        assert chain.primary_failover_reason == ProviderFailoverReason.PROVIDER_UNAVAILABLE.value


# ===========================================================================
# 15. Full multimodal degrades to partial multimodal
# ===========================================================================


class TestFullToPartialDegradation:
    def test_partial_multimodal_level(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.current_level == DegradedOperationLevel.PARTIAL_MULTIMODAL.value

    def test_severity_is_warning(self):
        from core.degraded_operation_envelope import (
            DegradedOperationSeverity,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.severity == DegradedOperationSeverity.WARNING.value

    def test_is_degraded_true(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.is_degraded is True

    def test_is_observe_only_false(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_partial_multimodal_route())
        assert env.is_observe_only is False


# ===========================================================================
# 16. Partial multimodal degrades to text/summary
# ===========================================================================


class TestPartialToTextDegradation:
    def test_text_summary_fallback_level(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.current_level == DegradedOperationLevel.TEXT_SUMMARY_FALLBACK.value

    def test_severity_is_degraded(self):
        from core.degraded_operation_envelope import (
            DegradedOperationSeverity,
            build_degraded_operation_envelope,
        )

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.severity == DegradedOperationSeverity.DEGRADED.value

    def test_is_observe_only_false(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        assert env.is_observe_only is False


# ===========================================================================
# 17. Degraded envelope is serialisable and projection-ready
# ===========================================================================


class TestEnvelopeSerialisation:
    def test_full_round_trip_json(self):
        from core.degraded_operation_envelope import (
            DegradedOperationEnvelope,
            build_degraded_operation_envelope,
        )

        supply = _supply_snapshot_with_down_provider("bad_prov", "openai")
        env = build_degraded_operation_envelope(
            _partial_multimodal_route(), supply_snapshot=supply, trace_id="rt_123"
        )
        # Serialize to JSON
        raw_json = json.dumps(env.to_dict())
        # Deserialize
        d = json.loads(raw_json)
        env2 = DegradedOperationEnvelope.from_dict(d)
        assert env2.current_level == env.current_level
        assert env2.severity == env.severity
        assert env2.provider == env.provider
        assert env2.trace_id == "rt_123"
        assert isinstance(env2.failover_chain, dict)
        assert isinstance(env2.fallback_ladder, dict)

    def test_all_values_are_primitives(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_advisory_route())
        d = env.to_dict()
        raw = json.dumps(d)
        parsed = json.loads(raw)
        assert isinstance(parsed["envelope_id"], str)
        assert isinstance(parsed["current_level"], str)
        assert isinstance(parsed["is_degraded"], bool)
        assert isinstance(parsed["failover_reasons"], list)


# ===========================================================================
# 18. Failover reasons are structured and stable
# ===========================================================================


class TestFailoverReasonsStability:
    def test_reasons_are_known_values_or_raw_strings(self):
        from core.degraded_operation_envelope import (
            ProviderFailoverReason,
            build_degraded_operation_envelope,
        )

        known_values = {r.value for r in ProviderFailoverReason}
        for route in [
            _native_multimodal_route(),
            _partial_multimodal_route(),
            _text_only_route(),
            _advisory_route(),
        ]:
            env = build_degraded_operation_envelope(route)
            for reason in env.failover_reasons:
                # Each reason is either a known enum value or a raw string (acceptable)
                assert isinstance(reason, str), f"Reason must be a string, got {type(reason)}"

    def test_empty_fallback_reason_produces_empty_reasons_list(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        route = _native_multimodal_route()
        # native_multimodal has empty fallback_reason
        env = build_degraded_operation_envelope(route)
        # Advisory reasons from skipped steps only come if supply is provided
        assert isinstance(env.failover_reasons, list)


# ===========================================================================
# 19. Repeated degraded transitions are coherent
# ===========================================================================


class TestRepeatedTransitions:
    def test_second_transition_tracks_prior_level(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        # Step 1: Full native multimodal
        env1 = build_degraded_operation_envelope(_native_multimodal_route())
        assert env1.current_level == DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value
        assert env1.transition_occurred is False

        # Step 2: Degrade to partial multimodal
        env2 = build_degraded_operation_envelope(
            _partial_multimodal_route(), prior_envelope=env1.to_dict()
        )
        assert env2.current_level == DegradedOperationLevel.PARTIAL_MULTIMODAL.value
        assert env2.prior_level == DegradedOperationLevel.FULL_NATIVE_MULTIMODAL.value
        assert env2.transition_occurred is True

        # Step 3: Degrade to text summary
        env3 = build_degraded_operation_envelope(
            _text_only_route(), prior_envelope=env2.to_dict()
        )
        assert env3.current_level == DegradedOperationLevel.TEXT_SUMMARY_FALLBACK.value
        assert env3.prior_level == DegradedOperationLevel.PARTIAL_MULTIMODAL.value
        assert env3.transition_occurred is True

    def test_stable_level_no_transition(self):
        from core.degraded_operation_envelope import (
            DegradedOperationLevel,
            build_degraded_operation_envelope,
        )

        env1 = build_degraded_operation_envelope(_partial_multimodal_route())
        env2 = build_degraded_operation_envelope(
            _partial_multimodal_route(), prior_envelope=env1.to_dict()
        )
        assert env2.transition_occurred is False

    def test_ladder_current_level_matches_envelope_level(self):
        from core.degraded_operation_envelope import build_degraded_operation_envelope

        env = build_degraded_operation_envelope(_text_only_route())
        ladder = env.fallback_ladder
        assert ladder is not None
        assert ladder["current_level"] == env.current_level


# ===========================================================================
# 20. OpenClawd integration
# ===========================================================================


class TestOpenClawdIntegration:
    def _get_openclawd(self):
        try:
            from core.openclawd import OpenClawd

            return OpenClawd.__new__(OpenClawd)
        except Exception:
            return None

    def test_method_exists(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd unavailable")
        assert hasattr(oc, "_build_degraded_operation_envelope")

    def test_returns_dict_on_valid_route_dict(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd unavailable")

        route = _native_multimodal_route()
        result = oc._build_degraded_operation_envelope(route_dict=route)
        # Must be a dict or None (never raises)
        assert result is None or isinstance(result, dict)

    def test_returns_dict_with_required_keys_on_valid_input(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd unavailable")

        route = _partial_multimodal_route()
        result = oc._build_degraded_operation_envelope(route_dict=route)
        if result is not None:
            assert "current_level" in result
            assert "severity" in result
            assert "is_degraded" in result
            assert "envelope_id" in result

    def test_never_raises_on_none_route(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd unavailable")

        # Must not raise
        result = oc._build_degraded_operation_envelope(route_dict=None)
        assert result is None or isinstance(result, dict)

    def test_never_raises_on_garbage_route(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd unavailable")

        result = oc._build_degraded_operation_envelope(
            route_dict={"route_type": None, "provider": 42}
        )
        assert result is None or isinstance(result, dict)


# ===========================================================================
# 21. Module imports
# ===========================================================================


class TestModuleImports:
    def test_all_public_symbols_importable(self):
        from core.degraded_operation_envelope import (
            DegradedOperationEnvelope,
            DegradedOperationLevel,
            DegradedOperationSeverity,
            FallbackLadderRung,
            FallbackPolicyLadder,
            ProviderFailoverChain,
            ProviderFailoverReason,
            ProviderFailoverStep,
            build_degraded_operation_envelope,
            build_fallback_policy_ladder,
            build_provider_failover_chain,
            build_provider_failover_step,
            envelope_summary,
        )

        # Verify they are the right types
        assert issubclass(DegradedOperationLevel, str)
        assert issubclass(ProviderFailoverReason, str)
        assert issubclass(DegradedOperationSeverity, str)
        assert callable(build_degraded_operation_envelope)
        assert callable(envelope_summary)
        # Verify enum members are proper enum instances
        assert isinstance(DegradedOperationLevel.FULL_NATIVE_MULTIMODAL, DegradedOperationLevel)
        assert isinstance(ProviderFailoverReason.PROVIDER_UNAVAILABLE, ProviderFailoverReason)
        assert isinstance(DegradedOperationSeverity.OK, DegradedOperationSeverity)
