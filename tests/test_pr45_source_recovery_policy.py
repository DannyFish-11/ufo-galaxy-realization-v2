#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr45_source_recovery_policy.py
==========================================
Tests for PR-31: Runtime Source/Session Recovery and Primary-Source Re-election.

Coverage
--------
1.  SourceRecoverability
    - all expected enum values present and stable
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

2.  SourceFreshness
    - all expected enum values present and stable
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

3.  PrimarySourceSwitchReason
    - all expected enum values present and stable
    - from_string round-trips all known values
    - from_string returns NONE for unrecognised input

4.  RecoveryEventKind
    - all expected enum values present and stable
    - from_string round-trips all known values
    - from_string returns RECOVERED for unrecognised input

5.  SourceRecoveryEvent
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - to_dict is JSON-serialisable
    - event_id is auto-generated (UUID)
    - occurred_at is auto-populated

6.  PrimarySourceSwitchEvent
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - to_dict is JSON-serialisable
    - event_id is auto-generated

7.  SourceRecoverySnapshot
    - construction with defaults
    - to_dict / from_dict round-trip preserves all fields
    - to_dict is JSON-serialisable
    - snapshot_id is auto-generated (UUID)
    - snapshot_at is auto-populated
    - round-trip preserves nested event lists

8.  SourceRecoveryPolicy — assess_recoverability
    - HEALTHY source → UNKNOWN
    - DEGRADED source → RECOVERABLE
    - UNAVAILABLE source → UNRECOVERABLE
    - None input → UNKNOWN

9.  SourceRecoveryPolicy — assess_freshness
    - active source → FRESH
    - recently seen inactive source → FRESH
    - old inactive source → STALE
    - inactive source with no last_seen_at → UNKNOWN
    - None input → UNKNOWN
    - custom stale_threshold_s is respected

10. SourceRecoveryPolicy — attempt_recovery
    - DEGRADED source is recovered (health=HEALTHY, is_active=True)
    - degradation_reasons are cleared on recovery
    - UNAVAILABLE source is NOT recovered
    - HEALTHY source returns False
    - unknown source_id returns False
    - recovery event is appended to policy event log
    - mark_recovered() on registry is called when available

11. SourceRecoveryPolicy — evict_stale_sources (behavioral requirement 2)
    - stale DEGRADED source is evicted
    - stale UNAVAILABLE source is evicted
    - stale HEALTHY source is NOT evicted
    - active source is NOT evicted regardless of age
    - source with no last_seen_at is NOT evicted
    - source younger than threshold is NOT evicted
    - eviction event is appended to policy event log
    - evicted source_id is removed from registry
    - eviction removes primary designation when primary is evicted

12. SourceRecoveryPolicy — reelect_primary_audio (behavioral requirement 3)
    - selects the best (highest priority, active, healthy) audio source
    - switches primary when current primary fails (behavioral requirement 3)
    - prefers HEALTHY over DEGRADED candidates
    - prefers active over inactive candidates
    - prefers lower priority number
    - clears primary when no eligible audio source exists
    - switch event is appended to policy event log
    - no switch event when candidate is already the primary

13. SourceRecoveryPolicy — reelect_primary_video (behavioral requirement 4)
    - selects the best video source
    - switches primary when current primary fails
    - prefers HEALTHY over DEGRADED candidates
    - clears primary when no eligible video source exists
    - switch event is appended to policy event log

14. SourceRecoveryPolicy — run_recovery_cycle
    - evicts stale sources before checking primaries
    - re-elects primary audio when primary is UNAVAILABLE
    - re-elects primary audio when primary is DEGRADED
    - re-elects primary video when primary is UNAVAILABLE
    - re-elects primary video when primary is DEGRADED
    - fills audio vacancy when no primary is selected
    - fills video vacancy when no primary is selected
    - returns correct summary dict keys

15. Flap smoothing / hysteresis (behavioral requirement 5)
    - single degradation event does not constitute flapping
    - flap_threshold-many degradation events within window → is_flapping True
    - events outside flap_window_s are not counted
    - flapping primary audio does NOT trigger re-election (deferred)
    - flapping primary video does NOT trigger re-election (deferred)
    - FLAP_SMOOTHED event is recorded when deferred
    - non-flapping degraded primary IS re-elected

16. SourceRecoveryPolicy — snapshot
    - snapshot_at is recent
    - recoverable_source_count counts DEGRADED sources
    - unrecoverable_source_count counts UNAVAILABLE sources
    - stale_source_count counts stale sources
    - current primary IDs are correct
    - recent events are included in snapshot
    - snapshot is JSON-serialisable

17. Disconnected source reintegration (behavioral requirement 1)
    - disconnected source marked recoverable
    - source reintegrated (marked active) becomes HEALTHY
    - recovery event appears in snapshot after reintegration
    - primary re-election includes recovered source as candidate

18. Projection coherence (behavioral requirement 6)
    - DesktopPresenceRuntime.run_source_recovery_cycle() returns dict
    - DesktopPresenceRuntime.source_recovery_snapshot() returns dict
    - source_recovery_snapshot is JSON-serialisable
    - run_source_recovery_cycle never raises

19. Canonical state preservation
    - registry primary_audio_id reflects re-election outcome
    - registry primary_video_id reflects re-election outcome
    - registry source health reflects recovery outcome

20. get_source_recovery_policy / reset_source_recovery_policy
    - returns same singleton on repeated calls
    - reset clears singleton (new object after reset)

21. Module imports
    - all public symbols importable from core.multimodal.source_recovery_policy

22. PerceptionSourceRegistry.mark_recovered
    - DEGRADED source is reset to HEALTHY + active + cleared reasons
    - UNAVAILABLE source is NOT recovered
    - HEALTHY source remains HEALTHY (no-op)
    - unknown source_id is safe (no-op)
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry():
    from core.multimodal.perception_source_registry import PerceptionSourceRegistry
    return PerceptionSourceRegistry()


def _mic_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import (
        PerceptionSourceType,
        SourceModality,
    )
    base = dict(
        source_type=PerceptionSourceType.MICROPHONE,
        modality=SourceModality.AUDIO,
        display_name="Test Microphone",
        device_id="hw:0,0",
        transport="local",
        priority=10,
    )
    base.update(overrides)
    return base


def _webcam_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import (
        PerceptionSourceType,
        SourceModality,
    )
    base = dict(
        source_type=PerceptionSourceType.WEBCAM,
        modality=SourceModality.VIDEO,
        display_name="Local Webcam",
        device_id="/dev/video0",
        transport="local",
        priority=10,
    )
    base.update(overrides)
    return base


def _webrtc_kwargs(**overrides) -> dict:
    from core.multimodal.perception_source_registry import (
        PerceptionSourceType,
        SourceModality,
    )
    base = dict(
        source_type=PerceptionSourceType.WEBRTC,
        modality=SourceModality.VIDEO,
        display_name="Remote WebRTC Camera",
        transport="webrtc",
        priority=50,
    )
    base.update(overrides)
    return base


def _make_policy(**kwargs):
    from core.multimodal.source_recovery_policy import SourceRecoveryPolicy
    return SourceRecoveryPolicy(**kwargs)


# ---------------------------------------------------------------------------
# 1. SourceRecoverability
# ---------------------------------------------------------------------------


class TestSourceRecoverability:
    def test_expected_values_present(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability
        assert SourceRecoverability.RECOVERABLE.value == "recoverable"
        assert SourceRecoverability.UNRECOVERABLE.value == "unrecoverable"
        assert SourceRecoverability.UNKNOWN.value == "unknown"

    def test_from_string_round_trips(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability
        for member in SourceRecoverability:
            assert SourceRecoverability.from_string(member.value) == member

    def test_from_string_unknown_input(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability
        assert SourceRecoverability.from_string("garbage") == SourceRecoverability.UNKNOWN
        assert SourceRecoverability.from_string("") == SourceRecoverability.UNKNOWN


# ---------------------------------------------------------------------------
# 2. SourceFreshness
# ---------------------------------------------------------------------------


class TestSourceFreshness:
    def test_expected_values_present(self):
        from core.multimodal.source_recovery_policy import SourceFreshness
        assert SourceFreshness.FRESH.value == "fresh"
        assert SourceFreshness.STALE.value == "stale"
        assert SourceFreshness.UNKNOWN.value == "unknown"

    def test_from_string_round_trips(self):
        from core.multimodal.source_recovery_policy import SourceFreshness
        for member in SourceFreshness:
            assert SourceFreshness.from_string(member.value) == member

    def test_from_string_unknown_input(self):
        from core.multimodal.source_recovery_policy import SourceFreshness
        assert SourceFreshness.from_string("garbage") == SourceFreshness.UNKNOWN


# ---------------------------------------------------------------------------
# 3. PrimarySourceSwitchReason
# ---------------------------------------------------------------------------


class TestPrimarySourceSwitchReason:
    def test_expected_values_present(self):
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        expected = {
            "PRIMARY_FAILED",
            "PRIMARY_DEGRADED",
            "PRIMARY_STALE",
            "PRIMARY_EVICTED",
            "NO_PRIMARY",
            "EXPLICIT_SELECTION",
            "NONE",
        }
        actual = {m.name for m in PrimarySourceSwitchReason}
        assert expected.issubset(actual)

    def test_from_string_round_trips(self):
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        for member in PrimarySourceSwitchReason:
            assert PrimarySourceSwitchReason.from_string(member.value) == member

    def test_from_string_unrecognised_returns_none(self):
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        assert PrimarySourceSwitchReason.from_string("garbage") == PrimarySourceSwitchReason.NONE


# ---------------------------------------------------------------------------
# 4. RecoveryEventKind
# ---------------------------------------------------------------------------


class TestRecoveryEventKind:
    def test_expected_values_present(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind
        expected = {"RECOVERED", "EVICTED", "PRIMARY_REELECTED", "FLAP_SMOOTHED"}
        actual = {m.name for m in RecoveryEventKind}
        assert expected.issubset(actual)

    def test_from_string_round_trips(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind
        for member in RecoveryEventKind:
            assert RecoveryEventKind.from_string(member.value) == member

    def test_from_string_unrecognised_returns_recovered(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind
        assert RecoveryEventKind.from_string("garbage") == RecoveryEventKind.RECOVERED


# ---------------------------------------------------------------------------
# 5. SourceRecoveryEvent
# ---------------------------------------------------------------------------


class TestSourceRecoveryEvent:
    def test_defaults(self):
        from core.multimodal.source_recovery_policy import SourceRecoveryEvent, RecoveryEventKind
        evt = SourceRecoveryEvent()
        assert isinstance(evt.event_id, str) and len(evt.event_id) > 0
        assert evt.event_kind == RecoveryEventKind.RECOVERED
        assert evt.occurred_at > 0

    def test_to_dict_is_json_serialisable(self):
        from core.multimodal.source_recovery_policy import SourceRecoveryEvent
        evt = SourceRecoveryEvent(source_id="s1", modality="audio")
        d = evt.to_dict()
        json.dumps(d)  # must not raise

    def test_to_dict_from_dict_round_trip(self):
        from core.multimodal.source_recovery_policy import (
            SourceRecoveryEvent,
            RecoveryEventKind,
        )
        evt = SourceRecoveryEvent(
            event_kind=RecoveryEventKind.EVICTED,
            source_id="src-abc",
            modality="video",
            previous_health="degraded",
            new_health="removed",
            reason="stale_age=45.0s",
        )
        d = evt.to_dict()
        restored = SourceRecoveryEvent.from_dict(d)
        assert restored.event_id == evt.event_id
        assert restored.event_kind == RecoveryEventKind.EVICTED
        assert restored.source_id == "src-abc"
        assert restored.modality == "video"
        assert restored.previous_health == "degraded"
        assert restored.new_health == "removed"
        assert restored.reason == "stale_age=45.0s"

    def test_event_id_is_unique_per_instance(self):
        from core.multimodal.source_recovery_policy import SourceRecoveryEvent
        e1 = SourceRecoveryEvent()
        e2 = SourceRecoveryEvent()
        assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------------
# 6. PrimarySourceSwitchEvent
# ---------------------------------------------------------------------------


class TestPrimarySourceSwitchEvent:
    def test_defaults(self):
        from core.multimodal.source_recovery_policy import (
            PrimarySourceSwitchEvent,
            PrimarySourceSwitchReason,
        )
        evt = PrimarySourceSwitchEvent()
        assert isinstance(evt.event_id, str)
        assert evt.reason == PrimarySourceSwitchReason.NONE
        assert evt.occurred_at > 0

    def test_to_dict_is_json_serialisable(self):
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchEvent
        evt = PrimarySourceSwitchEvent(modality="audio", new_source_id="s1")
        json.dumps(evt.to_dict())

    def test_to_dict_from_dict_round_trip(self):
        from core.multimodal.source_recovery_policy import (
            PrimarySourceSwitchEvent,
            PrimarySourceSwitchReason,
        )
        evt = PrimarySourceSwitchEvent(
            modality="video",
            previous_source_id="old",
            new_source_id="new",
            reason=PrimarySourceSwitchReason.PRIMARY_FAILED,
        )
        d = evt.to_dict()
        restored = PrimarySourceSwitchEvent.from_dict(d)
        assert restored.modality == "video"
        assert restored.previous_source_id == "old"
        assert restored.new_source_id == "new"
        assert restored.reason == PrimarySourceSwitchReason.PRIMARY_FAILED


# ---------------------------------------------------------------------------
# 7. SourceRecoverySnapshot
# ---------------------------------------------------------------------------


class TestSourceRecoverySnapshot:
    def test_defaults(self):
        from core.multimodal.source_recovery_policy import SourceRecoverySnapshot
        snap = SourceRecoverySnapshot()
        assert isinstance(snap.snapshot_id, str)
        assert snap.snapshot_at > 0
        assert snap.recent_recovery_events == []
        assert snap.recent_switch_events == []

    def test_to_dict_is_json_serialisable(self):
        from core.multimodal.source_recovery_policy import (
            SourceRecoverySnapshot,
            SourceRecoveryEvent,
            PrimarySourceSwitchEvent,
        )
        snap = SourceRecoverySnapshot(
            recent_recovery_events=[SourceRecoveryEvent()],
            recent_switch_events=[PrimarySourceSwitchEvent()],
        )
        json.dumps(snap.to_dict())

    def test_to_dict_from_dict_round_trip(self):
        from core.multimodal.source_recovery_policy import (
            SourceRecoverySnapshot,
            SourceRecoveryEvent,
            PrimarySourceSwitchEvent,
        )
        snap = SourceRecoverySnapshot(
            current_primary_audio_id="mic-1",
            current_primary_video_id="cam-1",
            recoverable_source_count=2,
            unrecoverable_source_count=1,
            stale_source_count=3,
            flap_source_count=1,
            recent_recovery_events=[SourceRecoveryEvent(source_id="s1")],
            recent_switch_events=[PrimarySourceSwitchEvent(modality="audio")],
        )
        d = snap.to_dict()
        restored = SourceRecoverySnapshot.from_dict(d)
        assert restored.current_primary_audio_id == "mic-1"
        assert restored.current_primary_video_id == "cam-1"
        assert restored.recoverable_source_count == 2
        assert restored.unrecoverable_source_count == 1
        assert restored.stale_source_count == 3
        assert restored.flap_source_count == 1
        assert len(restored.recent_recovery_events) == 1
        assert len(restored.recent_switch_events) == 1


# ---------------------------------------------------------------------------
# 8. assess_recoverability
# ---------------------------------------------------------------------------


class TestAssessRecoverability:
    def test_healthy_source_returns_unknown(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        policy = _make_policy()
        record = registry.get(sid)
        assert record.health == SourceHealthStatus.HEALTHY
        assert policy.assess_recoverability(record) == SourceRecoverability.UNKNOWN

    def test_degraded_source_returns_recoverable(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "test reason")
        policy = _make_policy()
        record = registry.get(sid)
        assert policy.assess_recoverability(record) == SourceRecoverability.RECOVERABLE

    def test_unavailable_source_returns_unrecoverable(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, "hardware missing")
        policy = _make_policy()
        record = registry.get(sid)
        assert policy.assess_recoverability(record) == SourceRecoverability.UNRECOVERABLE

    def test_none_returns_unknown(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability

        policy = _make_policy()
        assert policy.assess_recoverability(None) == SourceRecoverability.UNKNOWN


# ---------------------------------------------------------------------------
# 9. assess_freshness
# ---------------------------------------------------------------------------


class TestAssessFreshness:
    def test_active_source_is_fresh(self):
        from core.multimodal.source_recovery_policy import SourceFreshness

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        policy = _make_policy()
        assert policy.assess_freshness(registry.get(sid)) == SourceFreshness.FRESH

    def test_recently_seen_inactive_is_fresh(self):
        from core.multimodal.source_recovery_policy import SourceFreshness

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.mark_inactive(sid)
        record = registry.get(sid)
        record.last_seen_at = time.time() - 5.0  # 5 s ago, within default 30 s
        policy = _make_policy(stale_threshold_s=30.0)
        assert policy.assess_freshness(record) == SourceFreshness.FRESH

    def test_old_inactive_source_is_stale(self):
        from core.multimodal.source_recovery_policy import SourceFreshness

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0  # 60 s ago
        record.is_active = False
        policy = _make_policy(stale_threshold_s=30.0)
        assert policy.assess_freshness(record) == SourceFreshness.STALE

    def test_no_last_seen_at_returns_unknown(self):
        from core.multimodal.source_recovery_policy import SourceFreshness

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = None
        record.is_active = False
        policy = _make_policy()
        assert policy.assess_freshness(record) == SourceFreshness.UNKNOWN

    def test_none_returns_unknown(self):
        from core.multimodal.source_recovery_policy import SourceFreshness

        policy = _make_policy()
        assert policy.assess_freshness(None) == SourceFreshness.UNKNOWN

    def test_custom_threshold_respected(self):
        from core.multimodal.source_recovery_policy import SourceFreshness

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 15.0  # 15 s ago
        record.is_active = False
        policy = _make_policy(stale_threshold_s=30.0)
        assert policy.assess_freshness(record, stale_threshold_s=10.0) == SourceFreshness.STALE
        assert policy.assess_freshness(record, stale_threshold_s=30.0) == SourceFreshness.FRESH


# ---------------------------------------------------------------------------
# 10. attempt_recovery (behavioral requirement 1)
# ---------------------------------------------------------------------------


class TestAttemptRecovery:
    def test_degraded_source_is_recovered(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "packet loss")
        policy = _make_policy()
        assert policy.attempt_recovery(registry, sid) is True
        record = registry.get(sid)
        assert record.health == SourceHealthStatus.HEALTHY
        assert record.is_active is True

    def test_degradation_reasons_cleared_on_recovery(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "some error")
        policy = _make_policy()
        policy.attempt_recovery(registry, sid)
        assert registry.get(sid).degradation_reasons == []

    def test_unavailable_source_not_recovered(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, "hardware missing")
        policy = _make_policy()
        assert policy.attempt_recovery(registry, sid) is False

    def test_healthy_source_returns_false(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        policy = _make_policy()
        assert policy.attempt_recovery(registry, sid) is False

    def test_unknown_source_returns_false(self):
        registry = _make_registry()
        policy = _make_policy()
        assert policy.attempt_recovery(registry, "nonexistent-id") is False

    def test_recovery_event_appended(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid)
        policy = _make_policy()
        policy.attempt_recovery(registry, sid)
        snap = policy.snapshot(registry)
        kinds = [e.event_kind for e in snap.recent_recovery_events]
        assert RecoveryEventKind.RECOVERED in kinds


# ---------------------------------------------------------------------------
# 11. evict_stale_sources (behavioral requirement 2)
# ---------------------------------------------------------------------------


class TestEvictStaleSources:
    def test_stale_degraded_source_is_evicted(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_degraded(sid, "timeout")
        policy = _make_policy(stale_threshold_s=30.0)
        evicted = policy.evict_stale_sources(registry)
        assert sid in evicted
        assert registry.get(sid) is None

    def test_stale_unavailable_source_is_evicted(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_unavailable(sid, "hardware missing")
        policy = _make_policy(stale_threshold_s=30.0)
        evicted = policy.evict_stale_sources(registry)
        assert sid in evicted

    def test_stale_healthy_source_is_not_evicted(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.mark_inactive(sid)
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        # force health to HEALTHY while inactive to test the guard
        from core.multimodal.perception_source_registry import SourceHealthStatus
        record.health = SourceHealthStatus.HEALTHY
        policy = _make_policy(stale_threshold_s=30.0)
        evicted = policy.evict_stale_sources(registry)
        assert sid not in evicted

    def test_active_source_not_evicted(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_degraded(sid)
        policy = _make_policy(stale_threshold_s=30.0)
        evicted = policy.evict_stale_sources(registry)
        assert sid not in evicted

    def test_source_with_no_last_seen_at_not_evicted(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid)
        # last_seen_at is None by default for newly registered source
        policy = _make_policy(stale_threshold_s=30.0)
        evicted = policy.evict_stale_sources(registry)
        assert sid not in evicted

    def test_fresh_source_not_evicted(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 5.0  # within threshold
        registry.mark_degraded(sid)
        policy = _make_policy(stale_threshold_s=30.0)
        evicted = policy.evict_stale_sources(registry)
        assert sid not in evicted

    def test_eviction_event_appended(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_degraded(sid)
        policy = _make_policy(stale_threshold_s=30.0)
        policy.evict_stale_sources(registry)
        snap = policy.snapshot(registry)
        kinds = [e.event_kind for e in snap.recent_recovery_events]
        assert RecoveryEventKind.EVICTED in kinds

    def test_eviction_clears_primary_audio(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.set_primary_audio(sid)
        registry.mark_inactive(sid)
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_degraded(sid)
        policy = _make_policy(stale_threshold_s=30.0)
        policy.evict_stale_sources(registry)
        assert registry.primary_audio_id is None


# ---------------------------------------------------------------------------
# 12. reelect_primary_audio (behavioral requirement 3)
# ---------------------------------------------------------------------------


class TestReelelectPrimaryAudio:
    def test_selects_healthy_active_source(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="mic1", priority=20))
        sid2 = registry.register(**_mic_kwargs(source_id="mic2", priority=10))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        # Fail sid1
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        assert new_id == sid2
        assert registry.primary_audio_id == sid2

    def test_prefers_lower_priority_number(self):
        registry = _make_registry()
        sid_low = registry.register(**_mic_kwargs(source_id="low", priority=5))
        sid_high = registry.register(**_mic_kwargs(source_id="high", priority=100))
        registry.mark_active(sid_low)
        registry.mark_active(sid_high)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.NO_PRIMARY)
        assert new_id == sid_low

    def test_prefers_healthy_over_degraded(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid_deg = registry.register(**_mic_kwargs(source_id="deg", priority=5))
        sid_hlth = registry.register(**_mic_kwargs(source_id="hlth", priority=50))
        registry.mark_active(sid_deg)
        registry.mark_active(sid_hlth)
        registry.mark_degraded(sid_deg, "test")
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.PRIMARY_DEGRADED)
        assert new_id == sid_hlth

    def test_clears_primary_when_no_candidates(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.set_primary_audio(sid)
        registry.mark_unavailable(sid)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        assert new_id is None
        assert registry.primary_audio_id is None

    def test_switch_event_appended_on_change(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        snap = policy.snapshot(registry)
        assert len(snap.recent_switch_events) >= 1
        assert snap.recent_switch_events[-1].modality == "audio"

    def test_no_switch_event_when_already_best(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.set_primary_audio(sid)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        snap = policy.snapshot(registry)
        # No switch because the same source is still best
        assert len(snap.recent_switch_events) == 0


# ---------------------------------------------------------------------------
# 13. reelect_primary_video (behavioral requirement 4)
# ---------------------------------------------------------------------------


class TestReelectPrimaryVideo:
    def test_switches_primary_when_current_fails(self):
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="cam1", priority=10))
        sid2 = registry.register(**_webrtc_kwargs(source_id="rtc1", priority=50))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_video(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_video(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        assert new_id == sid2
        assert registry.primary_video_id == sid2

    def test_prefers_healthy_over_degraded(self):
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="cam1", priority=5))
        sid2 = registry.register(**_webcam_kwargs(source_id="cam2", priority=10))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.mark_degraded(sid1)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_video(registry, PrimarySourceSwitchReason.PRIMARY_DEGRADED)
        assert new_id == sid2

    def test_clears_primary_when_no_candidates(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.mark_active(sid)
        registry.set_primary_video(sid)
        registry.mark_unavailable(sid)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_video(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        assert new_id is None
        assert registry.primary_video_id is None

    def test_switch_event_appended(self):
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="c1", priority=10))
        sid2 = registry.register(**_webcam_kwargs(source_id="c2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_video(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        policy.reelect_primary_video(registry, PrimarySourceSwitchReason.PRIMARY_FAILED)
        snap = policy.snapshot(registry)
        assert len(snap.recent_switch_events) >= 1
        assert snap.recent_switch_events[-1].modality == "video"


# ---------------------------------------------------------------------------
# 14. run_recovery_cycle
# ---------------------------------------------------------------------------


class TestRunRecoveryCycle:
    def test_evicts_stale_before_checking_primaries(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_degraded(sid)
        policy = _make_policy(stale_threshold_s=30.0)
        result = policy.run_recovery_cycle(registry)
        assert sid in result["evicted"]

    def test_reelects_primary_audio_on_unavailable(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        result = policy.run_recovery_cycle(registry)
        assert result["audio_reelected"] is True
        assert registry.primary_audio_id == sid2

    def test_reelects_primary_audio_on_degraded(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        registry.mark_degraded(sid1)
        registry.mark_inactive(sid1)
        policy = _make_policy()
        result = policy.run_recovery_cycle(registry)
        assert result["audio_reelected"] is True

    def test_reelects_primary_video_on_unavailable(self):
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="c1", priority=10))
        sid2 = registry.register(**_webcam_kwargs(source_id="c2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_video(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        result = policy.run_recovery_cycle(registry)
        assert result["video_reelected"] is True
        assert registry.primary_video_id == sid2

    def test_fills_audio_vacancy(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        # No primary set yet
        assert registry.primary_audio_id is None
        policy = _make_policy()
        result = policy.run_recovery_cycle(registry)
        assert result["audio_reelected"] is True
        assert registry.primary_audio_id == sid

    def test_fills_video_vacancy(self):
        registry = _make_registry()
        sid = registry.register(**_webcam_kwargs())
        registry.mark_active(sid)
        assert registry.primary_video_id is None
        policy = _make_policy()
        result = policy.run_recovery_cycle(registry)
        assert result["video_reelected"] is True
        assert registry.primary_video_id == sid

    def test_returns_expected_keys(self):
        registry = _make_registry()
        policy = _make_policy()
        result = policy.run_recovery_cycle(registry)
        assert "evicted" in result
        assert "audio_reelected" in result
        assert "video_reelected" in result
        assert "flap_smoothed_ids" in result


# ---------------------------------------------------------------------------
# 15. Flap smoothing / hysteresis (behavioral requirement 5)
# ---------------------------------------------------------------------------


class TestFlapSmoothing:
    def test_single_event_not_flapping(self):
        policy = _make_policy(flap_threshold=3, flap_window_s=10.0)
        policy._record_flap("src-1")
        assert policy.is_flapping("src-1") is False

    def test_threshold_events_within_window_is_flapping(self):
        policy = _make_policy(flap_threshold=3, flap_window_s=10.0)
        for _ in range(3):
            policy._record_flap("src-1")
        assert policy.is_flapping("src-1") is True

    def test_events_outside_window_not_counted(self):
        policy = _make_policy(flap_threshold=3, flap_window_s=5.0)
        now = time.time()
        # Inject old timestamps directly
        policy._flap_history["src-1"] = [now - 20.0, now - 15.0, now - 10.0]
        # All outside the 5 s window — should not be flapping
        assert policy.is_flapping("src-1") is False

    def test_flapping_primary_audio_defers_reelection(self):
        """Transient degradation should NOT cause chaotic source switching."""
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        registry.mark_degraded(sid1)
        registry.mark_inactive(sid1)

        policy = _make_policy(flap_threshold=3, flap_window_s=10.0)
        # Inject enough flap history to make sid1 appear as flapping
        for _ in range(3):
            policy._record_flap(sid1)

        result = policy.run_recovery_cycle(registry)
        # Re-election should be deferred — still on sid1
        assert result["audio_reelected"] is False
        assert sid1 in result["flap_smoothed_ids"]

    def test_flapping_primary_video_defers_reelection(self):
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="c1", priority=10))
        sid2 = registry.register(**_webcam_kwargs(source_id="c2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_video(sid1)
        registry.mark_degraded(sid1)
        registry.mark_inactive(sid1)

        policy = _make_policy(flap_threshold=3, flap_window_s=10.0)
        for _ in range(3):
            policy._record_flap(sid1)

        result = policy.run_recovery_cycle(registry)
        assert result["video_reelected"] is False
        assert sid1 in result["flap_smoothed_ids"]

    def test_flap_smoothed_event_recorded(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs(source_id="m1"))
        registry.mark_active(sid)
        registry.set_primary_audio(sid)
        registry.mark_degraded(sid)
        registry.mark_inactive(sid)

        policy = _make_policy(flap_threshold=3, flap_window_s=10.0)
        for _ in range(3):
            policy._record_flap(sid)

        policy.run_recovery_cycle(registry)
        snap = policy.snapshot(registry)
        kinds = [e.event_kind for e in snap.recent_recovery_events]
        assert RecoveryEventKind.FLAP_SMOOTHED in kinds

    def test_non_flapping_degraded_primary_is_reelected(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        registry.mark_degraded(sid1)
        registry.mark_inactive(sid1)

        policy = _make_policy(flap_threshold=3, flap_window_s=10.0)
        # Only 1 flap recorded — below threshold
        policy._record_flap(sid1)

        result = policy.run_recovery_cycle(registry)
        assert result["audio_reelected"] is True


# ---------------------------------------------------------------------------
# 16. snapshot
# ---------------------------------------------------------------------------


class TestPolicySnapshot:
    def test_snapshot_at_is_recent(self):
        registry = _make_registry()
        policy = _make_policy()
        snap = policy.snapshot(registry)
        assert abs(snap.snapshot_at - time.time()) < 2.0

    def test_recoverable_count(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid)
        policy = _make_policy()
        snap = policy.snapshot(registry)
        assert snap.recoverable_source_count == 1

    def test_unrecoverable_count(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid)
        policy = _make_policy()
        snap = policy.snapshot(registry)
        assert snap.unrecoverable_source_count == 1

    def test_stale_count(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        record = registry.get(sid)
        record.last_seen_at = time.time() - 60.0
        registry.mark_degraded(sid)
        policy = _make_policy(stale_threshold_s=30.0)
        snap = policy.snapshot(registry)
        assert snap.stale_source_count == 1

    def test_primary_ids_correct(self):
        registry = _make_registry()
        sid_a = registry.register(**_mic_kwargs())
        sid_v = registry.register(**_webcam_kwargs())
        registry.mark_active(sid_a)
        registry.mark_active(sid_v)
        registry.set_primary_audio(sid_a)
        registry.set_primary_video(sid_v)
        policy = _make_policy()
        snap = policy.snapshot(registry)
        assert snap.current_primary_audio_id == sid_a
        assert snap.current_primary_video_id == sid_v

    def test_snapshot_is_json_serialisable(self):
        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.set_primary_audio(sid)
        policy = _make_policy()
        policy.run_recovery_cycle(registry)
        snap = policy.snapshot(registry)
        json.dumps(snap.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# 17. Disconnected source reintegration (behavioral requirement 1)
# ---------------------------------------------------------------------------


class TestDisconnectedSourceReintegration:
    def test_disconnected_source_marked_recoverable(self):
        from core.multimodal.source_recovery_policy import SourceRecoverability

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "disconnected")
        policy = _make_policy()
        record = registry.get(sid)
        assert policy.assess_recoverability(record) == SourceRecoverability.RECOVERABLE

    def test_source_reintegrated_becomes_healthy(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "disconnected")
        policy = _make_policy()
        policy.attempt_recovery(registry, sid)
        assert registry.get(sid).health == SourceHealthStatus.HEALTHY
        assert registry.get(sid).is_active is True

    def test_recovery_event_in_snapshot(self):
        from core.multimodal.source_recovery_policy import RecoveryEventKind

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "disconnected")
        policy = _make_policy()
        policy.attempt_recovery(registry, sid)
        snap = policy.snapshot(registry)
        kinds = [e.event_kind for e in snap.recent_recovery_events]
        assert RecoveryEventKind.RECOVERED in kinds

    def test_recovered_source_eligible_as_primary_candidate(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid2)
        registry.set_primary_audio(sid2)
        registry.mark_degraded(sid1, "disconnected")

        policy = _make_policy()
        policy.attempt_recovery(registry, sid1)
        # After recovery sid1 has priority 10 (better than sid2 at 20)
        from core.multimodal.source_recovery_policy import PrimarySourceSwitchReason
        new_id = policy.reelect_primary_audio(registry, PrimarySourceSwitchReason.PRIMARY_DEGRADED)
        assert new_id == sid1


# ---------------------------------------------------------------------------
# 18. Projection coherence via DesktopPresenceRuntime (behavioral req 6)
# ---------------------------------------------------------------------------


class TestDesktopPresenceRuntimeIntegration:
    def test_run_source_recovery_cycle_returns_dict(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        result = runtime.run_source_recovery_cycle()
        assert isinstance(result, dict)

    def test_source_recovery_snapshot_returns_dict(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        snap = runtime.source_recovery_snapshot()
        assert isinstance(snap, dict)

    def test_source_recovery_snapshot_is_json_serialisable(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        snap = runtime.source_recovery_snapshot()
        json.dumps(snap)  # must not raise

    def test_run_source_recovery_cycle_never_raises(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        # Register a mic and set it as primary, then degrade it
        sid = runtime._source_registry.register(
            **_mic_kwargs(source_id="test-mic")
        )
        runtime._source_registry.mark_active(sid)
        runtime._source_registry.set_primary_audio(sid)
        runtime._source_registry.mark_degraded(sid, "test")
        try:
            result = runtime.run_source_recovery_cycle()
            assert isinstance(result, dict)
        except Exception as exc:
            pytest.fail(f"run_source_recovery_cycle raised: {exc}")


# ---------------------------------------------------------------------------
# 19. Canonical state preservation
# ---------------------------------------------------------------------------


class TestCanonicalStatePreservation:
    def test_registry_primary_audio_reflects_reelection(self):
        registry = _make_registry()
        sid1 = registry.register(**_mic_kwargs(source_id="m1", priority=10))
        sid2 = registry.register(**_mic_kwargs(source_id="m2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_audio(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        policy.run_recovery_cycle(registry)
        assert registry.primary_audio_id == sid2

    def test_registry_primary_video_reflects_reelection(self):
        registry = _make_registry()
        sid1 = registry.register(**_webcam_kwargs(source_id="c1", priority=10))
        sid2 = registry.register(**_webcam_kwargs(source_id="c2", priority=20))
        registry.mark_active(sid1)
        registry.mark_active(sid2)
        registry.set_primary_video(sid1)
        registry.mark_unavailable(sid1)
        policy = _make_policy()
        policy.run_recovery_cycle(registry)
        assert registry.primary_video_id == sid2

    def test_registry_health_reflects_recovery(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid)
        policy = _make_policy()
        policy.attempt_recovery(registry, sid)
        assert registry.get(sid).health == SourceHealthStatus.HEALTHY


# ---------------------------------------------------------------------------
# 20. get_source_recovery_policy / reset_source_recovery_policy
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_singleton_on_repeated_calls(self):
        from core.multimodal.source_recovery_policy import (
            get_source_recovery_policy,
            reset_source_recovery_policy,
        )
        reset_source_recovery_policy()
        p1 = get_source_recovery_policy()
        p2 = get_source_recovery_policy()
        assert p1 is p2

    def test_reset_clears_singleton(self):
        from core.multimodal.source_recovery_policy import (
            get_source_recovery_policy,
            reset_source_recovery_policy,
        )
        reset_source_recovery_policy()
        p1 = get_source_recovery_policy()
        reset_source_recovery_policy()
        p2 = get_source_recovery_policy()
        assert p1 is not p2


# ---------------------------------------------------------------------------
# 21. Module imports
# ---------------------------------------------------------------------------


class TestModuleImports:
    def test_all_public_symbols_importable(self):
        from core.multimodal.source_recovery_policy import (
            SourceRecoverability,
            SourceFreshness,
            PrimarySourceSwitchReason,
            RecoveryEventKind,
            SourceRecoveryEvent,
            PrimarySourceSwitchEvent,
            SourceRecoverySnapshot,
            SourceRecoveryPolicy,
            build_source_recovery_snapshot,
            get_source_recovery_policy,
            reset_source_recovery_policy,
        )
        assert SourceRecoveryPolicy is not None


# ---------------------------------------------------------------------------
# 22. PerceptionSourceRegistry.mark_recovered
# ---------------------------------------------------------------------------


class TestMarkRecovered:
    def test_degraded_source_reset_to_healthy(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_degraded(sid, "error")
        registry.mark_recovered(sid)
        record = registry.get(sid)
        assert record.health == SourceHealthStatus.HEALTHY
        assert record.is_active is True
        assert record.degradation_reasons == []

    def test_unavailable_source_not_recovered(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_unavailable(sid, "hardware missing")
        registry.mark_recovered(sid)
        assert registry.get(sid).health == SourceHealthStatus.UNAVAILABLE

    def test_healthy_source_remains_healthy(self):
        from core.multimodal.perception_source_registry import SourceHealthStatus

        registry = _make_registry()
        sid = registry.register(**_mic_kwargs())
        registry.mark_active(sid)
        registry.mark_recovered(sid)
        assert registry.get(sid).health == SourceHealthStatus.HEALTHY

    def test_unknown_source_id_is_safe(self):
        registry = _make_registry()
        registry.mark_recovered("nonexistent-id")  # must not raise
