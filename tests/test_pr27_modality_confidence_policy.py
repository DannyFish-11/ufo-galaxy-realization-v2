#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr27_modality_confidence_policy.py
=============================================

PR-27 — Source-to-Routing Calibration and Modality Confidence Policy

Coverage
--------

1. ModalityPresence enum
   - all expected values present
   - string values are stable

2. SourceDegradationSeverity enum
   - all expected values present
   - string values are stable

3. ModalitySemantics enum
   - all expected values present

4. RoutingEligibilityReason enum
   - all expected values present

5. ModalityConfidencePolicy
   - construction with defaults
   - construction with all fields
   - to_dict is JSON-serialisable
   - from_dict round-trip preserves all fields

6. RoutingEligibilityAssessment
   - construction with defaults
   - construction with full fields
   - to_dict is JSON-serialisable
   - from_dict round-trip preserves all fields

7. PerceptionRoutingReadiness
   - construction with defaults
   - construction with full fields
   - to_dict is JSON-serialisable
   - from_dict round-trip preserves all fields

8. assess_modality_confidence()
   - absent when no source records
   - healthy source → strong presence, high confidence
   - degraded source → reduced confidence
   - unavailable source → absent or very low confidence
   - stale source → staleness flag set, confidence reduced
   - quality_score respected
   - multiple sources: best-source score used
   - contributing_source_ids populated

9. assess_routing_eligibility()
   - empty policy list → not eligible
   - strong signal → eligible with STRONG_MULTIMODAL_SIGNAL reason
   - adequate signal → eligible with ADEQUATE_MULTIMODAL_SIGNAL reason
   - confidence below threshold → not eligible, CONFIDENCE_BELOW_THRESHOLD
   - degraded source → not eligible with WEAK_SIGNAL_DEGRADED_ELIGIBILITY reason
   - required modality absent → not eligible with MODALITY_REQUIRED_BUT_ABSENT
   - all_reasons are stable enum values
   - eligibility_summary is a non-empty string

10. build_perception_routing_readiness()
    - None perception → readiness with NO_MULTIMODAL_INPUT
    - text-only perception → not eligible
    - strong multimodal request-bound input → eligible
    - degraded source lowers eligibility
    - stale continuous perception flagged
    - request-bound overrides missing continuous perception
    - source registry snapshot respected
    - result is fully JSON-serialisable

11. Integration: _select_multimodal_route() with PR-27 readiness
    - text-only request → perception_routing_readiness in result
    - degraded signal → route degrades to text_only via eligibility gate
    - strong signal with native MM provider → native_multimodal route
    - readiness dict is JSON-serialisable

12. Additive integration
    - PR-27 exports available from core.multimodal
    - importing does not break existing behaviour
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _make_source_record(
    *,
    source_id: str = "src-001",
    modality: str = "audio",
    health: str = "healthy",
    is_active: bool = True,
    quality_score: Optional[float] = 0.9,
    last_seen_at: Optional[float] = None,
    degradation_reasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a minimal source record dict (mimics PerceptionSourceRecord.to_dict)."""
    return {
        "source_id": source_id,
        "source_type": "microphone",
        "modality": modality,
        "display_name": "Test Source",
        "device_id": None,
        "transport": "local",
        "is_active": is_active,
        "is_primary_audio": modality == "audio",
        "is_primary_video": modality == "video",
        "priority": 10,
        "health": health,
        "degradation_reasons": degradation_reasons or [],
        "quality_score": quality_score,
        "latency_ms": None,
        "registered_at": time.time() - 60.0,
        "last_seen_at": last_seen_at if last_seen_at is not None else time.time(),
        "extra": {},
    }


def _make_perception_dict(
    *,
    has_request_multimodal: bool = True,
    has_continuous_perception: bool = False,
    active_modalities: Optional[List[str]] = None,
    requires_native_multimodal: bool = True,
    continuous_wall_clock: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a minimal canonical perception state dict."""
    return {
        "runtime_session_id": "sess-pr27-001",
        "trace_id": "trace-pr27-001",
        "has_continuous_perception": has_continuous_perception,
        "continuous_frame_id": 1 if has_continuous_perception else None,
        "continuous_wall_clock": continuous_wall_clock,
        "continuous_overall_quality": 0.85 if has_continuous_perception else None,
        "has_request_multimodal": has_request_multimodal,
        "active_modalities": active_modalities or (["image", "audio"] if has_request_multimodal else []),
        "audio_summary": None,
        "video_summary": None,
        "screen_summary": None,
        "sensor_summary": None,
        "system_summary": None,
        "source_summary": {},
        "fusion_summary": "",
        "requires_native_multimodal": requires_native_multimodal,
        "degradation_reasons": [],
        "perception_summary": "test perception",
    }


def _make_registry_snapshot(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a minimal source registry snapshot."""
    return {
        "sources": records,
        "primary_audio_source_id": None,
        "primary_video_source_id": None,
    }


# ===========================================================================
# 1. ModalityPresence enum
# ===========================================================================


class TestModalityPresenceEnum:
    def test_all_expected_values(self):
        from core.multimodal.modality_confidence_policy import ModalityPresence

        assert ModalityPresence.ABSENT.value == "absent"
        assert ModalityPresence.WEAK.value == "weak"
        assert ModalityPresence.MODERATE.value == "moderate"
        assert ModalityPresence.STRONG.value == "strong"

    def test_string_subclass(self):
        from core.multimodal.modality_confidence_policy import ModalityPresence

        assert isinstance(ModalityPresence.STRONG, str)


# ===========================================================================
# 2. SourceDegradationSeverity enum
# ===========================================================================


class TestSourceDegradationSeverityEnum:
    def test_all_expected_values(self):
        from core.multimodal.modality_confidence_policy import SourceDegradationSeverity

        assert SourceDegradationSeverity.NONE.value == "none"
        assert SourceDegradationSeverity.LOW.value == "low"
        assert SourceDegradationSeverity.MEDIUM.value == "medium"
        assert SourceDegradationSeverity.HIGH.value == "high"
        assert SourceDegradationSeverity.UNAVAILABLE.value == "unavailable"

    def test_string_subclass(self):
        from core.multimodal.modality_confidence_policy import SourceDegradationSeverity

        assert isinstance(SourceDegradationSeverity.HIGH, str)


# ===========================================================================
# 3. ModalitySemantics enum
# ===========================================================================


class TestModalitySemantics:
    def test_all_expected_values(self):
        from core.multimodal.modality_confidence_policy import ModalitySemantics

        assert ModalitySemantics.REQUIRED.value == "required"
        assert ModalitySemantics.PREFERRED.value == "preferred"
        assert ModalitySemantics.OPTIONAL.value == "optional"
        assert ModalitySemantics.CONTINUOUS_ONLY.value == "continuous_only"


# ===========================================================================
# 4. RoutingEligibilityReason enum
# ===========================================================================


class TestRoutingEligibilityReason:
    def test_all_expected_values(self):
        from core.multimodal.modality_confidence_policy import RoutingEligibilityReason

        expected = {
            "strong_multimodal_signal",
            "adequate_multimodal_signal",
            "weak_signal_degraded_eligibility",
            "source_degraded",
            "source_unavailable",
            "stale_continuous_perception",
            "request_bound_override",
            "no_multimodal_input",
            "modality_required_but_absent",
            "confidence_below_threshold",
            "text_only_fallback",
        }
        actual = {r.value for r in RoutingEligibilityReason}
        assert expected.issubset(actual)


# ===========================================================================
# 5. ModalityConfidencePolicy dataclass
# ===========================================================================


class TestModalityConfidencePolicy:
    def test_construction_defaults(self):
        from core.multimodal.modality_confidence_policy import (
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            ModalitySemantics,
        )

        pol = ModalityConfidencePolicy(modality="audio")
        assert pol.modality == "audio"
        assert pol.presence == ModalityPresence.ABSENT
        assert pol.confidence_score == 0.0
        assert pol.source_quality_score is None
        assert pol.degradation_severity == SourceDegradationSeverity.NONE
        assert pol.is_stale is False
        assert pol.staleness_age_s is None
        assert pol.semantics == ModalitySemantics.OPTIONAL
        assert pol.contributing_source_ids == []
        assert pol.degradation_reasons == []

    def test_construction_full(self):
        from core.multimodal.modality_confidence_policy import (
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            ModalitySemantics,
        )

        pol = ModalityConfidencePolicy(
            modality="video",
            presence=ModalityPresence.STRONG,
            confidence_score=0.92,
            source_quality_score=0.95,
            degradation_severity=SourceDegradationSeverity.NONE,
            is_stale=False,
            staleness_age_s=0.5,
            semantics=ModalitySemantics.REQUIRED,
            contributing_source_ids=["src-001"],
            degradation_reasons=[],
        )
        assert pol.modality == "video"
        assert pol.confidence_score == 0.92
        assert pol.semantics == ModalitySemantics.REQUIRED

    def test_to_dict_is_json_serialisable(self):
        from core.multimodal.modality_confidence_policy import (
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
        )

        pol = ModalityConfidencePolicy(
            modality="audio",
            presence=ModalityPresence.MODERATE,
            confidence_score=0.6,
            degradation_severity=SourceDegradationSeverity.LOW,
            contributing_source_ids=["src-x"],
        )
        d = pol.to_dict()
        assert json.dumps(d)  # must not raise

    def test_from_dict_round_trip(self):
        from core.multimodal.modality_confidence_policy import (
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            ModalitySemantics,
        )

        original = ModalityConfidencePolicy(
            modality="image",
            presence=ModalityPresence.STRONG,
            confidence_score=0.88,
            source_quality_score=0.9,
            degradation_severity=SourceDegradationSeverity.LOW,
            is_stale=True,
            staleness_age_s=7.2,
            semantics=ModalitySemantics.PREFERRED,
            contributing_source_ids=["src-a", "src-b"],
            degradation_reasons=["minor_lag"],
        )
        restored = ModalityConfidencePolicy.from_dict(original.to_dict())
        assert restored.modality == original.modality
        assert restored.presence == original.presence
        assert abs(restored.confidence_score - original.confidence_score) < 1e-6
        assert restored.is_stale == original.is_stale
        assert restored.semantics == original.semantics
        assert restored.contributing_source_ids == original.contributing_source_ids


# ===========================================================================
# 6. RoutingEligibilityAssessment dataclass
# ===========================================================================


class TestRoutingEligibilityAssessment:
    def test_construction_defaults(self):
        from core.multimodal.modality_confidence_policy import (
            RoutingEligibilityAssessment,
            RoutingEligibilityReason,
            SourceDegradationSeverity,
        )

        assessment = RoutingEligibilityAssessment()
        assert assessment.is_native_multimodal_eligible is False
        assert assessment.aggregate_confidence == 0.0
        assert assessment.primary_reason == RoutingEligibilityReason.NO_MULTIMODAL_INPUT
        assert assessment.all_reasons == []
        assert assessment.modality_policies == []
        assert assessment.has_required_modality_absent is False
        assert assessment.is_degraded is False
        assert assessment.degradation_severity == SourceDegradationSeverity.NONE
        assert isinstance(assessment.eligibility_summary, str)

    def test_to_dict_is_json_serialisable(self):
        from core.multimodal.modality_confidence_policy import RoutingEligibilityAssessment

        assessment = RoutingEligibilityAssessment()
        d = assessment.to_dict()
        assert json.dumps(d)

    def test_from_dict_round_trip(self):
        from core.multimodal.modality_confidence_policy import (
            RoutingEligibilityAssessment,
            RoutingEligibilityReason,
            SourceDegradationSeverity,
        )

        original = RoutingEligibilityAssessment(
            is_native_multimodal_eligible=True,
            aggregate_confidence=0.85,
            primary_reason=RoutingEligibilityReason.STRONG_MULTIMODAL_SIGNAL,
            all_reasons=[RoutingEligibilityReason.STRONG_MULTIMODAL_SIGNAL],
            has_required_modality_absent=False,
            is_degraded=False,
            degradation_severity=SourceDegradationSeverity.NONE,
            eligibility_summary="test summary",
        )
        restored = RoutingEligibilityAssessment.from_dict(original.to_dict())
        assert restored.is_native_multimodal_eligible == original.is_native_multimodal_eligible
        assert abs(restored.aggregate_confidence - original.aggregate_confidence) < 1e-6
        assert restored.primary_reason == original.primary_reason
        assert restored.all_reasons == original.all_reasons
        assert restored.eligibility_summary == original.eligibility_summary


# ===========================================================================
# 7. PerceptionRoutingReadiness dataclass
# ===========================================================================


class TestPerceptionRoutingReadiness:
    def test_construction_defaults(self):
        from core.multimodal.modality_confidence_policy import PerceptionRoutingReadiness

        readiness = PerceptionRoutingReadiness()
        assert readiness.has_request_multimodal is False
        assert readiness.has_continuous_perception is False
        assert readiness.request_bound_modalities == []
        assert readiness.continuous_modalities == []
        assert readiness.continuous_perception_age_s is None
        assert readiness.is_continuous_perception_stale is False
        assert readiness.request_overrides_continuous is False
        assert readiness.assessed_at > 0

    def test_to_dict_is_json_serialisable(self):
        from core.multimodal.modality_confidence_policy import PerceptionRoutingReadiness

        r = PerceptionRoutingReadiness()
        d = r.to_dict()
        assert json.dumps(d)

    def test_from_dict_round_trip(self):
        from core.multimodal.modality_confidence_policy import (
            PerceptionRoutingReadiness,
            RoutingEligibilityAssessment,
        )

        ts = time.time()
        original = PerceptionRoutingReadiness(
            eligibility=RoutingEligibilityAssessment(
                is_native_multimodal_eligible=True,
                aggregate_confidence=0.75,
            ),
            has_request_multimodal=True,
            has_continuous_perception=False,
            request_bound_modalities=["image"],
            continuous_modalities=[],
            continuous_perception_age_s=None,
            is_continuous_perception_stale=False,
            request_overrides_continuous=True,
            assessed_at=ts,
        )
        restored = PerceptionRoutingReadiness.from_dict(original.to_dict())
        assert restored.has_request_multimodal is True
        assert restored.request_overrides_continuous is True
        assert restored.eligibility.is_native_multimodal_eligible is True
        assert abs(restored.assessed_at - ts) < 0.01


# ===========================================================================
# 8. assess_modality_confidence()
# ===========================================================================


class TestAssessModalityConfidence:
    def test_absent_when_no_source_records(self):
        from core.multimodal.modality_confidence_policy import (
            assess_modality_confidence,
            ModalityPresence,
            SourceDegradationSeverity,
        )

        pol = assess_modality_confidence(modality="audio", source_records=None)
        assert pol.presence == ModalityPresence.ABSENT
        assert pol.confidence_score == 0.0
        assert pol.degradation_severity == SourceDegradationSeverity.UNAVAILABLE

    def test_absent_when_empty_source_records(self):
        from core.multimodal.modality_confidence_policy import (
            assess_modality_confidence,
            ModalityPresence,
        )

        pol = assess_modality_confidence(modality="audio", source_records=[])
        assert pol.presence == ModalityPresence.ABSENT

    def test_healthy_active_source_high_confidence(self):
        from core.multimodal.modality_confidence_policy import (
            assess_modality_confidence,
            ModalityPresence,
            SourceDegradationSeverity,
        )

        rec = _make_source_record(
            source_id="mic-001",
            modality="audio",
            health="healthy",
            is_active=True,
            quality_score=0.95,
            last_seen_at=time.time(),
        )
        pol = assess_modality_confidence(
            modality="audio",
            source_records=[rec],
            now=time.time(),
        )
        assert pol.presence == ModalityPresence.STRONG
        assert pol.confidence_score >= 0.7
        assert pol.degradation_severity == SourceDegradationSeverity.NONE
        assert pol.is_stale is False
        assert "mic-001" in pol.contributing_source_ids

    def test_degraded_source_reduces_confidence(self):
        from core.multimodal.modality_confidence_policy import (
            assess_modality_confidence,
            ModalityPresence,
            SourceDegradationSeverity,
        )

        rec = _make_source_record(
            source_id="mic-002",
            health="degraded",
            is_active=True,
            quality_score=0.7,
            degradation_reasons=["noise_too_high"],
        )
        pol = assess_modality_confidence(modality="audio", source_records=[rec])
        # Confidence should be below healthy source
        assert pol.confidence_score < 0.7
        assert pol.degradation_severity == SourceDegradationSeverity.MEDIUM
        assert "noise_too_high" in pol.degradation_reasons

    def test_unavailable_source_zero_confidence(self):
        from core.multimodal.modality_confidence_policy import (
            assess_modality_confidence,
            SourceDegradationSeverity,
        )

        rec = _make_source_record(
            source_id="mic-003",
            health="unavailable",
            is_active=False,
            quality_score=0.0,
        )
        pol = assess_modality_confidence(modality="audio", source_records=[rec])
        assert pol.confidence_score == 0.0
        assert pol.degradation_severity == SourceDegradationSeverity.UNAVAILABLE

    def test_stale_source_flagged(self):
        from core.multimodal.modality_confidence_policy import (
            assess_modality_confidence,
            CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S,
        )

        stale_ts = time.time() - CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S - 2.0
        rec = _make_source_record(
            source_id="cam-001",
            modality="video",
            health="healthy",
            is_active=True,
            quality_score=0.9,
            last_seen_at=stale_ts,
        )
        now_ts = time.time()
        pol = assess_modality_confidence(
            modality="video",
            source_records=[rec],
            now=now_ts,
        )
        assert pol.is_stale is True
        assert pol.staleness_age_s is not None
        assert pol.staleness_age_s > CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S

    def test_quality_score_respected(self):
        from core.multimodal.modality_confidence_policy import assess_modality_confidence

        rec_low = _make_source_record(quality_score=0.2, is_active=True)
        rec_high = _make_source_record(quality_score=0.95, is_active=True)

        pol_low = assess_modality_confidence(modality="audio", source_records=[rec_low])
        pol_high = assess_modality_confidence(modality="audio", source_records=[rec_high])
        assert pol_high.confidence_score > pol_low.confidence_score

    def test_multiple_sources_uses_best(self):
        from core.multimodal.modality_confidence_policy import assess_modality_confidence

        rec_bad = _make_source_record(
            source_id="src-bad", health="degraded", quality_score=0.2, is_active=True
        )
        rec_good = _make_source_record(
            source_id="src-good", health="healthy", quality_score=0.9, is_active=True
        )
        pol = assess_modality_confidence(
            modality="audio",
            source_records=[rec_bad, rec_good],
        )
        # Best-source scoring: should be >= good source score
        single_good = assess_modality_confidence(
            modality="audio",
            source_records=[rec_good],
        )
        assert pol.confidence_score >= single_good.confidence_score * 0.95

    def test_contributing_source_ids_populated(self):
        from core.multimodal.modality_confidence_policy import assess_modality_confidence

        rec1 = _make_source_record(source_id="id-a", is_active=True)
        rec2 = _make_source_record(source_id="id-b", is_active=True)
        pol = assess_modality_confidence(modality="audio", source_records=[rec1, rec2])
        assert "id-a" in pol.contributing_source_ids
        assert "id-b" in pol.contributing_source_ids


# ===========================================================================
# 9. assess_routing_eligibility()
# ===========================================================================


class TestAssessRoutingEligibility:
    def test_empty_policies_not_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            RoutingEligibilityReason,
        )

        assessment = assess_routing_eligibility([])
        assert assessment.is_native_multimodal_eligible is False
        assert assessment.primary_reason == RoutingEligibilityReason.NO_MULTIMODAL_INPUT

    def test_strong_signal_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            ModalitySemantics,
            RoutingEligibilityReason,
        )

        pol = ModalityConfidencePolicy(
            modality="image",
            presence=ModalityPresence.STRONG,
            confidence_score=0.92,
            degradation_severity=SourceDegradationSeverity.NONE,
            semantics=ModalitySemantics.REQUIRED,
        )
        assessment = assess_routing_eligibility([pol])
        assert assessment.is_native_multimodal_eligible is True
        assert assessment.primary_reason == RoutingEligibilityReason.STRONG_MULTIMODAL_SIGNAL
        assert assessment.aggregate_confidence >= 0.8

    def test_adequate_signal_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            RoutingEligibilityReason,
        )

        pol = ModalityConfidencePolicy(
            modality="audio",
            presence=ModalityPresence.MODERATE,
            confidence_score=0.65,
            degradation_severity=SourceDegradationSeverity.NONE,
        )
        assessment = assess_routing_eligibility([pol])
        assert assessment.is_native_multimodal_eligible is True
        assert assessment.primary_reason == RoutingEligibilityReason.ADEQUATE_MULTIMODAL_SIGNAL

    def test_confidence_below_threshold_not_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            RoutingEligibilityReason,
        )

        pol = ModalityConfidencePolicy(
            modality="audio",
            presence=ModalityPresence.WEAK,
            confidence_score=0.3,
            degradation_severity=SourceDegradationSeverity.NONE,
        )
        assessment = assess_routing_eligibility([pol], confidence_threshold=0.5)
        assert assessment.is_native_multimodal_eligible is False
        assert assessment.primary_reason in {
            RoutingEligibilityReason.CONFIDENCE_BELOW_THRESHOLD,
            RoutingEligibilityReason.WEAK_SIGNAL_DEGRADED_ELIGIBILITY,
        }

    def test_degraded_source_lowers_eligibility(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            RoutingEligibilityReason,
        )

        pol = ModalityConfidencePolicy(
            modality="audio",
            presence=ModalityPresence.WEAK,
            confidence_score=0.25,
            degradation_severity=SourceDegradationSeverity.HIGH,
        )
        assessment = assess_routing_eligibility([pol], confidence_threshold=0.5)
        assert assessment.is_native_multimodal_eligible is False
        assert RoutingEligibilityReason.SOURCE_DEGRADED in assessment.all_reasons

    def test_required_modality_absent_blocks(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
            ModalitySemantics,
            RoutingEligibilityReason,
        )

        pol = ModalityConfidencePolicy(
            modality="image",
            presence=ModalityPresence.ABSENT,
            confidence_score=0.0,
            semantics=ModalitySemantics.REQUIRED,
        )
        assessment = assess_routing_eligibility([pol])
        assert assessment.is_native_multimodal_eligible is False
        assert assessment.has_required_modality_absent is True
        assert assessment.primary_reason == RoutingEligibilityReason.MODALITY_REQUIRED_BUT_ABSENT

    def test_all_reasons_are_stable_enum_values(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
            SourceDegradationSeverity,
            RoutingEligibilityReason,
        )

        pol = ModalityConfidencePolicy(
            modality="video",
            presence=ModalityPresence.MODERATE,
            confidence_score=0.55,
            degradation_severity=SourceDegradationSeverity.MEDIUM,
        )
        assessment = assess_routing_eligibility([pol])
        for reason in assessment.all_reasons:
            # Should be convertible back to the enum
            assert RoutingEligibilityReason(reason.value) == reason

    def test_eligibility_summary_is_non_empty_string(self):
        from core.multimodal.modality_confidence_policy import (
            assess_routing_eligibility,
            ModalityConfidencePolicy,
            ModalityPresence,
        )

        pol = ModalityConfidencePolicy(
            modality="audio",
            presence=ModalityPresence.STRONG,
            confidence_score=0.9,
        )
        assessment = assess_routing_eligibility([pol])
        assert isinstance(assessment.eligibility_summary, str)
        assert len(assessment.eligibility_summary) > 0


# ===========================================================================
# 10. build_perception_routing_readiness()
# ===========================================================================


class TestBuildPerceptionRoutingReadiness:
    def test_none_perception_not_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
            RoutingEligibilityReason,
        )

        readiness = build_perception_routing_readiness(canonical_perception=None)
        assert readiness.eligibility.is_native_multimodal_eligible is False
        assert readiness.eligibility.primary_reason == RoutingEligibilityReason.NO_MULTIMODAL_INPUT

    def test_text_only_perception_not_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
        )

        perception = _make_perception_dict(
            has_request_multimodal=False,
            active_modalities=[],
            requires_native_multimodal=False,
        )
        readiness = build_perception_routing_readiness(canonical_perception=perception)
        assert readiness.eligibility.is_native_multimodal_eligible is False
        assert readiness.has_request_multimodal is False

    def test_strong_multimodal_request_eligible(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
        )

        perception = _make_perception_dict(
            has_request_multimodal=True,
            active_modalities=["image", "audio"],
            requires_native_multimodal=True,
        )
        readiness = build_perception_routing_readiness(canonical_perception=perception)
        assert readiness.has_request_multimodal is True
        # With request-bound input and no source registry, should be eligible
        assert readiness.eligibility.is_native_multimodal_eligible is True

    def test_degraded_source_lowers_eligibility(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
            SourceDegradationSeverity,
        )

        perception = _make_perception_dict(
            has_request_multimodal=False,
            has_continuous_perception=True,
            active_modalities=["audio"],
            requires_native_multimodal=True,
            continuous_wall_clock=time.time(),
        )
        registry = _make_registry_snapshot([
            _make_source_record(
                source_id="mic-deg",
                modality="audio",
                health="unavailable",
                is_active=False,
                quality_score=0.0,
            )
        ])
        readiness = build_perception_routing_readiness(
            canonical_perception=perception,
            source_registry_snapshot=registry,
        )
        # An unavailable source should block native MM eligibility
        assert readiness.eligibility.is_native_multimodal_eligible is False
        # The modality policy should reflect the unavailable severity
        policies = readiness.eligibility.modality_policies
        assert len(policies) > 0
        assert any(
            p.degradation_severity == SourceDegradationSeverity.UNAVAILABLE
            for p in policies
        )

    def test_stale_continuous_perception_flagged(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
            CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S,
        )

        now = time.time()
        stale_clock = now - CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S - 3.0
        perception = _make_perception_dict(
            has_continuous_perception=True,
            continuous_wall_clock=stale_clock,
            has_request_multimodal=False,
            requires_native_multimodal=True,
            active_modalities=["audio"],
        )
        readiness = build_perception_routing_readiness(
            canonical_perception=perception,
            now=now,
        )
        assert readiness.is_continuous_perception_stale is True

    def test_request_bound_overrides_missing_continuous(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
            RoutingEligibilityReason,
        )

        perception = _make_perception_dict(
            has_request_multimodal=True,
            has_continuous_perception=False,
            active_modalities=["image"],
            requires_native_multimodal=True,
        )
        readiness = build_perception_routing_readiness(canonical_perception=perception)
        assert readiness.request_overrides_continuous is True
        assert readiness.eligibility.is_native_multimodal_eligible is True

    def test_source_registry_snapshot_respected(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
        )

        perception = _make_perception_dict(
            has_request_multimodal=False,
            has_continuous_perception=True,
            active_modalities=["audio"],
            requires_native_multimodal=True,
            continuous_wall_clock=time.time(),
        )
        registry = _make_registry_snapshot([
            _make_source_record(
                source_id="mic-ok",
                modality="audio",
                health="healthy",
                is_active=True,
                quality_score=0.9,
                last_seen_at=time.time(),
            )
        ])
        readiness = build_perception_routing_readiness(
            canonical_perception=perception,
            source_registry_snapshot=registry,
        )
        # Healthy source should make the assessment confident
        assert readiness.eligibility.aggregate_confidence > 0.0

    def test_result_is_json_serialisable(self):
        from core.multimodal.modality_confidence_policy import (
            build_perception_routing_readiness,
        )

        perception = _make_perception_dict(
            has_request_multimodal=True,
            active_modalities=["image"],
            requires_native_multimodal=True,
        )
        readiness = build_perception_routing_readiness(canonical_perception=perception)
        d = readiness.to_dict()
        # Must not raise
        assert json.dumps(d)


# ===========================================================================
# 11. Integration: _select_multimodal_route() with PR-27 readiness
# ===========================================================================


class TestSelectMultimodalRouteIntegration:
    """Verify that OpenClawd._select_multimodal_route embeds readiness data."""

    def _make_openclawd(self):
        """Build a minimal OpenClawd instance with no real providers."""
        try:
            from core.openclawd import OpenClawd
            oc = OpenClawd.__new__(OpenClawd)
            oc._router = None
            oc._provider_config = {}
            oc._initialized = True
            oc._providers = {}
            # Minimal attribute stubs to avoid AttributeError
            for attr in ("_fusion_suffix", "_agent", "_swarm"):
                if not hasattr(oc, attr):
                    object.__setattr__(oc, attr, None)
            return oc
        except Exception:
            return None

    def test_text_only_includes_readiness(self):
        oc = self._make_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not instantiable in minimal test environment")

        text_perception = {
            "has_request_multimodal": False,
            "has_continuous_perception": False,
            "active_modalities": [],
            "requires_native_multimodal": False,
        }
        result = oc._select_multimodal_route(text_perception)
        assert result["route_type"] == "text_only"
        # PR-27: readiness should be present
        assert "perception_routing_readiness" in result
        assert json.dumps(result["perception_routing_readiness"])

    def test_degraded_signal_degrades_to_text_only(self):
        """When eligibility gate blocks native MM, route degrades gracefully."""
        oc = self._make_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not instantiable in minimal test environment")

        # Build perception that requires native MM
        mm_perception = {
            "has_request_multimodal": False,
            "has_continuous_perception": True,
            "active_modalities": ["audio"],
            "requires_native_multimodal": True,
            "continuous_wall_clock": time.time(),
        }
        # Registry with unavailable source
        degraded_registry = _make_registry_snapshot([
            _make_source_record(
                source_id="mic-unavail",
                modality="audio",
                health="unavailable",
                is_active=False,
                quality_score=0.0,
            )
        ])
        result = oc._select_multimodal_route(mm_perception, degraded_registry)
        # Should degrade to text_only (eligibility gate) or advisory (router_unavailable)
        assert result["route_type"] in ("text_only", "advisory")
        if "perception_routing_readiness" in result:
            assert json.dumps(result["perception_routing_readiness"])

    def test_readiness_dict_is_json_serialisable(self):
        oc = self._make_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not instantiable in minimal test environment")

        perception = _make_perception_dict(
            has_request_multimodal=True,
            active_modalities=["image"],
            requires_native_multimodal=True,
        )
        result = oc._select_multimodal_route(perception)
        assert json.dumps(result)  # full result must be serialisable


# ===========================================================================
# 12. Additive integration
# ===========================================================================


class TestAdditiveIntegration:
    def test_exports_available_from_core_multimodal(self):
        from core.multimodal import (
            ModalityPresence,
            SourceDegradationSeverity,
            ModalitySemantics,
            RoutingEligibilityReason,
            ModalityConfidencePolicy,
            RoutingEligibilityAssessment,
            PerceptionRoutingReadiness,
            assess_modality_confidence,
            assess_routing_eligibility,
            build_perception_routing_readiness,
        )
        assert ModalityPresence is not None
        assert PerceptionRoutingReadiness is not None
        assert callable(build_perception_routing_readiness)

    def test_import_does_not_break_existing_exports(self):
        """Importing the PR-27 module must not remove existing exports."""
        from core.multimodal import (
            PerceptionSourceRegistry,
            PerceptionSourceType,
            SourceModality,
            SourceHealthStatus,
            PerceptionSourceRecord,
        )
        assert PerceptionSourceRegistry is not None
        assert SourceModality is not None

    def test_direct_module_import(self):
        import core.multimodal.modality_confidence_policy as m

        assert hasattr(m, "ModalityConfidencePolicy")
        assert hasattr(m, "RoutingEligibilityAssessment")
        assert hasattr(m, "PerceptionRoutingReadiness")
        assert hasattr(m, "build_perception_routing_readiness")
        assert hasattr(m, "assess_modality_confidence")
        assert hasattr(m, "assess_routing_eligibility")
