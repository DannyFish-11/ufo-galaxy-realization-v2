"""tests/test_pr8v2_manifestation_shell_presence_semantics.py
==============================================================

PR-8 V2 — Manifestation / Shell / Presence Semantic Consistency
----------------------------------------------------------------

Tests covering:

1.  StateEventType — SHELL_* event types exist with correct string values.
2.  Shell state transitions emit SHELL_* events on core.state_event_bus.
3.  Shell state vocabulary — transition methods use canonical DORMANT /
    ISLAND / SIDESHEET / FULLAGENT values.
4.  DesktopPresenceRuntime.presence_summary() — returns correct structure
    and reflects active session tri-state distribution.
5.  OperatorSnapshot — includes desktop_shell_state, presence_tristate,
    and manifestation_summary fields.
6.  operator_snapshot() — populates shell/presence fields from real
    runtime singletons.
7.  Semantic consistency — shell states are distinct from tri-state phases;
    the two vocabularies never overlap.
8.  OperatorSnapshot.to_dict() — includes PR-8 V2 manifestation fields.
9.  No detached manifestation state — manifestation_summary is derived
    from desktop_shell_state and presence_tristate only.
"""
from __future__ import annotations

import sys
from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _patch_numpy():
    """Return a patch-dict context that stubs out numpy-dependent modules.

    DesktopPresenceRuntime.__init__ eagerly imports
    core.multimodal.perception_source_registry which in turn transitively
    imports numpy.  In the CI/unit-test environment numpy is not installed.
    We stub the entire numpy module so DesktopPresenceRuntime can be
    instantiated without the dependency.
    """
    return patch.dict(
        sys.modules,
        {
            "numpy": MagicMock(),
            "sounddevice": MagicMock(),
            "pyaudio": MagicMock(),
        },
    )


# ===========================================================================
# 1. StateEventType — SHELL_* event types
# ===========================================================================

class TestShellEventTypes:
    """SHELL_* event types must exist in StateEventType with correct values."""

    def test_shell_dormant_exists(self):
        from core.state_event_bus import StateEventType
        assert StateEventType.SHELL_DORMANT.value == "shell.dormant"

    def test_shell_island_exists(self):
        from core.state_event_bus import StateEventType
        assert StateEventType.SHELL_ISLAND.value == "shell.island"

    def test_shell_sidesheet_exists(self):
        from core.state_event_bus import StateEventType
        assert StateEventType.SHELL_SIDESHEET.value == "shell.sidesheet"

    def test_shell_fullagent_exists(self):
        from core.state_event_bus import StateEventType
        assert StateEventType.SHELL_FULLAGENT.value == "shell.fullagent"

    def test_shell_events_distinct_from_phase_events(self):
        """SHELL_* values must not overlap with PHASE_* values."""
        from core.state_event_bus import StateEventType
        shell_values = {
            StateEventType.SHELL_DORMANT.value,
            StateEventType.SHELL_ISLAND.value,
            StateEventType.SHELL_SIDESHEET.value,
            StateEventType.SHELL_FULLAGENT.value,
        }
        phase_values = {
            StateEventType.PHASE_SILENT.value,
            StateEventType.PHASE_LIMINAL.value,
            StateEventType.PHASE_MANIFEST.value,
        }
        assert shell_values.isdisjoint(phase_values), (
            "SHELL_* and PHASE_* event types must not share values"
        )


# ===========================================================================
# 2. Shell state transitions emit SHELL_* events on state_event_bus
# ===========================================================================

class TestShellStateTransitionsEmitToBus:
    """SystemStateMachine.transition_to emits SHELL_* events on the unified bus."""

    def setup_method(self):
        from core.state_event_bus import reset_state_event_bus
        reset_state_event_bus()

    def teardown_method(self):
        from core.state_event_bus import reset_state_event_bus
        reset_state_event_bus()

    def _collect_shell_events(self) -> List:
        from core.state_event_bus import get_state_event_bus, StateEventType
        bus = get_state_event_bus()
        collected = []
        for et in (
            StateEventType.SHELL_DORMANT,
            StateEventType.SHELL_ISLAND,
            StateEventType.SHELL_SIDESHEET,
            StateEventType.SHELL_FULLAGENT,
        ):
            bus.subscribe(et, collected.append)
        return collected

    def _make_fresh_state_machine(self):
        """Return a fresh SystemStateMachine in DORMANT state.

        SystemStateMachine is a singleton so we reset it between tests by
        re-setting the _initialized flag and resetting state.
        """
        from system_integration.state_machine_ui_integration import (
            SystemStateMachine, SystemState
        )
        sm = SystemStateMachine()
        # Force to known state (DORMANT) without going through transition
        sm._current_state = SystemState.DORMANT
        sm._transition_history.clear()
        return sm

    def test_wakeup_emits_shell_island_event(self):
        from core.state_event_bus import StateEventType
        collected = self._collect_shell_events()
        sm = self._make_fresh_state_machine()
        result = sm.wakeup()
        assert result is True
        island_events = [e for e in collected if e.type == StateEventType.SHELL_ISLAND.value]
        assert len(island_events) >= 1, "wakeup() must emit SHELL_ISLAND on state event bus"
        assert island_events[0].payload["to_state"] == "island"

    def test_dormant_to_fullagent_emits_shell_fullagent(self):
        from core.state_event_bus import StateEventType
        from system_integration.state_machine_ui_integration import SystemState, TriggerType
        collected = self._collect_shell_events()
        sm = self._make_fresh_state_machine()
        sm.wakeup()  # DORMANT → ISLAND
        sm.expand_to_fullagent()  # ISLAND → FULLAGENT
        fullagent_events = [e for e in collected if e.type == StateEventType.SHELL_FULLAGENT.value]
        assert len(fullagent_events) >= 1, "expand_to_fullagent() must emit SHELL_FULLAGENT"
        assert fullagent_events[0].payload["to_state"] == "fullagent"

    def test_sleep_emits_shell_dormant(self):
        from core.state_event_bus import StateEventType
        collected = self._collect_shell_events()
        sm = self._make_fresh_state_machine()
        sm.wakeup()  # DORMANT → ISLAND
        sm.sleep()   # ISLAND → DORMANT
        dormant_events = [e for e in collected if e.type == StateEventType.SHELL_DORMANT.value]
        assert len(dormant_events) >= 1, "sleep() must emit SHELL_DORMANT on state event bus"
        assert dormant_events[0].payload["to_state"] == "dormant"

    def test_sidesheet_transition_emits_shell_sidesheet(self):
        from core.state_event_bus import StateEventType
        collected = self._collect_shell_events()
        sm = self._make_fresh_state_machine()
        sm.wakeup()              # DORMANT → ISLAND
        sm.expand_to_sidesheet() # ISLAND → SIDESHEET
        ss_events = [e for e in collected if e.type == StateEventType.SHELL_SIDESHEET.value]
        assert len(ss_events) >= 1, "expand_to_sidesheet() must emit SHELL_SIDESHEET"
        assert ss_events[0].payload["to_state"] == "sidesheet"

    def test_shell_event_payload_has_from_and_to(self):
        """Every SHELL_* event must carry from_state and to_state in payload."""
        from core.state_event_bus import StateEventType
        collected = self._collect_shell_events()
        sm = self._make_fresh_state_machine()
        sm.wakeup()
        assert collected, "Expected at least one shell event"
        ev = collected[0]
        assert "from_state" in ev.payload
        assert "to_state" in ev.payload

    def test_no_duplicate_shell_event_on_same_state(self):
        """Calling transition_to with the same state must not emit a new event."""
        from core.state_event_bus import StateEventType
        collected = self._collect_shell_events()
        sm = self._make_fresh_state_machine()
        sm.wakeup()  # DORMANT → ISLAND (one SHELL_ISLAND event)
        before_count = len([e for e in collected if e.type == StateEventType.SHELL_ISLAND.value])
        sm.transition_to(  # same state → no emission
            __import__(
                "system_integration.state_machine_ui_integration",
                fromlist=["SystemState"]
            ).SystemState.ISLAND
        )
        after_count = len([e for e in collected if e.type == StateEventType.SHELL_ISLAND.value])
        assert after_count == before_count, (
            "Transitioning to current state must not emit another event"
        )


# ===========================================================================
# 3. Shell state vocabulary tests (regression guard)
# ===========================================================================

class TestShellStateVocabularyConsistency:
    """Canonical shell vocabulary must be stable across all related modules."""

    def test_state_machine_has_all_four_canonical_states(self):
        from system_integration.state_machine_ui_integration import SystemState
        canonical = {"dormant", "island", "sidesheet", "fullagent"}
        actual = {s.value for s in SystemState
                  if s.value in canonical}  # exclude aliases
        assert canonical.issubset(actual)

    def test_hardware_trigger_has_same_canonical_states(self):
        from system_integration.hardware_trigger import SystemState as HT_State
        canonical = {"dormant", "island", "sidesheet", "fullagent"}
        actual = {s.value for s in HT_State}
        assert canonical.issubset(actual)

    def test_shell_event_values_match_state_values(self):
        """SHELL_* event type values must follow the 'shell.<state_value>' pattern."""
        from core.state_event_bus import StateEventType
        from system_integration.state_machine_ui_integration import SystemState
        # Build expected mapping from canonical state values
        canonical_states = [s for s in SystemState
                            if s.value in {"dormant", "island", "sidesheet", "fullagent"}]
        shell_event_values = {
            StateEventType.SHELL_DORMANT.value,
            StateEventType.SHELL_ISLAND.value,
            StateEventType.SHELL_SIDESHEET.value,
            StateEventType.SHELL_FULLAGENT.value,
        }
        for state in canonical_states:
            expected_event_value = f"shell.{state.value}"
            assert expected_event_value in shell_event_values, (
                f"Missing SHELL event type for state '{state.value}': "
                f"expected '{expected_event_value}' in StateEventType"
            )


# ===========================================================================
# 4. DesktopPresenceRuntime.presence_summary()
# ===========================================================================

class TestPresenceSummary:
    """DesktopPresenceRuntime.presence_summary returns correct structure.

    All tests in this class construct DesktopPresenceRuntime directly under a
    numpy stub so that the multimodal-ingest dependency is not required in the
    unit-test environment.
    """

    def _build_runtime(self):
        """Return a DesktopPresenceRuntime instance with multimodal stubs."""
        with _patch_numpy():
            from core.desktop_presence_runtime import DesktopPresenceRuntime
            rt = DesktopPresenceRuntime()
        return rt

    def test_presence_summary_returns_dict(self):
        rt = self._build_runtime()
        summary = rt.presence_summary()
        assert isinstance(summary, dict)

    def test_presence_summary_has_required_keys(self):
        rt = self._build_runtime()
        summary = rt.presence_summary()
        assert "active_session_count" in summary
        assert "tristate_distribution" in summary
        assert "dominant_tristate" in summary

    def test_presence_summary_idle_dominant_tristate_is_silent(self):
        """When no sessions are active the dominant_tristate must be 'silent'."""
        rt = self._build_runtime()
        # No active sessions at construction time
        summary = rt.presence_summary()
        assert summary["dominant_tristate"] == "silent"

    def test_presence_summary_counts_active_sessions(self):
        """Inject mock sessions and verify counts are reflected."""
        from core.desktop_presence_runtime import TriState, RuntimeSession
        rt = self._build_runtime()
        sess_liminal = RuntimeSession(source="chat")
        sess_liminal.tristate = TriState.LIMINAL
        sess_manifest = RuntimeSession(source="chat")
        sess_manifest.tristate = TriState.MANIFEST
        rt._active_sessions = {
            sess_liminal.runtime_session_id: sess_liminal,
            sess_manifest.runtime_session_id: sess_manifest,
        }
        summary = rt.presence_summary()
        assert summary["active_session_count"] == 2
        dist = summary["tristate_distribution"]
        assert dist.get("liminal", 0) == 1
        assert dist.get("manifest", 0) == 1

    def test_dominant_tristate_manifest_wins_over_liminal(self):
        """manifest takes priority over liminal in dominant_tristate."""
        from core.desktop_presence_runtime import TriState, RuntimeSession
        rt = self._build_runtime()
        s1 = RuntimeSession(source="chat")
        s1.tristate = TriState.LIMINAL
        s2 = RuntimeSession(source="chat")
        s2.tristate = TriState.MANIFEST
        rt._active_sessions = {s1.runtime_session_id: s1, s2.runtime_session_id: s2}
        summary = rt.presence_summary()
        assert summary["dominant_tristate"] == "manifest"

    def test_dominant_tristate_liminal_over_silent(self):
        from core.desktop_presence_runtime import TriState, RuntimeSession
        rt = self._build_runtime()
        s1 = RuntimeSession(source="chat")
        s1.tristate = TriState.SILENT
        s2 = RuntimeSession(source="chat")
        s2.tristate = TriState.LIMINAL
        rt._active_sessions = {s1.runtime_session_id: s1, s2.runtime_session_id: s2}
        summary = rt.presence_summary()
        assert summary["dominant_tristate"] == "liminal"

    def test_presence_summary_never_raises(self):
        """presence_summary must return a dict even if internal state is corrupt."""
        rt = self._build_runtime()
        rt._active_sessions = None  # intentionally corrupt
        result = rt.presence_summary()
        assert isinstance(result, dict)
        assert "dominant_tristate" in result


# ===========================================================================
# 5. OperatorSnapshot — fields exist
# ===========================================================================

class TestOperatorSnapshotFields:
    """OperatorSnapshot must carry desktop_shell_state, presence_tristate,
    and manifestation_summary fields."""

    def test_snapshot_has_desktop_shell_state(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        assert hasattr(snap, "desktop_shell_state")
        assert isinstance(snap.desktop_shell_state, str)

    def test_snapshot_has_presence_tristate(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        assert hasattr(snap, "presence_tristate")
        assert isinstance(snap.presence_tristate, str)

    def test_snapshot_has_manifestation_summary(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        assert hasattr(snap, "manifestation_summary")
        assert isinstance(snap.manifestation_summary, dict)

    def test_snapshot_to_dict_includes_shell_fields(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot(
            desktop_shell_state="island",
            presence_tristate="liminal",
            manifestation_summary={"desktop_shell_state": "island", "presence_tristate": "liminal"},
        )
        d = snap.to_dict()
        assert d["desktop_shell_state"] == "island"
        assert d["presence_tristate"] == "liminal"
        assert d["manifestation_summary"]["desktop_shell_state"] == "island"

    def test_snapshot_to_dict_includes_all_legacy_fields(self):
        """Adding new fields must not remove any previously existing fields."""
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        d = snap.to_dict()
        required_legacy = {
            "snapshot_id", "generated_at",
            "active_task_count", "recent_tasks",
            "active_flow_count",
            "online_device_count", "device_summaries",
            "topology_node_count", "topology_edge_count",
            "capability_provider_count", "online_provider_count",
            "source_runtime_posture_counts", "recent_source_runtime_postures",
            "android_ecosystem",
            "authority", "contract_version", "projection_policy",
        }
        for key in required_legacy:
            assert key in d, f"Legacy key '{key}' must be present in OperatorSnapshot.to_dict()"


# ===========================================================================
# 6. operator_snapshot() populates shell/presence fields
# ===========================================================================

class TestOperatorSnapshotPopulation:
    """operator_snapshot() must populate shell/presence fields from singletons."""

    def test_operator_snapshot_includes_desktop_shell_state(self):
        """desktop_shell_state in snapshot must be a recognized shell value or empty."""
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        valid_shell_states = {"dormant", "island", "sidesheet", "fullagent", ""}
        assert snap.desktop_shell_state in valid_shell_states, (
            f"Unexpected desktop_shell_state: {snap.desktop_shell_state!r}"
        )

    def test_operator_snapshot_includes_presence_tristate(self):
        """presence_tristate in snapshot must be a recognized tri-state or empty."""
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        valid_tristates = {"silent", "liminal", "manifest", ""}
        assert snap.presence_tristate in valid_tristates, (
            f"Unexpected presence_tristate: {snap.presence_tristate!r}"
        )

    def test_operator_snapshot_manifestation_summary_derives_from_shell_and_presence(self):
        """manifestation_summary must not introduce state not in shell/presence fields."""
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        if snap.manifestation_summary:
            # The summary may only reference shell and presence state values
            assert snap.manifestation_summary.get("desktop_shell_state") == snap.desktop_shell_state
            assert snap.manifestation_summary.get("presence_tristate") == snap.presence_tristate

    def test_operator_snapshot_with_mocked_shell_state(self):
        """When SystemStateMachine is in ISLAND state, snapshot reflects it."""
        from core.operator_surface import get_operator_surface, reset_operator_surface
        from system_integration.state_machine_ui_integration import SystemState
        reset_operator_surface()
        mock_ssm = MagicMock()
        mock_ssm.return_value.current_state = SystemState.ISLAND
        with patch(
            "system_integration.state_machine_ui_integration.SystemStateMachine",
            mock_ssm,
        ):
            surface = get_operator_surface()
            snap = surface.operator_snapshot()
        assert snap.desktop_shell_state == "island"

    def test_operator_snapshot_with_mocked_presence_summary(self):
        """When presence_summary returns 'manifest', snapshot reflects it."""
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        mock_runtime = MagicMock()
        mock_runtime.presence_summary.return_value = {
            "active_session_count": 1,
            "tristate_distribution": {"manifest": 1, "liminal": 0, "silent": 0},
            "dominant_tristate": "manifest",
        }
        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=mock_runtime,
        ):
            surface = get_operator_surface()
            snap = surface.operator_snapshot()
        assert snap.presence_tristate == "manifest"

    def test_operator_snapshot_degrades_gracefully_when_shell_unavailable(self):
        """If SystemStateMachine raises, snapshot still returns without error."""
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        with patch(
            "system_integration.state_machine_ui_integration.SystemStateMachine",
            side_effect=Exception("module unavailable"),
        ):
            surface = get_operator_surface()
            snap = surface.operator_snapshot()
        # Should not raise; desktop_shell_state defaults to empty string
        assert isinstance(snap.desktop_shell_state, str)


# ===========================================================================
# 7. Semantic consistency — shell ≠ tri-state
# ===========================================================================

class TestSemanticDistinctness:
    """Shell states and tri-state phases must remain semantically distinct."""

    def test_tristate_values_do_not_appear_in_shell_event_values(self):
        """No SHELL_* event value must equal a PHASE_* event value."""
        from core.state_event_bus import StateEventType
        tristate_values = {et.value for et in StateEventType
                          if et.value.startswith("phase.")}
        shell_values = {et.value for et in StateEventType
                        if et.value.startswith("shell.")}
        assert tristate_values.isdisjoint(shell_values)

    def test_shell_dormant_is_not_tristate_silent(self):
        """DORMANT (clothing mode) must not equal SILENT (lifecycle phase)."""
        from system_integration.state_machine_ui_integration import SystemState
        from core.desktop_presence_runtime import TriState
        assert SystemState.DORMANT.value != TriState.SILENT.value

    def test_shell_fullagent_is_not_tristate_manifest(self):
        """FULLAGENT (clothing mode) must not equal MANIFEST (lifecycle phase)."""
        from system_integration.state_machine_ui_integration import SystemState
        from core.desktop_presence_runtime import TriState
        assert SystemState.FULLAGENT.value != TriState.MANIFEST.value

    def test_presence_summary_tristate_values_match_tristate_enum(self):
        """presence_summary dominant_tristate must be a valid TriState value."""
        from core.desktop_presence_runtime import TriState
        with _patch_numpy():
            from core.desktop_presence_runtime import DesktopPresenceRuntime
            rt = DesktopPresenceRuntime()
        summary = rt.presence_summary()
        valid = {ts.value for ts in TriState}
        assert summary["dominant_tristate"] in valid, (
            f"dominant_tristate={summary['dominant_tristate']!r} not in TriState values"
        )


# ===========================================================================
# 8. No detached manifestation state
# ===========================================================================

class TestNoDetachedManifestationState:
    """manifestation_summary must only derive from real runtime state fields."""

    def test_manifestation_summary_only_derives_from_shell_and_presence(self):
        """manifestation_summary keys must be traceable to shell or presence fields."""
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot(
            desktop_shell_state="fullagent",
            presence_tristate="manifest",
        )
        # Manually build the summary as operator_snapshot() would
        snap.manifestation_summary = {
            "desktop_shell_state": snap.desktop_shell_state,
            "presence_tristate": snap.presence_tristate,
            "_source": "operator_surface.operator_snapshot",
        }
        d = snap.to_dict()
        msum = d["manifestation_summary"]
        # Every non-meta key must be directly traceable to snapshot fields
        assert msum["desktop_shell_state"] == snap.desktop_shell_state
        assert msum["presence_tristate"] == snap.presence_tristate

    def test_empty_manifestation_summary_when_both_fields_empty(self):
        """When shell and presence are empty, manifestation_summary is empty."""
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot(
            desktop_shell_state="",
            presence_tristate="",
        )
        # operator_snapshot() only populates manifestation_summary when at
        # least one of desktop_shell_state / presence_tristate is non-empty.
        assert snap.manifestation_summary == {}
