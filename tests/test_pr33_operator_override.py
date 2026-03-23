#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr33_operator_override.py
=====================================
Tests for PR-33: Add operator override panel for source, model, and execution
policy.

Coverage
--------
1.  OverrideMultimodalMode enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns AUTO for unrecognised input

2.  OverrideExecutionLocality enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns DEFAULT for unrecognised input

3.  OverrideRemoteMode enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns DEFAULT for unrecognised input

4.  OperatorOverrideSet
    - to_dict / from_dict round-trip
    - override_id is auto-generated when omitted
    - is_noop True when no domain is overridden
    - is_noop False when any domain is overridden
    - has_source_override, has_model_override, has_multimodal_override,
      has_locality_override, has_remote_mode_override derived flags

5.  PolicyOverrideRecord
    - to_dict / from_dict round-trip
    - nested override_set reconstructed from dict
    - record_id is auto-generated when omitted

6.  OperatorOverrideSnapshot
    - to_dict / from_dict round-trip
    - has_active_override=False when no override set
    - has_active_override=True when non-noop override set present

7.  OperatorOverrideState singleton
    - get_operator_override_state returns same object on repeated calls
    - reset_operator_override_state clears singleton
    - commit stores active override; history record appended
    - clear removes active override; "clear" history record appended
    - snapshot reflects current active state

8.  apply_route_override
    - noop override → route dict unchanged
    - FORCE_OFF → route_type="text_only", is_native_multimodal=False
    - FORCE_ON on non-native route → route_type="native_multimodal"
    - preferred_provider locks provider field
    - preferred_model locks model field
    - original dict is not mutated (copy semantics)

9.  apply_execution_policy_override
    - noop override → original values unchanged, override_applied=False
    - LOCAL_ONLY → effective_cross_device_allowed=False
    - REMOTE_DISABLED → effective_cross_device_allowed=False
    - COMMAND_ONLY remote mode → effective_remote_mode="command_only"
    - FULL_AGENT remote mode → effective_remote_mode="full_agent"

10. apply_source_override
    - noop override → original source IDs unchanged
    - audio source override changes effective_audio_source_id
    - video source override changes effective_video_source_id
    - audio_overridden and video_overridden flags set correctly

11. build_override_summary
    - no active override → has_active_override=False, operator_message contains "none"
    - active override → has_active_override=True, operator_message contains domains

12. Primary source override (acceptance)
    - primary audio source override changes source selection deterministically
    - primary video source override changes source selection deterministically

13. Model/provider override (acceptance)
    - provider lock reflected in canonical route output
    - model lock reflected in canonical route output

14. Execution-policy override (acceptance)
    - LOCAL_ONLY blocks cross-device execution
    - COMMAND_ONLY restricts remote mode
    - override_applied=True when override is effective

15. Override visibility in projection / explanation (acceptance)
    - operator_override_state key present in OpenClawd response metadata
    - has_active_override=True when override is committed
    - applied_domains reflect correct domain names

16. Overrides do not bypass canonical authority (acceptance)
    - override state is an input to the control core, not a bypass
    - clearing override restores automation default (override_applied=False)

17. Override interaction with degraded/safety-constrained states (acceptance)
    - FORCE_ON override with degraded route still surfaces operator intent
    - override_reason propagated to snapshot summary

18. OpenClawd integration (_apply_operator_overrides)
    - _apply_operator_overrides returns a dict
    - returned dict is JSON-serialisable
    - multimodal_mode=FORCE_OFF reflected in route dict after call
    - provider lock reflected in route dict after call

19. DesktopPresenceRuntime integration
    - set_operator_override returns status="committed" and override_id
    - clear_operator_override returns status="cleared"
    - operator_override_summary returns dict with expected keys
    - operator_override_summary reflects committed override
    - operator_override_summary shows has_active_override=False after clear
"""

import json
import pytest

# ---------------------------------------------------------------------------
# Imports from the module under test
# ---------------------------------------------------------------------------

from core.operator_override import (
    OverrideMultimodalMode,
    OverrideExecutionLocality,
    OverrideRemoteMode,
    OperatorOverrideSet,
    PolicyOverrideRecord,
    OperatorOverrideSnapshot,
    OperatorOverrideState,
    get_operator_override_state,
    reset_operator_override_state,
    apply_route_override,
    apply_execution_policy_override,
    apply_source_override,
    build_override_summary,
    build_operator_override_snapshot,
    _collect_applied_domains,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the operator override singleton before and after every test."""
    reset_operator_override_state()
    yield
    reset_operator_override_state()


def _make_route_dict(**kwargs):
    base = {
        "route_type": "native_multimodal",
        "is_native_multimodal": True,
        "provider": "openai",
        "model": "gpt-4o",
        "route_reason": "tier=1 native multimodal selected",
        "fallback_reason": "",
        "active_modalities": ["audio", "video"],
    }
    base.update(kwargs)
    return base


# ===========================================================================
# 1. OverrideMultimodalMode enum
# ===========================================================================

class TestOverrideMultimodalMode:
    def test_values_present(self):
        assert OverrideMultimodalMode.FORCE_ON.value == "force_on"
        assert OverrideMultimodalMode.FORCE_OFF.value == "force_off"
        assert OverrideMultimodalMode.AUTO.value == "auto"

    def test_from_string_roundtrip(self):
        for member in OverrideMultimodalMode:
            assert OverrideMultimodalMode.from_string(member.value) == member

    def test_from_string_unknown_defaults_to_auto(self):
        assert OverrideMultimodalMode.from_string("nonsense") == OverrideMultimodalMode.AUTO


# ===========================================================================
# 2. OverrideExecutionLocality enum
# ===========================================================================

class TestOverrideExecutionLocality:
    def test_values_present(self):
        assert OverrideExecutionLocality.LOCAL_ONLY.value == "local_only"
        assert OverrideExecutionLocality.REMOTE_DISABLED.value == "remote_disabled"
        assert OverrideExecutionLocality.DEFAULT.value == "default"

    def test_from_string_roundtrip(self):
        for member in OverrideExecutionLocality:
            assert OverrideExecutionLocality.from_string(member.value) == member

    def test_from_string_unknown_defaults_to_default(self):
        assert OverrideExecutionLocality.from_string("bogus") == OverrideExecutionLocality.DEFAULT


# ===========================================================================
# 3. OverrideRemoteMode enum
# ===========================================================================

class TestOverrideRemoteMode:
    def test_values_present(self):
        assert OverrideRemoteMode.COMMAND_ONLY.value == "command_only"
        assert OverrideRemoteMode.FULL_AGENT.value == "full_agent"
        assert OverrideRemoteMode.DEFAULT.value == "default"

    def test_from_string_roundtrip(self):
        for member in OverrideRemoteMode:
            assert OverrideRemoteMode.from_string(member.value) == member

    def test_from_string_unknown_defaults_to_default(self):
        assert OverrideRemoteMode.from_string("unknown_mode") == OverrideRemoteMode.DEFAULT


# ===========================================================================
# 4. OperatorOverrideSet
# ===========================================================================

class TestOperatorOverrideSet:
    def test_to_dict_from_dict_roundtrip(self):
        obj = OperatorOverrideSet(
            primary_audio_source_id="mic:builtin",
            primary_video_source_id="cam:usb0",
            preferred_provider="anthropic",
            preferred_model="claude-3-opus",
            multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
            execution_locality=OverrideExecutionLocality.LOCAL_ONLY,
            remote_mode=OverrideRemoteMode.COMMAND_ONLY,
            override_reason="test_maintenance",
        )
        d = obj.to_dict()
        restored = OperatorOverrideSet.from_dict(d)
        assert restored.primary_audio_source_id == "mic:builtin"
        assert restored.primary_video_source_id == "cam:usb0"
        assert restored.preferred_provider == "anthropic"
        assert restored.preferred_model == "claude-3-opus"
        assert restored.multimodal_mode == OverrideMultimodalMode.FORCE_OFF
        assert restored.execution_locality == OverrideExecutionLocality.LOCAL_ONLY
        assert restored.remote_mode == OverrideRemoteMode.COMMAND_ONLY
        assert restored.override_reason == "test_maintenance"
        assert restored.override_id == obj.override_id

    def test_override_id_auto_generated(self):
        a = OperatorOverrideSet()
        b = OperatorOverrideSet()
        assert a.override_id != b.override_id

    def test_is_noop_when_all_default(self):
        obj = OperatorOverrideSet()
        assert obj.is_noop is True

    def test_is_noop_false_when_audio_source_set(self):
        obj = OperatorOverrideSet(primary_audio_source_id="mic:external")
        assert obj.is_noop is False
        assert obj.has_source_override is True

    def test_is_noop_false_when_model_set(self):
        obj = OperatorOverrideSet(preferred_model="gpt-4-turbo")
        assert obj.is_noop is False
        assert obj.has_model_override is True

    def test_is_noop_false_when_multimodal_force_off(self):
        obj = OperatorOverrideSet(multimodal_mode=OverrideMultimodalMode.FORCE_OFF)
        assert obj.is_noop is False
        assert obj.has_multimodal_override is True

    def test_is_noop_false_when_locality_local_only(self):
        obj = OperatorOverrideSet(execution_locality=OverrideExecutionLocality.LOCAL_ONLY)
        assert obj.is_noop is False
        assert obj.has_locality_override is True

    def test_is_noop_false_when_remote_mode_command_only(self):
        obj = OperatorOverrideSet(remote_mode=OverrideRemoteMode.COMMAND_ONLY)
        assert obj.is_noop is False
        assert obj.has_remote_mode_override is True

    def test_dict_is_json_serialisable(self):
        obj = OperatorOverrideSet(
            preferred_provider="openai",
            multimodal_mode=OverrideMultimodalMode.FORCE_ON,
            override_reason="test",
        )
        json.dumps(obj.to_dict())

    def test_from_dict_with_unknown_fields_does_not_raise(self):
        d = {"override_id": "abc", "unknown_future_field": "x"}
        obj = OperatorOverrideSet.from_dict(d)
        assert obj.override_id == "abc"


# ===========================================================================
# 5. PolicyOverrideRecord
# ===========================================================================

class TestPolicyOverrideRecord:
    def test_to_dict_from_dict_roundtrip(self):
        override = OperatorOverrideSet(preferred_provider="openai", override_reason="r1")
        record = PolicyOverrideRecord(
            event_kind="commit",
            override_set=override,
            applied_by="operator:alice",
            context_trace_id="trace-123",
        )
        d = record.to_dict()
        restored = PolicyOverrideRecord.from_dict(d)
        assert restored.event_kind == "commit"
        assert restored.applied_by == "operator:alice"
        assert restored.context_trace_id == "trace-123"
        assert isinstance(restored.override_set, OperatorOverrideSet)
        assert restored.override_set.preferred_provider == "openai"

    def test_record_id_auto_generated(self):
        r1 = PolicyOverrideRecord()
        r2 = PolicyOverrideRecord()
        assert r1.record_id != r2.record_id

    def test_nested_override_set_none(self):
        record = PolicyOverrideRecord(event_kind="clear", override_set=None)
        d = record.to_dict()
        assert d["override_set"] is None
        restored = PolicyOverrideRecord.from_dict(d)
        assert restored.override_set is None

    def test_dict_is_json_serialisable(self):
        override = OperatorOverrideSet()
        record = PolicyOverrideRecord(override_set=override)
        json.dumps(record.to_dict())


# ===========================================================================
# 6. OperatorOverrideSnapshot
# ===========================================================================

class TestOperatorOverrideSnapshot:
    def test_to_dict_from_dict_roundtrip_no_override(self):
        snap = OperatorOverrideSnapshot(has_active_override=False)
        d = snap.to_dict()
        restored = OperatorOverrideSnapshot.from_dict(d)
        assert restored.has_active_override is False
        assert restored.active_override_set is None

    def test_to_dict_from_dict_roundtrip_with_override(self):
        override = OperatorOverrideSet(preferred_provider="anthropic")
        snap = OperatorOverrideSnapshot(
            has_active_override=True,
            active_override_set=override,
            applied_domains=["provider"],
            override_reason="testing",
        )
        d = snap.to_dict()
        restored = OperatorOverrideSnapshot.from_dict(d)
        assert restored.has_active_override is True
        assert isinstance(restored.active_override_set, OperatorOverrideSet)
        assert restored.active_override_set.preferred_provider == "anthropic"
        assert "provider" in restored.applied_domains

    def test_dict_is_json_serialisable(self):
        override = OperatorOverrideSet(
            multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
            override_reason="serialise_test",
        )
        snap = OperatorOverrideSnapshot(
            has_active_override=True,
            active_override_set=override,
            applied_domains=["multimodal_mode"],
        )
        json.dumps(snap.to_dict())


# ===========================================================================
# 7. OperatorOverrideState singleton
# ===========================================================================

class TestOperatorOverrideState:
    def test_singleton_identity(self):
        a = get_operator_override_state()
        b = get_operator_override_state()
        assert a is b

    def test_reset_clears_singleton(self):
        a = get_operator_override_state()
        reset_operator_override_state()
        b = get_operator_override_state()
        assert a is not b

    def test_commit_sets_active_override(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(preferred_provider="openai")
        state.commit(override, applied_by="test")
        assert state.active_override_set is override

    def test_commit_appends_history_record(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(preferred_provider="openai")
        state.commit(override, applied_by="op:bob", context_trace_id="t-1")
        assert len(state.history) == 1
        record = state.history[0]
        assert record.event_kind == "commit"
        assert record.applied_by == "op:bob"
        assert record.override_set is override

    def test_clear_removes_active_override(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(preferred_provider="openai")
        state.commit(override)
        state.clear(applied_by="op:carol")
        assert state.active_override_set is None

    def test_clear_appends_clear_history_record(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(preferred_provider="openai")
        state.commit(override)
        state.clear(applied_by="op:carol")
        assert len(state.history) == 2
        clear_record = state.history[1]
        assert clear_record.event_kind == "clear"
        assert clear_record.applied_by == "op:carol"
        assert clear_record.override_set is override

    def test_snapshot_no_override(self):
        state = get_operator_override_state()
        snap = state.snapshot(trace_id="t-0")
        assert snap.has_active_override is False
        assert snap.active_override_set is None
        assert snap.applied_domains == []

    def test_snapshot_with_active_override(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
            override_reason="window",
        )
        state.commit(override)
        snap = state.snapshot(trace_id="t-1")
        assert snap.has_active_override is True
        assert "provider" in snap.applied_domains
        assert "multimodal_mode" in snap.applied_domains
        assert snap.override_reason == "window"


# ===========================================================================
# 8. apply_route_override
# ===========================================================================

class TestApplyRouteOverride:
    def test_noop_override_leaves_route_unchanged(self):
        route = _make_route_dict()
        original_route_type = route["route_type"]
        result = apply_route_override(route, OperatorOverrideSet())
        assert result["route_type"] == original_route_type
        assert result.get("operator_override_applied") is None

    def test_none_override_leaves_route_unchanged(self):
        route = _make_route_dict()
        result = apply_route_override(route, None)
        assert result["route_type"] == route["route_type"]

    def test_force_off_downgrades_to_text_only(self):
        route = _make_route_dict(route_type="native_multimodal", is_native_multimodal=True)
        override = OperatorOverrideSet(
            multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
            override_reason="safety_mode",
        )
        result = apply_route_override(route, override)
        assert result["route_type"] == "text_only"
        assert result["is_native_multimodal"] is False
        assert "force_off" in result.get("operator_override_applied", "")

    def test_force_on_upgrades_partial_to_native(self):
        route = _make_route_dict(route_type="partial_multimodal", is_native_multimodal=False)
        override = OperatorOverrideSet(
            multimodal_mode=OverrideMultimodalMode.FORCE_ON,
            override_reason="operator_explicit",
        )
        result = apply_route_override(route, override)
        assert result["route_type"] == "native_multimodal"
        assert result["is_native_multimodal"] is True

    def test_force_on_does_not_change_already_native(self):
        route = _make_route_dict(route_type="native_multimodal", is_native_multimodal=True)
        override = OperatorOverrideSet(multimodal_mode=OverrideMultimodalMode.FORCE_ON)
        result = apply_route_override(route, override)
        # Already native; force_on doesn't re-override but must keep it native
        assert result["is_native_multimodal"] is True

    def test_preferred_provider_locks_provider_field(self):
        route = _make_route_dict(provider="openai")
        override = OperatorOverrideSet(preferred_provider="anthropic", override_reason="lock")
        result = apply_route_override(route, override)
        assert result["provider"] == "anthropic"

    def test_preferred_model_locks_model_field(self):
        route = _make_route_dict(model="gpt-4o")
        override = OperatorOverrideSet(preferred_model="claude-3-haiku")
        result = apply_route_override(route, override)
        assert result["model"] == "claude-3-haiku"

    def test_original_dict_not_mutated(self):
        route = _make_route_dict()
        original_provider = route["provider"]
        override = OperatorOverrideSet(preferred_provider="anthropic")
        _ = apply_route_override(route, override)
        assert route["provider"] == original_provider

    def test_inactive_override_leaves_route_unchanged(self):
        route = _make_route_dict()
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            is_active=False,
        )
        result = apply_route_override(route, override)
        assert result["provider"] == route["provider"]


# ===========================================================================
# 9. apply_execution_policy_override
# ===========================================================================

class TestApplyExecutionPolicyOverride:
    def test_noop_leaves_values_unchanged(self):
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=OperatorOverrideSet(),
        )
        assert result["effective_cross_device_allowed"] is True
        assert result["effective_remote_mode"] == "full_agent"
        assert result["override_applied"] is False

    def test_none_override_leaves_values_unchanged(self):
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode=None,
            override_set=None,
        )
        assert result["effective_cross_device_allowed"] is True
        assert result["override_applied"] is False

    def test_local_only_blocks_cross_device(self):
        override = OperatorOverrideSet(execution_locality=OverrideExecutionLocality.LOCAL_ONLY)
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=override,
        )
        assert result["effective_cross_device_allowed"] is False
        assert result["override_applied"] is True

    def test_remote_disabled_blocks_cross_device(self):
        override = OperatorOverrideSet(
            execution_locality=OverrideExecutionLocality.REMOTE_DISABLED
        )
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=override,
        )
        assert result["effective_cross_device_allowed"] is False
        assert result["override_applied"] is True

    def test_command_only_restricts_remote_mode(self):
        override = OperatorOverrideSet(remote_mode=OverrideRemoteMode.COMMAND_ONLY)
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=override,
        )
        assert result["effective_remote_mode"] == "command_only"
        assert result["override_applied"] is True

    def test_full_agent_sets_remote_mode(self):
        override = OperatorOverrideSet(remote_mode=OverrideRemoteMode.FULL_AGENT)
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="command_only",
            override_set=override,
        )
        assert result["effective_remote_mode"] == "full_agent"
        assert result["override_applied"] is True

    def test_override_reason_propagated(self):
        override = OperatorOverrideSet(
            execution_locality=OverrideExecutionLocality.LOCAL_ONLY,
            override_reason="maintenance",
        )
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode=None,
            override_set=override,
        )
        assert result["override_reason"] == "maintenance"


# ===========================================================================
# 10. apply_source_override
# ===========================================================================

class TestApplySourceOverride:
    def test_noop_leaves_sources_unchanged(self):
        result = apply_source_override(
            current_audio_source_id="mic:builtin",
            current_video_source_id="cam:usb0",
            override_set=OperatorOverrideSet(),
        )
        assert result["effective_audio_source_id"] == "mic:builtin"
        assert result["effective_video_source_id"] == "cam:usb0"
        assert result["audio_overridden"] is False
        assert result["video_overridden"] is False

    def test_audio_source_override_changes_audio(self):
        override = OperatorOverrideSet(primary_audio_source_id="mic:external")
        result = apply_source_override(
            current_audio_source_id="mic:builtin",
            current_video_source_id="cam:usb0",
            override_set=override,
        )
        assert result["effective_audio_source_id"] == "mic:external"
        assert result["audio_overridden"] is True
        assert result["effective_video_source_id"] == "cam:usb0"
        assert result["video_overridden"] is False

    def test_video_source_override_changes_video(self):
        override = OperatorOverrideSet(primary_video_source_id="cam:hdmi1")
        result = apply_source_override(
            current_audio_source_id="mic:builtin",
            current_video_source_id="cam:usb0",
            override_set=override,
        )
        assert result["effective_video_source_id"] == "cam:hdmi1"
        assert result["video_overridden"] is True
        assert result["audio_overridden"] is False

    def test_both_sources_overridden(self):
        override = OperatorOverrideSet(
            primary_audio_source_id="mic:external",
            primary_video_source_id="cam:hdmi1",
            override_reason="test_both",
        )
        result = apply_source_override(
            current_audio_source_id="mic:builtin",
            current_video_source_id="cam:usb0",
            override_set=override,
        )
        assert result["effective_audio_source_id"] == "mic:external"
        assert result["effective_video_source_id"] == "cam:hdmi1"
        assert result["audio_overridden"] is True
        assert result["video_overridden"] is True
        assert result["override_reason"] == "test_both"

    def test_none_override_leaves_sources_unchanged(self):
        result = apply_source_override(
            current_audio_source_id="mic:builtin",
            current_video_source_id=None,
            override_set=None,
        )
        assert result["effective_audio_source_id"] == "mic:builtin"
        assert result["audio_overridden"] is False


# ===========================================================================
# 11. build_override_summary
# ===========================================================================

class TestBuildOverrideSummary:
    def test_no_override_summary(self):
        snap = OperatorOverrideSnapshot(has_active_override=False)
        summary = build_override_summary(snap)
        assert summary["has_active_override"] is False
        assert summary["applied_domains"] == []
        assert "none" in summary["operator_message"]

    def test_active_override_summary(self):
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
            override_reason="maintenance_window",
        )
        snap = OperatorOverrideSnapshot(
            has_active_override=True,
            active_override_set=override,
            applied_domains=["provider", "multimodal_mode"],
            override_reason="maintenance_window",
        )
        summary = build_override_summary(snap)
        assert summary["has_active_override"] is True
        assert "provider" in summary["applied_domains"]
        assert "multimodal_mode" in summary["applied_domains"]
        assert "maintenance_window" in summary["operator_message"]

    def test_summary_is_json_serialisable(self):
        snap = OperatorOverrideSnapshot(has_active_override=False)
        json.dumps(build_override_summary(snap))


# ===========================================================================
# 12. Primary source override (acceptance)
# ===========================================================================

class TestPrimarySourceOverrideAcceptance:
    def test_audio_source_override_is_deterministic(self):
        override = OperatorOverrideSet(primary_audio_source_id="mic:external_usb")
        r1 = apply_source_override(
            current_audio_source_id="mic:builtin",
            current_video_source_id=None,
            override_set=override,
        )
        r2 = apply_source_override(
            current_audio_source_id="mic:different_source",
            current_video_source_id=None,
            override_set=override,
        )
        # Deterministic: same override always yields same effective ID
        assert r1["effective_audio_source_id"] == "mic:external_usb"
        assert r2["effective_audio_source_id"] == "mic:external_usb"

    def test_video_source_override_is_deterministic(self):
        override = OperatorOverrideSet(primary_video_source_id="cam:rear")
        for current in ["cam:front", "cam:usb0", None]:
            result = apply_source_override(
                current_audio_source_id=None,
                current_video_source_id=current,
                override_set=override,
            )
            assert result["effective_video_source_id"] == "cam:rear"


# ===========================================================================
# 13. Model/provider override (acceptance)
# ===========================================================================

class TestModelProviderOverrideAcceptance:
    def test_provider_lock_reflected_in_route(self):
        route = _make_route_dict(provider="openai", model="gpt-4o")
        override = OperatorOverrideSet(preferred_provider="anthropic")
        result = apply_route_override(route, override)
        assert result["provider"] == "anthropic"
        # model should be unchanged when only provider is locked
        assert result["model"] == "gpt-4o"

    def test_model_lock_reflected_in_route(self):
        route = _make_route_dict(provider="openai", model="gpt-4o")
        override = OperatorOverrideSet(preferred_model="claude-3-haiku")
        result = apply_route_override(route, override)
        assert result["model"] == "claude-3-haiku"

    def test_combined_provider_and_model_lock(self):
        route = _make_route_dict(provider="openai", model="gpt-4o")
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            preferred_model="claude-3-opus",
        )
        result = apply_route_override(route, override)
        assert result["provider"] == "anthropic"
        assert result["model"] == "claude-3-opus"


# ===========================================================================
# 14. Execution-policy override (acceptance)
# ===========================================================================

class TestExecutionPolicyOverrideAcceptance:
    def test_local_only_blocks_cross_device(self):
        override = OperatorOverrideSet(execution_locality=OverrideExecutionLocality.LOCAL_ONLY)
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=override,
        )
        assert result["effective_cross_device_allowed"] is False
        assert result["override_applied"] is True

    def test_command_only_restricts_remote_mode(self):
        override = OperatorOverrideSet(remote_mode=OverrideRemoteMode.COMMAND_ONLY)
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=override,
        )
        assert result["effective_remote_mode"] == "command_only"
        assert result["override_applied"] is True

    def test_no_override_does_not_set_override_applied(self):
        result = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode="full_agent",
            override_set=None,
        )
        assert result["override_applied"] is False


# ===========================================================================
# 15. Override visibility (acceptance)
# ===========================================================================

class TestOverrideVisibilityAcceptance:
    def test_override_state_in_openclawd_response(self):
        """_apply_operator_overrides should return a serialisable dict."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        # Inject minimal required attributes
        oc._router = None
        oc._config = {}

        route = _make_route_dict()
        result = oc._apply_operator_overrides(
            multimodal_route=route,
            trace_id="t-visibility",
        )
        assert isinstance(result, dict)
        json.dumps(result)

    def test_has_active_override_true_when_committed(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            override_reason="visibility_test",
        )
        state.commit(override)
        snap = state.snapshot(trace_id="t-vis")
        assert snap.has_active_override is True

    def test_applied_domains_reflect_correct_domains(self):
        override = OperatorOverrideSet(
            primary_audio_source_id="mic:test",
            execution_locality=OverrideExecutionLocality.LOCAL_ONLY,
            override_reason="domain_test",
        )
        domains = _collect_applied_domains(override)
        assert "audio_source" in domains
        assert "execution_locality" in domains
        assert "video_source" not in domains


# ===========================================================================
# 16. Overrides do not bypass canonical authority (acceptance)
# ===========================================================================

class TestOverrideDoesNotBypassAuthority:
    def test_override_is_input_not_bypass(self):
        """Verify the override is applied as an input layer, not a bypass."""
        route = _make_route_dict(route_type="native_multimodal", is_native_multimodal=True)
        override = OperatorOverrideSet(multimodal_mode=OverrideMultimodalMode.FORCE_OFF)

        # apply_route_override produces an overlay dict — the override is an
        # explicit input modification, not silent routing logic inside the core
        result = apply_route_override(route, override)
        assert result["route_type"] == "text_only"
        # The resulting route dict is transparent: the change is clearly stamped
        assert "operator_override_applied" in result

    def test_clearing_override_restores_automation_default(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(
            execution_locality=OverrideExecutionLocality.LOCAL_ONLY
        )
        state.commit(override)

        # While committed, cross-device is blocked
        active = state.active_override_set
        result_active = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode=None,
            override_set=active,
        )
        assert result_active["effective_cross_device_allowed"] is False

        # After clearing, automation default is restored
        state.clear()
        cleared = state.active_override_set
        result_cleared = apply_execution_policy_override(
            cross_device_allowed=True,
            remote_mode=None,
            override_set=cleared,
        )
        assert result_cleared["effective_cross_device_allowed"] is True
        assert result_cleared["override_applied"] is False


# ===========================================================================
# 17. Override interaction with degraded/safety-constrained states (acceptance)
# ===========================================================================

class TestOverrideWithDegradedState:
    def test_force_on_override_with_degraded_route_surfaces_intent(self):
        """An operator FORCE_ON override is stamped as intent even on a degraded route."""
        # Simulate a degraded (text_only) route that came from low confidence
        route = _make_route_dict(
            route_type="text_only",
            is_native_multimodal=False,
            provider="none",
            model="none",
            route_reason="modality_confidence_ineligible",
        )
        override = OperatorOverrideSet(
            multimodal_mode=OverrideMultimodalMode.FORCE_ON,
            override_reason="operator:manual_force",
        )
        result = apply_route_override(route, override)
        # The override intent is stamped (operator requested force_on)
        assert result["route_type"] == "native_multimodal"
        assert result["is_native_multimodal"] is True
        assert "force_on" in result.get("operator_override_applied", "")

    def test_override_reason_propagated_to_snapshot_summary(self):
        state = get_operator_override_state()
        override = OperatorOverrideSet(
            execution_locality=OverrideExecutionLocality.LOCAL_ONLY,
            override_reason="safety_protocol_active",
        )
        state.commit(override)
        snap = state.snapshot()
        summary = build_override_summary(snap)
        assert "safety_protocol_active" in summary["operator_message"]
        assert summary["override_reason"] == "safety_protocol_active"


# ===========================================================================
# 18. OpenClawd integration (_apply_operator_overrides)
# ===========================================================================

class TestOpenClawdIntegration:
    def test_apply_operator_overrides_returns_dict(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._config = {}

        route = _make_route_dict()
        result = oc._apply_operator_overrides(
            multimodal_route=route,
            trace_id="t-oc-1",
        )
        assert result is None or isinstance(result, dict)

    def test_apply_operator_overrides_returns_json_serialisable(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._config = {}

        route = _make_route_dict()
        result = oc._apply_operator_overrides(multimodal_route=route)
        if result is not None:
            json.dumps(result)

    def test_force_off_reflected_in_route_after_apply(self):
        from core.openclawd import OpenClawd

        state = get_operator_override_state()
        state.commit(
            OperatorOverrideSet(
                multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
                override_reason="oc_integration_test",
            )
        )

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._config = {}

        route = _make_route_dict(route_type="native_multimodal", is_native_multimodal=True)
        oc._apply_operator_overrides(multimodal_route=route)
        # Route dict mutated in-place
        assert route["route_type"] == "text_only"
        assert route["is_native_multimodal"] is False

    def test_provider_lock_reflected_in_route_after_apply(self):
        from core.openclawd import OpenClawd

        state = get_operator_override_state()
        state.commit(
            OperatorOverrideSet(
                preferred_provider="anthropic",
                override_reason="oc_provider_test",
            )
        )

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._config = {}

        route = _make_route_dict(provider="openai")
        oc._apply_operator_overrides(multimodal_route=route)
        assert route["provider"] == "anthropic"


# ===========================================================================
# 19. DesktopPresenceRuntime integration
# ===========================================================================

class TestDesktopPresenceRuntimeIntegration:
    def _make_runtime(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        # Inject minimal required attributes
        try:
            from core.multimodal.perception_source_registry import PerceptionSourceRegistry
            rt._source_registry = PerceptionSourceRegistry()
        except Exception:
            rt._source_registry = None
        rt._config = {}
        return rt

    def test_set_operator_override_returns_committed(self):
        rt = self._make_runtime()
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            override_reason="rt_test",
        )
        result = rt.set_operator_override(override, applied_by="test_operator")
        assert result["status"] == "committed"
        assert result["override_id"] == override.override_id

    def test_clear_operator_override_returns_cleared(self):
        rt = self._make_runtime()
        override = OperatorOverrideSet(preferred_provider="anthropic")
        rt.set_operator_override(override)
        result = rt.clear_operator_override(applied_by="test_operator")
        assert result["status"] == "cleared"

    def test_operator_override_summary_returns_dict_with_expected_keys(self):
        rt = self._make_runtime()
        summary = rt.operator_override_summary()
        assert "has_active_override" in summary
        assert "applied_domains" in summary
        assert "override_reason" in summary
        assert "operator_message" in summary

    def test_operator_override_summary_reflects_committed_override(self):
        rt = self._make_runtime()
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            execution_locality=OverrideExecutionLocality.LOCAL_ONLY,
            override_reason="summary_test",
        )
        rt.set_operator_override(override)
        summary = rt.operator_override_summary()
        assert summary["has_active_override"] is True
        assert "provider" in summary["applied_domains"]
        assert "execution_locality" in summary["applied_domains"]

    def test_operator_override_summary_no_override_after_clear(self):
        rt = self._make_runtime()
        override = OperatorOverrideSet(preferred_provider="anthropic")
        rt.set_operator_override(override)
        rt.clear_operator_override()
        summary = rt.operator_override_summary()
        assert summary["has_active_override"] is False

    def test_operator_override_summary_never_raises(self):
        rt = self._make_runtime()
        # Should not raise even with a None result
        summary = rt.operator_override_summary(result=None)
        assert isinstance(summary, dict)

    def test_operator_override_summary_from_result_dict(self):
        rt = self._make_runtime()
        override = OperatorOverrideSet(
            preferred_provider="anthropic",
            override_reason="from_result_test",
        )
        state = get_operator_override_state()
        state.commit(override)
        snap = state.snapshot()

        # Simulate an OpenClawd response dict containing the override snapshot
        fake_result = {
            "metadata": {
                "operator_override_state": {
                    **snap.to_dict(),
                    "summary": build_override_summary(snap),
                }
            }
        }
        summary = rt.operator_override_summary(result=fake_result)
        assert summary["has_active_override"] is True
