"""
tests/test_android_presence_participation.py
=============================================
Behavioural tests for the dual-repo Android presence participation /
projection model (PR — Android Presence Participation).

These tests prove the following claims:

1. Android presence participation enters a canonical runtime structure that
   is distinct from execution / device metadata.
2. Presence-mode selection differs between the case where Android is an
   execution-only node and the case where Android is a presence participant.
3. Android presence participation is propagated into the PresenceProjection
   output — projection events carry a non-None
   ``android_presence_participation_mode`` for participating devices.
4. The runtime explicitly distinguishes Android-as-execution-node from
   Android-as-presence-participant in a single runtime path.

No test here validates field presence alone; each test exercises a behavioural
consequence of Android presence participation.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Group A — Android presence participation structure
# ===========================================================================


class TestAndroidPresenceParticipationStructure:
    """Verify that Android device states enter the canonical participation
    structure and are NOT reduced to plain device metadata."""

    def test_execution_only_device_is_not_a_presence_participant(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            AndroidPresenceParticipationMode,
        )

        rec = derive_android_presence_participation("device-exec-only")
        # No presence signals → EXECUTION_ONLY
        assert rec.participation_mode == AndroidPresenceParticipationMode.EXECUTION_ONLY
        assert not rec.is_presence_participant
        assert not rec.drives_liminal
        assert not rec.drives_manifest

    def test_active_engagement_makes_device_a_presence_participant(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            AndroidPresenceParticipationMode,
        )

        rec = derive_android_presence_participation(
            "device-engaged",
            active_engagement=True,
        )
        assert rec.participation_mode == AndroidPresenceParticipationMode.PRESENCE_PARTICIPANT
        assert rec.is_presence_participant
        assert rec.drives_liminal
        assert not rec.drives_manifest  # no execution coupling

    def test_sensing_stream_makes_device_a_presence_participant(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
        )

        rec = derive_android_presence_participation(
            "device-sensing",
            sensing_stream_active=True,
        )
        assert rec.is_presence_participant
        assert rec.drives_liminal

    def test_execution_presence_coupled_drives_manifest(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
        )

        rec = derive_android_presence_participation(
            "device-exec-coupled",
            active_engagement=True,
            execution_presence_coupled=True,
        )
        assert rec.is_presence_participant
        assert rec.drives_manifest

    def test_foreground_surface_plus_active_engagement_is_foreground_presence(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            AndroidPresenceParticipationMode,
        )

        rec = derive_android_presence_participation(
            "device-fg",
            active_engagement=True,
            is_foreground_surface=True,
        )
        assert rec.participation_mode == AndroidPresenceParticipationMode.FOREGROUND_PRESENCE
        assert rec.is_presence_participant

    def test_execution_only_override_suppresses_presence_signals(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            AndroidPresenceParticipationMode,
        )

        # Even with active engagement, execution_only_override forces EXECUTION_ONLY.
        rec = derive_android_presence_participation(
            "device-override",
            active_engagement=True,
            sensing_stream_active=True,
            execution_only_override=True,
        )
        assert rec.participation_mode == AndroidPresenceParticipationMode.EXECUTION_ONLY
        assert not rec.is_presence_participant

    def test_summary_aggregates_presence_participant_count(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        records = [
            derive_android_presence_participation("exec-only"),
            derive_android_presence_participation("participant-1", active_engagement=True),
            derive_android_presence_participation("participant-2", sensing_stream_active=True),
        ]
        summary = summarise_android_presence_participation(records)
        assert summary.any_presence_participant is True
        assert summary.presence_participant_count == 2
        assert summary.any_drives_liminal is True
        assert summary.any_drives_manifest is False

    def test_to_dict_carries_canonical_fields(self):
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
        )

        rec = derive_android_presence_participation(
            "device-dict",
            active_engagement=True,
        )
        d = rec.to_dict()
        assert "participation_mode" in d
        assert "is_presence_participant" in d
        assert "drives_liminal" in d
        assert "drives_manifest" in d
        assert d["is_presence_participant"] is True
        assert d["device_id"] == "device-dict"


# ===========================================================================
# Group B — Presence behaviour difference with Android participation
# ===========================================================================


class TestPresenceBehaviorDifferenceWithAndroidParticipation:
    """Prove that the DesktopPresenceStateMachine behaves differently when
    Android presence participation is active vs absent.

    This is the core evidence that Android presence participation is NOT just
    a metadata annotation: it directly changes state-machine decisions.
    """

    def _make_sm(self):
        from core.desktop_presence_system import DesktopPresenceStateMachine
        sm = DesktopPresenceStateMachine()
        # Advance time so min-hold constraints don't block transitions.
        sm.simulate_elapsed_time_for_testing(2.0)
        return sm

    def test_static_mode_does_not_transition_without_android_participation(self):
        """Without Android participation, silent tri-state + no tasks → STATIC."""
        sm = self._make_sm()
        result = sm.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
        )
        # Already in STATIC — no transition.
        assert result is None
        assert sm.mode.value == "static"

    def test_android_presence_participant_drives_static_to_liminal(self):
        """Android presence participant alone should push STATIC → LIMINAL even
        when V2-internal signals are all absent."""
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        sm = self._make_sm()
        android_summary = summarise_android_presence_participation([
            derive_android_presence_participation("device-A", active_engagement=True),
        ])

        result = sm.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
            android_presence_participation=android_summary,
        )
        # Android presence participation drove the transition.
        assert result is not None
        assert result["to_mode"] == "liminal"
        assert sm.mode.value == "liminal"
        # Transition record explicitly carries android participation evidence.
        assert result["android_presence_participant_count"] == 1
        assert result["android_drives_liminal"] is True

    def test_android_execution_only_does_not_drive_static_to_liminal(self):
        """Android execution-only device must NOT affect presence mode."""
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        sm = self._make_sm()
        android_summary = summarise_android_presence_participation([
            # execution_only_override=True: Android is only an execution node.
            derive_android_presence_participation("device-exec", execution_only_override=True),
        ])

        result = sm.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
            android_presence_participation=android_summary,
        )
        # No transition — STATIC remains STATIC.
        assert result is None
        assert sm.mode.value == "static"

    def test_android_execution_presence_coupled_drives_manifest(self):
        """Android device with execution_presence_coupled=True should drive
        STATIC → MANIFEST (skipping LIMINAL when execution evidence is clear)."""
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        sm = self._make_sm()
        android_summary = summarise_android_presence_participation([
            derive_android_presence_participation(
                "device-exec-coupled",
                active_engagement=True,
                execution_presence_coupled=True,
            ),
        ])

        result = sm.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
            android_presence_participation=android_summary,
        )
        assert result is not None
        assert result["to_mode"] == "manifest"
        assert sm.mode.value == "manifest"
        assert result["android_drives_manifest"] is True

    def test_presence_transition_without_android_participation_carries_zero_count(self):
        """Absence of android_presence_participation → participant count = 0 in record."""
        sm = self._make_sm()
        result = sm.update(
            tri_state="liminal",
            task_active=True,
            sensing_active=False,
            execution_active=False,
            user_interaction=True,
        )
        assert result is not None
        assert result["android_presence_participant_count"] == 0
        assert result["android_drives_liminal"] is False


# ===========================================================================
# Group C — Presence projection carries Android participation
# ===========================================================================


class TestPresenceProjectionIncludesAndroidPresenceParticipant:
    """Verify that PresenceProjection stamps android_presence_participation_mode
    on projection events for participating Android devices, and that non-
    participating / execution-only devices get no such stamp."""

    def _make_entry(self, device_id: str, roles: list = None):
        entry = SimpleNamespace(
            device_id=device_id,
            roles=roles or [],
        )
        return entry

    def test_android_presence_participant_gets_stamped_on_projection_event(self):
        from core.presence.presence_projection import (
            PresenceProjection,
            ProjectionIntensity,
        )
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        proj = PresenceProjection()
        android_summary = summarise_android_presence_participation([
            derive_android_presence_participation("android-device-1", active_engagement=True),
        ])

        entries = [self._make_entry("android-device-1")]

        with patch(
            "core.presence.presence_projection.PresenceProjection._emit_event"
        ):
            with patch(
                "core.mesh.body_mesh_registry.get_body_mesh_registry"
            ) as mock_registry:
                registry = MagicMock()
                registry.list_entries.return_value = entries
                registry.get_by_session.return_value = []
                mock_registry.return_value = registry

                events = proj.project(
                    cognitive_state={"phase": "liminal"},
                    android_presence_participation=android_summary,
                )

        assert len(events) == 1
        evt = events[0]
        assert evt.android_presence_participation_mode == "presence_participant"
        # Intensity is elevated to at least MEDIUM.
        assert evt.intensity >= float(ProjectionIntensity.MEDIUM)

    def test_execution_only_android_device_gets_no_participation_stamp(self):
        from core.presence.presence_projection import PresenceProjection
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        proj = PresenceProjection()
        android_summary = summarise_android_presence_participation([
            # execution_only: Android is not a presence participant.
            derive_android_presence_participation("exec-device", execution_only_override=True),
        ])

        entries = [self._make_entry("exec-device")]

        with patch(
            "core.presence.presence_projection.PresenceProjection._emit_event"
        ):
            with patch(
                "core.mesh.body_mesh_registry.get_body_mesh_registry"
            ) as mock_registry:
                registry = MagicMock()
                registry.list_entries.return_value = entries
                registry.get_by_session.return_value = []
                mock_registry.return_value = registry

                events = proj.project(
                    cognitive_state={"phase": "static"},
                    android_presence_participation=android_summary,
                )

        assert len(events) == 1
        evt = events[0]
        # Execution-only device: NO presence participation stamp.
        assert evt.android_presence_participation_mode is None

    def test_foreground_presence_device_gets_full_intensity(self):
        from core.presence.presence_projection import (
            PresenceProjection,
            ProjectionIntensity,
        )
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        proj = PresenceProjection()
        android_summary = summarise_android_presence_participation([
            derive_android_presence_participation(
                "fg-device",
                active_engagement=True,
                is_foreground_surface=True,
            ),
        ])

        entries = [self._make_entry("fg-device")]

        with patch(
            "core.presence.presence_projection.PresenceProjection._emit_event"
        ):
            with patch(
                "core.mesh.body_mesh_registry.get_body_mesh_registry"
            ) as mock_registry:
                registry = MagicMock()
                registry.list_entries.return_value = entries
                registry.get_by_session.return_value = []
                mock_registry.return_value = registry

                events = proj.project(
                    cognitive_state={"phase": "manifest"},
                    android_presence_participation=android_summary,
                )

        assert len(events) == 1
        evt = events[0]
        assert evt.android_presence_participation_mode == "foreground_presence"
        assert evt.intensity >= float(ProjectionIntensity.FULL)

    def test_projection_without_android_participation_has_no_stamp(self):
        from core.presence.presence_projection import PresenceProjection

        proj = PresenceProjection()
        entries = [self._make_entry("desktop")]

        with patch(
            "core.presence.presence_projection.PresenceProjection._emit_event"
        ):
            with patch(
                "core.mesh.body_mesh_registry.get_body_mesh_registry"
            ) as mock_registry:
                registry = MagicMock()
                registry.list_entries.return_value = entries
                registry.get_by_session.return_value = []
                mock_registry.return_value = registry

                events = proj.project(
                    cognitive_state={"phase": "manifest"},
                    # No android_presence_participation supplied.
                )

        assert len(events) == 1
        assert events[0].android_presence_participation_mode is None


# ===========================================================================
# Group D — Execution-vs-presence distinction
# ===========================================================================


class TestExecutionVsPresenceDistinction:
    """Prove that the runtime explicitly distinguishes Android-as-execution-node
    from Android-as-presence-participant in a single runtime path.

    The key invariant: two devices that are identically "online and capable of
    execution" are differentiated by their presence participation mode, and
    that distinction changes runtime behaviour (state-machine mode selection
    and projection intensity).
    """

    def test_two_identical_execution_capable_devices_differ_only_by_participation_flag(self):
        """Two Android devices: both execution-capable, but one has
        active_engagement=True (presence participant) and the other does not.
        Their participation modes must differ."""
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            AndroidPresenceParticipationMode,
        )

        exec_node = derive_android_presence_participation(
            "exec-node",
            # Execution-capable but no presence signals.
        )
        presence_node = derive_android_presence_participation(
            "presence-node",
            active_engagement=True,  # same execution capability + presence signal
        )

        assert exec_node.participation_mode == AndroidPresenceParticipationMode.EXECUTION_ONLY
        assert presence_node.participation_mode == AndroidPresenceParticipationMode.PRESENCE_PARTICIPANT
        assert not exec_node.is_presence_participant
        assert presence_node.is_presence_participant

    def test_execution_node_does_not_change_presence_mode_when_both_are_online(self):
        """Two devices online and execution-ready.  Only the presence-participant
        device changes the state-machine mode from STATIC."""
        from core.desktop_presence_system import DesktopPresenceStateMachine
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        # Scenario A: only execution node online (no presence participation).
        sm_a = DesktopPresenceStateMachine()
        sm_a.simulate_elapsed_time_for_testing(2.0)
        exec_only_summary = summarise_android_presence_participation([
            derive_android_presence_participation("exec-node", execution_only_override=True),
        ])
        result_a = sm_a.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
            android_presence_participation=exec_only_summary,
        )
        # No state change: execution node alone does not affect presence.
        assert result_a is None
        assert sm_a.mode.value == "static"

        # Scenario B: same execution node + presence participant online.
        sm_b = DesktopPresenceStateMachine()
        sm_b.simulate_elapsed_time_for_testing(2.0)
        mixed_summary = summarise_android_presence_participation([
            derive_android_presence_participation("exec-node", execution_only_override=True),
            derive_android_presence_participation("presence-node", active_engagement=True),
        ])
        result_b = sm_b.update(
            tri_state="silent",
            task_active=False,
            sensing_active=False,
            execution_active=False,
            user_interaction=False,
            android_presence_participation=mixed_summary,
        )
        # Presence participant drove transition to LIMINAL.
        assert result_b is not None
        assert result_b["to_mode"] == "liminal"
        assert sm_b.mode.value == "liminal"

    def test_director_records_android_participant_count_in_transition_result(self):
        """PresenceDirector.on_phase_transition must report the Android
        participant count in its return value — this is the canonical evidence
        that Android presence participation (not execution) reached the
        director layer."""
        from core.presence.presence_director import PresenceDirector, DirectorConfig
        from core.presence.android_presence_participation import (
            derive_android_presence_participation,
            summarise_android_presence_participation,
        )

        director = PresenceDirector(config=DirectorConfig(project_on_manifest=False))
        android_summary = summarise_android_presence_participation([
            derive_android_presence_participation("d1", active_engagement=True),
            derive_android_presence_participation("d2", sensing_stream_active=True),
            derive_android_presence_participation("d3", execution_only_override=True),
        ])

        result = director.on_phase_transition(
            from_phase="liminal",
            to_phase="manifest",
            cognitive_state={"intensity": 0.9},
            android_presence_participation=android_summary,
        )

        # Two presence participants; one execution-only.
        assert result["android_presence_participant_count"] == 2

    def test_projection_event_to_dict_distinguishes_participation_mode(self):
        """to_dict() on a ProjectionEvent must surface the participation mode
        so that downstream consumers can distinguish presence-participant events
        from execution-only or desktop events."""
        from core.presence.presence_projection import ProjectionEvent

        exec_evt = ProjectionEvent(
            device_id="exec-device",
            android_presence_participation_mode=None,
        )
        presence_evt = ProjectionEvent(
            device_id="presence-device",
            android_presence_participation_mode="presence_participant",
        )

        exec_dict = exec_evt.to_dict()
        presence_dict = presence_evt.to_dict()

        assert exec_dict["android_presence_participation_mode"] is None
        assert presence_dict["android_presence_participation_mode"] == "presence_participant"
